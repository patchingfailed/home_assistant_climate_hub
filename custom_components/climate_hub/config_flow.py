"""Config flow of the hub (docs/integration.md 9.2, 9.6).

First setup: S1 start, S2 rooms, S3 house plan, S4 preview, create. Reconfigure: S10
house plan with the preview of new or changed outdoor sides (I17). The options flow
(S9) is in `flows/options.py`, the room and region flows are the subentry flows.
"""

from typing import Any

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import DOMAIN, SUBENTRY_REGION, SUBENTRY_ROOM, SUBENTRY_WINDOW
from .flows.hub import (
    CONF_OUTDOOR,
    CONF_ROOMS,
    Plan,
    PlanChange,
    area_options,
    async_room_proposal,
    async_scan,
    build_items,
    default_options,
    default_weather,
    empty_plan,
    final_items,
    new_subentry,
    outdoor_candidates,
    plan_changes,
    plan_from_entry,
    plan_from_input,
    plan_schema,
    plan_values,
    region_title,
    room_options,
    subentry_data,
    validate_plan,
)
from .flows.options import ClimateHubOptionsFlow
from .flows.preview import (
    async_run_house,
    async_texts,
    plan_markdown,
    regions_markdown,
)
from .flows.region import RegionSubentryFlow
from .flows.room import RoomSubentryFlow
from .flows.window import WindowSubentryFlow
from .logic import model as m
from .registry import area_infos, entity_infos

ENTRY_TITLE = "Climate Hub"
CREATED = "created"


class ClimateHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """First setup and the house plan reconfigure of the single hub entry."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._weather: str | None = None
        self._area_sync = True
        self._rooms: list[str] | None = None  # area IDs
        self._plan: Plan = empty_plan()
        self._change: PlanChange | None = None

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Order of the add items in the ⋮ menu."""
        return {
            SUBENTRY_ROOM: RoomSubentryFlow,
            SUBENTRY_REGION: RegionSubentryFlow,
            SUBENTRY_WINDOW: WindowSubentryFlow,
        }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ClimateHubOptionsFlow:
        return ClimateHubOptionsFlow()

    # S1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._weather = user_input.get(m.CONF_WEATHER)
            self._area_sync = user_input[m.CONF_AREA_SYNC]
            return await self.async_step_rooms()
        scan = await async_scan(self.hass, entity_infos(self.hass))
        suggested = default_weather(self.hass)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Optional(m.CONF_WEATHER): EntitySelector(
                            EntitySelectorConfig(domain="weather")
                        ),
                        probatio.Required(m.CONF_AREA_SYNC, default=True): (
                            BooleanSelector()
                        ),
                    }
                ),
                {m.CONF_WEATHER: suggested} if suggested else {},
            ),
            description_placeholders={
                "rooms": str(scan.rooms),
                "outdoor": str(scan.outdoor),
                "contacts": str(scan.contacts),
                "weather": str(scan.weather),
            },
        )

    # S2

    async def async_step_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        proposal = await async_room_proposal(self.hass, entity_infos(self.hass))
        errors: dict[str, str] = {}
        if user_input is not None:
            if chosen := user_input.get(CONF_ROOMS):
                self._rooms = [area_id for area_id, _ in proposal if area_id in chosen]
                self._drop_stale_plan_entries()
                return await self.async_step_plan()
            errors["base"] = "no_rooms"
        current = (
            []
            if user_input is not None
            else self._rooms
            if self._rooms is not None
            else [area_id for area_id, checked in proposal if checked]
        )
        texts = await async_texts(self.hass)
        return self.async_show_form(
            step_id="rooms",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Optional(CONF_ROOMS): SelectSelector(
                            SelectSelectorConfig(
                                options=room_options(self.hass, texts, proposal),
                                multiple=True,
                                mode=SelectSelectorMode.LIST,
                            )
                        )
                    }
                ),
                {CONF_ROOMS: current},
            ),
            errors=errors,
        )

    def _drop_stale_plan_entries(self) -> None:
        """Rooms that are no longer rooms leave the plan; so do new rooms as outdoor."""
        rooms = set(self._rooms or ())
        for side in self._plan.values():
            side[CONF_ROOMS] = [r for r in side[CONF_ROOMS] if r in rooms]
            if side[CONF_OUTDOOR] in rooms:
                side[CONF_OUTDOOR] = None

    # S3 and S10 share the form

    async def _async_read_plan(
        self, user_input: dict[str, Any] | None
    ) -> tuple[dict[str, str], dict[str, str]] | None:
        """Take the answers over; the errors and placeholders when they are invalid."""
        if user_input is None:
            return None
        self._plan = plan_from_input(user_input)
        problem = validate_plan(self.hass, await async_texts(self.hass), self._plan)
        if problem is None:
            return None
        return {"base": problem[0]}, problem[1]

    def _plan_form(
        self,
        step_id: str,
        rooms: list[str],
        keep: set[str],
        problem: tuple[dict[str, str], dict[str, str]] | None = None,
    ) -> ConfigFlowResult:
        outdoor = outdoor_candidates(
            entity_infos(self.hass),
            area_infos(self.hass),
            rooms,
            keep | {s["outdoor"] for s in self._plan.values() if s["outdoor"]},
        )
        errors, placeholders = problem or ({}, {"area": "", "side": ""})
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                plan_schema(
                    area_options(self.hass, rooms), area_options(self.hass, outdoor)
                ),
                plan_values(self._plan),
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    # S3

    async def async_step_plan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        problem = await self._async_read_plan(user_input)
        if user_input is not None and problem is None:
            return await self.async_step_preview()
        return self._plan_form("plan", self._rooms or [], set(), problem)

    # S4

    def _options(self) -> dict[str, Any]:
        return default_options(self._weather, self._area_sync)

    async def async_step_preview(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        rooms, regions = build_items(
            entity_infos(self.hass), self._rooms or [], self._plan
        )
        run = await async_run_house(
            self.hass, None, self._options(), [*rooms, *regions]
        )
        texts = await async_texts(self.hass)
        return self.async_show_menu(
            step_id="preview",
            menu_options=["create", "rooms", "plan"],
            description_placeholders={
                "preview": plan_markdown(self.hass, texts, run, rooms, regions)
            },
        )

    async def async_step_create(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        texts = await async_texts(self.hass)
        rooms, regions = build_items(
            entity_infos(self.hass), self._rooms or [], self._plan
        )
        return self.async_create_entry(
            title=ENTRY_TITLE,
            data={},
            options=self._options(),
            subentries=[subentry_data(self.hass, texts, i) for i in (*rooms, *regions)],
            description=CREATED,
        )

    # S10

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        if self._rooms is None:
            self._rooms, self._plan = plan_from_entry(entry)
        problem = await self._async_read_plan(user_input)
        if user_input is None or problem is not None:
            return self._plan_form(
                "reconfigure", self._rooms, self._configured_outdoor(entry), problem
            )
        self._change = plan_changes(entry, entity_infos(self.hass), self._plan)
        if self._change.regions:
            return await self.async_step_plan_preview()
        return await self._async_apply()

    @staticmethod
    def _configured_outdoor(entry: ConfigEntry) -> set[str]:
        return {
            sub.data[m.CONF_AREA]
            for sub in entry.subentries.values()
            if sub.subentry_type == SUBENTRY_REGION
        }

    async def async_step_plan_preview(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The suggested sources of new or changed sides before saving (I17)."""
        entry = self._get_reconfigure_entry()
        assert self._change is not None
        run = await async_run_house(
            self.hass, entry, entry.options, final_items(entry, self._change)
        )
        texts = await async_texts(self.hass)
        return self.async_show_menu(
            step_id="plan_preview",
            menu_options=["plan_save", "plan_adjust"],
            description_placeholders={
                "preview": regions_markdown(
                    self.hass, texts, run, self._change.regions, missing_sides=False
                )
            },
        )

    async def async_step_plan_adjust(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        return self._plan_form(
            "reconfigure", self._rooms or [], self._configured_outdoor(entry)
        )

    async def async_step_plan_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_apply()

    async def _async_apply(self) -> ConfigFlowResult:
        """Update the subentries; the update listener coalesces them into one reload."""
        entry = self._get_reconfigure_entry()
        change = self._change or plan_changes(
            entry, entity_infos(self.hass), self._plan
        )
        texts = await async_texts(self.hass)
        manager = self.hass.config_entries
        for sub in change.removed:
            manager.async_remove_subentry(entry, sub.subentry_id)
        for sub, side in change.room_sides:
            manager.async_update_subentry(
                entry, sub, data={**sub.data, m.CONF_SIDE: side}
            )
        for sub, item in change.changed:
            manager.async_update_subentry(
                entry,
                sub,
                data=dict(item.data),
                title=region_title(
                    self.hass, texts, item.data[m.CONF_DIRECTION], item.area_id
                ),
            )
        for item in change.added:
            manager.async_add_subentry(entry, new_subentry(self.hass, texts, item))
        return self.async_abort(reason="reconfigure_successful")
