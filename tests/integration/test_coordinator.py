"""Coordinator: cadence, forecast, start-up, registry, persistence, isolation."""

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.climate_hub import coordinator as coordinator_module
from custom_components.climate_hub.const import (
    CONTACT_RECHECK,
    DOMAIN,
    FORECAST_BACKSTOP,
    FORECAST_MIN_GAP,
    REFRESH_COOLDOWN,
    REGISTRY_DEBOUNCE,
    SUBENTRY_REGION,
    SUBENTRY_ROOM,
    SUBENTRY_WINDOW,
    TICK,
)
from custom_components.climate_hub.coordinator import ClimateHubCoordinator
from custom_components.climate_hub.logic import engine
from custom_components.climate_hub.logic import model as m
from custom_components.climate_hub.logic.engine import Comfort
from custom_components.climate_hub.logic.sources import Metric
from custom_components.climate_hub.logic.window import Level
from custom_components.climate_hub.registry import build_model
from custom_components.climate_hub.store import ClimateHubStore
from tests.house import House, set_value


def _sub(kind: str, sub_id: str, data: dict[str, Any]) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=data,
        subentry_type=kind,
        title=sub_id,
        unique_id=None,
        subentry_id=sub_id,
    )


def _entry(house: House) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={m.CONF_WEATHER: house.weather},
        subentries_data=[
            _sub(
                SUBENTRY_ROOM,
                "r_living",
                {
                    m.CONF_AREA: house.living_room,
                    m.CONF_SIDE: "s",
                    m.CONF_TEMPERATURE: [house.living_temp, house.living_air_temp],
                },
            ),
            _sub(
                SUBENTRY_ROOM,
                "r_bedroom",
                {m.CONF_AREA: house.bedroom, m.CONF_TEMPERATURE: [house.bedroom_temp]},
            ),
            _sub(
                SUBENTRY_REGION,
                "g_garden",
                {
                    m.CONF_AREA: house.garden,
                    m.CONF_DIRECTION: "n",
                    m.CONF_TEMPERATURE: [house.garden_temp],
                },
            ),
            _sub(
                SUBENTRY_WINDOW,
                "w_living",
                {
                    m.CONF_AREA: house.living_room,
                    m.CONF_TYPE: m.WINDOW_SINGLE,
                    m.CONF_NAME: "Fenster",
                    m.CONF_LEAF: house.living_leaf_1,
                },
            ),
        ],
    )


async def _setup(hass: HomeAssistant, house: House) -> ClimateHubCoordinator:
    entry = _entry(house)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    # Entities (build step 8) will listen; the tick only runs while someone does.
    entry.async_on_unload(coordinator.async_add_listener(lambda: None))
    return coordinator


