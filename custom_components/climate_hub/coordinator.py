"""Coordinator: reads HA, runs the engine, persists, publishes (integration §6)."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import issues
from .const import (
    CONTACT_RECHECK,
    DOMAIN,
    FORECAST_BACKSTOP,
    FORECAST_MIN_GAP,
    LOGGER,
    REFRESH_COOLDOWN,
    REGISTRY_DEBOUNCE,
    TICK,
)
from .logic.engine import Comfort, EngineResult, EngineState, Forecast, evaluate
from .logic.model import HouseModel
from .registry import build_model
from .snapshot import async_fetch_forecast, build_snapshot, referenced_entities
from .store import ClimateHubStore, SeenEntry, StoreData


@dataclass
class ClimateHubData:
    """Runtime data of a hub entry."""

    coordinator: ClimateHubCoordinator
    store: ClimateHubStore


type ClimateHubConfigEntry = ConfigEntry[ClimateHubData]


class ClimateHubCoordinator(DataUpdateCoordinator[EngineResult]):
    """One evaluation per tick or state change; owns all listeners and timers."""

    config_entry: ClimateHubConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ClimateHubConfigEntry,
        model: HouseModel,
        store: ClimateHubStore,
        stored: StoreData,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=TICK,
            request_refresh_debouncer=Debouncer(
                hass,
                LOGGER,
                cooldown=REFRESH_COOLDOWN.total_seconds(),
                immediate=True,
            ),
            always_update=True,
        )
        self.model = model
        self.store = store
        self.state: EngineState = stored.engine
        self.comfort: Comfort = stored.comfort
        self.forecast: Forecast | None = None
        self.seen: dict[str, SeenEntry] = stored.seen
        self.area_sync: dict[str, dict[str, str]] = stored.area_sync
        self.device_areas: dict[str, str] = stored.device_areas
        self._started = False
        self._failures: Mapping[str, str] = {}
        self._forecast_fetched: datetime | None = None
        self._recheck: CALLBACK_TYPE | None = None
        self._registry_timer: CALLBACK_TYPE | None = None

    def store_data(self) -> StoreData:
        """The content the Store writes."""
        return StoreData(
            engine=self.state,
            comfort=self.comfort,
            seen=self.seen,
            area_sync=self.area_sync,
            device_areas=self.device_areas,
        )

    # Lifecycle

    async def async_start(self) -> None:
        """Subscribe to everything; the first evaluation waits for HA start (I14)."""
        entry = self.config_entry
        entry.async_on_unload(
            async_track_state_change_event(
                self.hass, referenced_entities(self.model), self._state_changed
            )
        )
        if self.model.weather:
            entry.async_on_unload(
                async_track_time_interval(self.hass, self._backstop, FORECAST_BACKSTOP)
            )
        for event_type in (
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            ar.EVENT_AREA_REGISTRY_UPDATED,
        ):
            entry.async_on_unload(
                self.hass.bus.async_listen(event_type, self._registry_changed)
            )
        # The tick runs only while someone listens; learning and timers must not stop
        # when every entity is disabled.
        entry.async_on_unload(self.async_add_listener(lambda: None))
        entry.async_on_unload(self._cancel_timers)
        entry.async_on_unload(async_at_started(self.hass, self._async_first_run))

    async def _async_first_run(self, _hass: HomeAssistant) -> None:
        await self._async_fetch_forecast()
        self._started = True
        await self.async_refresh()
        if self.last_update_success:
            issues.async_sync_new_sources(self.hass, self.config_entry, self)

    async def async_shutdown(self) -> None:
        """Cancel timers and write the Store at once."""
        self._cancel_timers()
        await super().async_shutdown()
        await self.store.async_save(self.store_data())

    @callback
    def _cancel_timers(self) -> None:
        if self._recheck is not None:
            self._recheck()
            self._recheck = None
        if self._registry_timer is not None:
            self._registry_timer()
            self._registry_timer = None

    @callback
    def _request(self) -> None:
        """Debounced refresh, never before the first evaluation."""
        if self._started:
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), f"{DOMAIN} refresh"
            )

    # Listeners

    @callback
    def _state_changed(self, event: Event[Any]) -> None:
        if event.data["entity_id"] == self.model.weather and self._forecast_due():
            self.config_entry.async_create_background_task(
                self.hass, self._async_weather_changed(), f"{DOMAIN} forecast"
            )
            return
        self._request()

    async def _async_weather_changed(self) -> None:
        await self._async_fetch_forecast()
        self._request()

    def _forecast_due(self) -> bool:
        return (
            self._forecast_fetched is None
            or dt_util.utcnow() - self._forecast_fetched >= FORECAST_MIN_GAP
        )

    async def _async_fetch_forecast(self) -> None:
        if not self.model.weather:
            return
        self._forecast_fetched = dt_util.utcnow()
        # A failed fetch keeps the last forecast; the strategy only reads its future
        # points, so a short outage of the weather service does not flip it.
        if forecast := await async_fetch_forecast(self.hass, self.model.weather):
            self.forecast = forecast

    async def _backstop(self, _now: datetime) -> None:
        await self._async_fetch_forecast()

    @callback
    def _registry_changed(self, _event: Event[Any]) -> None:
        """Debounce registry events: restart the timer on each one."""
        if self._registry_timer is not None:
            self._registry_timer()
        self._registry_timer = async_call_later(
            self.hass, REGISTRY_DEBOUNCE, self._registry_settled
        )

    @callback
    def _registry_settled(self, _now: datetime) -> None:
        self._registry_timer = None
        if build_model(self.hass, self.config_entry) != self.model:
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        elif self.data is not None:
            issues.async_sync_new_sources(self.hass, self.config_entry, self)

    # Evaluation

    async def _async_update_data(self) -> EngineResult:
        now = dt_util.now()
        snapshot = build_snapshot(self.hass, self.model, self.forecast)
        result, state = evaluate(self.model, snapshot, self.state, self.comfort, now)
        self._log_failures(result.failures)
        objects = {*self.model.rooms, *self.model.regions, *self.model.windows}
        if objects and objects <= result.failures.keys():
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="evaluation_failed"
            )
        self.state = state
        self.store.schedule_save(self.store_data)
        self._schedule_recheck(state)
        await issues.async_sync_outages(
            self.hass, self.config_entry, self.model, result
        )
        return result

    def _log_failures(self, failures: Mapping[str, str]) -> None:
        for object_id, error in failures.items():
            if object_id not in self._failures:
                LOGGER.warning("Evaluation of %s failed: %s", object_id, error)
        for object_id in self._failures.keys() - failures.keys():
            LOGGER.info("Evaluation of %s recovered", object_id)
        self._failures = dict(failures)

    def _schedule_recheck(self, state: EngineState) -> None:
        if self._recheck is not None:
            self._recheck()
            self._recheck = None
        if any(
            w.debounced is not None and w.debounced.raw != w.debounced.published
            for w in state.windows.values()
        ):
            self._recheck = async_call_later(
                self.hass, CONTACT_RECHECK, self._async_recheck
            )

    async def _async_recheck(self, _now: datetime) -> None:
        self._recheck = None
        await self.async_refresh()

    # Comfort numbers (H2, I8, I13)

    async def async_set_comfort(
        self,
        c_min: float | None = None,
        c_max: float | None = None,
        threshold: float | None = None,
    ) -> None:
        """Validate and store new comfort values, save at once, re-evaluate."""
        new = replace(
            self.comfort,
            c_min=self.comfort.c_min if c_min is None else c_min,
            c_max=self.comfort.c_max if c_max is None else c_max,
            threshold=self.comfort.threshold if threshold is None else threshold,
        )
        if new.c_min >= new.c_max:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="comfort_range_invalid",
                translation_placeholders={
                    "min": f"{new.c_min:g}",
                    "max": f"{new.c_max:g}",
                },
            )
        if new.threshold <= 0:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="comfort_threshold_invalid",
                translation_placeholders={"threshold": f"{new.threshold:g}"},
            )
        self.comfort = new
        await self.store.async_save(self.store_data())
        self._request()
