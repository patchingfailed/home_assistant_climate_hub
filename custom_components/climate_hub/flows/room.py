"""Room subentry flow (docs/integration.md 9.3, screen S6)."""

from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.config_entries import SubentryFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import AreaSelector, AreaSelectorConfig

from ..const import SUBENTRY_REGION, SUBENTRY_ROOM
from ..logic import model as m
from ..logic.outdoor import Direction
from ..logic.prefill import Scope
from .common import (
    AREA_ENTITY_FILTER,
    SourceFlow,
    option_selector,
    subentry_by_area,
)
from .preview import PreviewRun, Texts, area_name, async_texts, room_markdown

SIDES = [*(d.value for d in Direction), m.SIDE_NONE]


class RoomSubentryFlow(SourceFlow):
    """Area (add only), form, preview menu, save."""

    scope = Scope.ROOM
    subentry_type = SUBENTRY_ROOM
    prefix = "room"

    def _area_selector(self) -> AreaSelector:
        return AreaSelector(AreaSelectorConfig(entity=AREA_ENTITY_FILTER))

    def _head_fields(self) -> dict[Any, Any]:
        return {
            probatio.Required(m.CONF_AREA): self._area_selector(),
            probatio.Required(m.CONF_SIDE): option_selector(SIDES, "side"),
        }

    def _validate(
        self, data: Mapping[str, Any], texts: Texts
    ) -> tuple[str, dict[str, str]] | None:
        entry = self._get_entry()
        area_id = data[m.CONF_AREA]
        placeholders = {"area": area_name(self.hass, area_id)}
        if area_id in subentry_by_area(entry, SUBENTRY_ROOM, self._own_id):
            return "already_room", placeholders
        if area_id in subentry_by_area(entry, SUBENTRY_REGION):
            return "is_region", placeholders
        return None

    def _title(self, hass: HomeAssistant, texts: Texts) -> str:
        return area_name(hass, self._data[m.CONF_AREA])

    def _unique_id(self) -> str:
        return f"room_{self._data[m.CONF_AREA]}"

    def _markdown(self, texts: Texts, run: PreviewRun) -> str:
        return room_markdown(self.hass, texts, run, self._data, self._not_taken)

    # Steps

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add, step 1: the area."""
        errors: dict[str, str] = {}
        placeholders = {"area": ""}
        if user_input is not None:
            data = {m.CONF_AREA: user_input[m.CONF_AREA]}
            if (problem := self._validate(data, await async_texts(self.hass))) is None:
                self._start({**data, m.CONF_SIDE: m.SIDE_NONE})
                return await self._async_form("room_form", None)
            errors["base"], placeholders = problem
        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {probatio.Required(m.CONF_AREA): self._area_selector()}
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit: the form directly, with the stored data."""
        self._load()
        return await self._async_form("room_form", None)

    async def async_step_room_form(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_form("room_form", user_input)

    async def async_step_room_form_changed(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """The same form after an area change; its description carries the hint."""
        return await self._async_form("room_form_changed", user_input)

    async def async_step_room_preview(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_preview()

    async def async_step_room_adjust(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_show_form("room_form")

    async def async_step_room_save(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_save()