async def _advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.fixture
def evaluations(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Every call of the engine, recording `now`."""
    calls: list[Any] = []
    real = engine.evaluate

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(args[-1])
        return real(*args, **kwargs)

    monkeypatch.setattr(coordinator_module, "evaluate", counting)
    return calls


@pytest.fixture
def forecast_fetches(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = coordinator_module.async_fetch_forecast

    async def counting(hass: HomeAssistant, weather_id: str) -> Any:
        calls.append(weather_id)
        return await real(hass, weather_id)

    monkeypatch.setattr(coordinator_module, "async_fetch_forecast", counting)
    return calls


async def test_first_evaluation_and_tick(
    hass: HomeAssistant,
    house: House,
    freezer: FrozenDateTimeFactory,
    evaluations: list[Any],
) -> None:
    coordinator = await _setup(hass, house)
    assert len(evaluations) == 1
    result = coordinator.data
    assert result.rooms["r_living"].temperature.value is not None
    assert result.rooms["r_bedroom"].temperature.value == pytest.approx(18.9)
    assert "g_garden" in result.regions
    assert "w_living" in result.windows
    assert not result.failures

    await _advance(hass, freezer, TICK)
    assert len(evaluations) == 2
    await _advance(hass, freezer, TICK)
    assert len(evaluations) == 3


async def test_burst_gives_at_most_two_evaluations(
    hass: HomeAssistant,
    house: House,
    freezer: FrozenDateTimeFactory,
    evaluations: list[Any],
) -> None:
    await _setup(hass, house)
    before = len(evaluations)
    for i in range(10):
        set_value(hass, house.bedroom_temp, 19.0 + i / 10)
        await hass.async_block_till_done()
        freezer.tick(timedelta(milliseconds=100))
    await _advance(hass, freezer, REFRESH_COOLDOWN + timedelta(seconds=1))
    assert 1 <= len(evaluations) - before <= 2


async def test_contact_change_publishes_after_debounce(
    hass: HomeAssistant,
    house: House,
    freezer: FrozenDateTimeFactory,
    evaluations: list[Any],
) -> None:
    coordinator = await _setup(hass, house)
    assert coordinator.data.windows["w_living"].state.level is Level.CLOSED

    set_value(hass, house.living_leaf_1, "on")
    await hass.async_block_till_done()
    assert coordinator.data.windows["w_living"].state.level is Level.CLOSED

    await _advance(hass, freezer, CONTACT_RECHECK + timedelta(seconds=0.1))
    assert coordinator.data.windows["w_living"].state.level is not Level.CLOSED


async def test_forecast_rules(
    hass: HomeAssistant,
    house: House,
    freezer: FrozenDateTimeFactory,
    evaluations: list[Any],
    forecast_fetches: list[str],
) -> None:
    coordinator = await _setup(hass, house)
    assert forecast_fetches == [house.weather]
    assert coordinator.forecast is not None

    # A weather change within the minimum gap does not refetch.
    set_value(hass, house.weather, "sunny", temperature=13.0)
    await _advance(hass, freezer, timedelta(seconds=10))
    assert len(forecast_fetches) == 1

    # After the gap it does.
    await _advance(hass, freezer, FORECAST_MIN_GAP)
    set_value(hass, house.weather, "cloudy", temperature=14.0)
    await hass.async_block_till_done()
    assert len(forecast_fetches) == 2

    # The backstop fetches on its own.
    await _advance(hass, freezer, FORECAST_BACKSTOP)
    assert len(forecast_fetches) == 3


async def test_nothing_evaluates_before_start(
    hass: HomeAssistant, house: House, evaluations: list[Any]
) -> None:
    hass.set_state(CoreState.starting)
    coordinator = await _setup(hass, house)
    set_value(hass, house.bedroom_temp, 19.5)
    await hass.async_block_till_done()
    assert not evaluations
    assert coordinator.last_update_success
    assert coordinator.data is None

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert len(evaluations) == 1
    assert coordinator.data is not None


async def test_tick_waits_for_start(
    hass: HomeAssistant,
    house: House,
    freezer: FrozenDateTimeFactory,
    evaluations: list[Any],
) -> None:
    """Listeners exist from setup on, but the tick must not beat the start (I14)."""
    hass.set_state(CoreState.starting)
    coordinator = await _setup(hass, house)
    await _advance(hass, freezer, TICK * 2)
    assert not evaluations
    assert coordinator.data is None

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert len(evaluations) == 1

    await _advance(hass, freezer, TICK)
    assert len(evaluations) == 2


async def _count_setups(
    hass: HomeAssistant, patch_target: str, action: Callable[[], None]
) -> int:
    with patch(patch_target, return_value=True) as setup:
        action()
        await hass.async_block_till_done()
    return setup.call_count


async def test_registry_change_reloads_once(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    coordinator = await _setup(hass, house)
    target = "custom_components.climate_hub.async_setup_entry"
    ent_reg = er.async_get(hass)

    def rename() -> None:
        ent_reg.async_update_entity(house.study_hum, name="Anders benannt")

    assert await _count_setups(hass, target, rename) == 0
    with patch(target, return_value=True) as setup:
        await _advance(hass, freezer, REGISTRY_DEBOUNCE + timedelta(seconds=1))
        assert setup.call_count == 0

        device_id = ent_reg.async_get(house.bedroom_temp).device_id
        for object_id in ("bedroom_hum", "bedroom_hum_2"):
            new = ent_reg.async_get_or_create(
                "sensor",
                "test",
                object_id,
                suggested_object_id=object_id,
                device_id=device_id,
                original_device_class="humidity",
            )
            hass.states.async_set(
                new.entity_id,
                "55",
                {"device_class": "humidity", "unit_of_measurement": "%"},
            )
        await hass.async_block_till_done()
        assert setup.call_count == 0

        await _advance(hass, freezer, REGISTRY_DEBOUNCE + timedelta(seconds=1))
        assert setup.call_count == 1
        await _advance(hass, freezer, timedelta(minutes=10))
        assert setup.call_count == 1
    assert build_model(hass, coordinator.config_entry) != coordinator.model


async def test_state_survives_reload(hass: HomeAssistant, house: House) -> None:
    coordinator = await _setup(hass, house)
    entry = coordinator.config_entry
    offsets = coordinator.state.rooms["r_living"].sources[Metric.TEMPERATURE].offsets
    assert offsets

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    stored = await ClimateHubStore(hass, entry.entry_id).async_load(coordinator.model)
    assert stored.engine == coordinator.state

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    again = entry.runtime_data.coordinator
    assert again is not coordinator
    reloaded = again.state.rooms["r_living"].sources[Metric.TEMPERATURE].offsets
    assert reloaded.keys() == offsets.keys()


async def test_comfort_saves_at_once_and_validates(
    hass: HomeAssistant, house: House
) -> None:
    coordinator = await _setup(hass, house)
    entry = coordinator.config_entry
    await coordinator.async_set_comfort(c_min=19.0, c_max=25.5, threshold=3.0)
    expected = Comfort(19.0, 25.5, 3.0)
    assert coordinator.comfort == expected
    stored = await ClimateHubStore(hass, entry.entry_id).async_load(coordinator.model)
    assert stored.comfort == expected

    with pytest.raises(ServiceValidationError) as err:
        await coordinator.async_set_comfort(c_min=26.0)
    assert err.value.translation_key == "comfort_range_invalid"
    assert err.value.translation_placeholders == {"min": "26", "max": "25.5"}
    assert coordinator.comfort == expected

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator.comfort == expected


async def test_failure_is_logged_once(
    hass: HomeAssistant,
    house: House,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    real = engine._evaluate_room
    broken = {"on": True}

    def failing(room: Any, *args: Any, **kwargs: Any) -> Any:
        if broken["on"] and room.id == "r_bedroom":
            raise ValueError("boom")
        return real(room, *args, **kwargs)

    monkeypatch.setattr(engine, "_evaluate_room", failing)
    caplog.set_level(logging.INFO, logger="custom_components.climate_hub")
    coordinator = await _setup(hass, house)
    await _advance(hass, freezer, TICK)
    await _advance(hass, freezer, TICK)

    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name.startswith("custom_components")
    ]
    assert len(warnings) == 1
    assert "r_bedroom" in warnings[0].getMessage()
    assert "boom" in warnings[0].getMessage()
    assert "r_bedroom" not in coordinator.data.rooms
    assert "r_living" in coordinator.data.rooms
    assert coordinator.last_update_success

    broken["on"] = False
    await _advance(hass, freezer, TICK)
    assert "r_bedroom" in coordinator.data.rooms
    assert any(
        r.levelno == logging.INFO and "recovered" in r.getMessage()
        for r in caplog.records
    )


async def test_remove_entry_deletes_store(
    hass: HomeAssistant, house: House, hass_storage: dict[str, Any]
) -> None:
    coordinator = await _setup(hass, house)
    entry = coordinator.config_entry
    key = f"{DOMAIN}.{entry.entry_id}"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert key in hass_storage

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage
