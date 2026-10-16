"""Outdoor side (region) subentry flow (docs/integration.md 9.4, screen S7)."""

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
    OUTDOOR_ENTITY_FILTER,
    SourceFlow,
    option_selector,
    region_by_direction,
    region_title,
    region_unique_id,
    subentry_by_area,
)
from .preview import PreviewRun, Texts, area_name, async_texts, region_markdown


class RegionSubentryFlow(SourceFlow):
    """Direction and area (add only), form, preview menu, save."""

    scope = Scope.REGION
    subentry_type = SUBENTRY_REGION
    prefix = "region"

    def _free_directions(self) -> list[str]:
        """Directions without a region; when editing, plus the region's own."""
        taken = region_by_direction(self._get_entry(), self._own_id)
        return [d.value for d in Direction if d.value not in taken]

    def _area_selector(self) -> AreaSelector:
        return AreaSelector(AreaSelectorConfig(entity=OUTDOOR_ENTITY_FILTER))

    def _head_fields(self) -> dict[Any, Any]:
        return {
            probatio.Required(m.CONF_DIRECTION): option_selector(
                self._free_directions(), "direction"
            ),
            probatio.Required(m.CONF_AREA): self._area_selector(),
        }

    def _validate(
        self, data: Mapping[str, Any], texts: Texts
    ) -> tuple[str, dict[str, str]] | None:
        entry = self._get_entry()
        area_id, direction = data[m.CONF_AREA], data[m.CONF_DIRECTION]
        name = area_name(self.hass, area_id)
        taken = region_by_direction(entry, self._own_id)
        if direction in taken:
            return "direction_taken", {
                "direction": texts.direction(direction),
                "area": area_name(self.hass, taken[direction].data[m.CONF_AREA]),
            }
        if sub := subentry_by_area(entry, SUBENTRY_REGION, self._own_id).get(area_id):
            return "already_region", {
                "area": name,
                "direction": texts.direction(sub.data[m.CONF_DIRECTION]),
            }
        if area_id in subentry_by_area(entry, SUBENTRY_ROOM):
            return "is_room", {"area": name}
        return None

    def _title(self, hass: HomeAssistant, texts: Texts) -> str:
        return region_title(
            hass, texts, self._data[m.CONF_DIRECTION], self._data[m.CONF_AREA]
        )

    def _unique_id(self) -> str:
        return region_unique_id(self._data[m.CONF_DIRECTION])

    def _markdown(self, texts: Texts, run: PreviewRun) -> str:
        return region_markdown(self.hass, texts, run, self._data)

    async def _async_show_form(
        self,
        step_id: str,
        errors: dict[str, str] | None = None,
        placeholders: Mapping[str, str] | None = None,
    ) -> SubentryFlowResult:
        """The form title names the direction."""
        texts = await async_texts(self.hass)
        direction = texts.direction(self._data[m.CONF_DIRECTION])
        return await super()._async_show_form(
            step_id, errors, {"direction": direction, **(placeholders or {})}
        )

    # Steps

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add, step 1: direction (free ones) and outdoor area."""
        errors: dict[str, str] = {}
        placeholders = {"area": "", "direction": ""}
        if user_input is not None:
            head = {
                m.CONF_DIRECTION: user_input[m.CONF_DIRECTION],
                m.CONF_AREA: user_input[m.CONF_AREA],
            }
            if (problem := self._validate(head, await async_texts(self.hass))) is None:
                self._start(head)
                return await self._async_form("region_form", None)
            errors["base"], placeholders = problem
        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(self._head_fields()),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit: the form directly, with the stored data."""
        self._load()
        return await self._async_form("region_form", None)

    async def async_step_region_form(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_form("region_form", user_input)

    async def async_step_region_form_changed(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """The same form after an area change; its description carries the hint."""
        return await self._async_form("region_form_changed", user_input)

    async def async_step_region_preview(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_preview()

    async def async_step_region_adjust(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_show_form("region_form")

    async def async_step_region_save(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_save()
