"""Shared flow parts (docs/integration.md 9.1).

Choice lists, suggestions, selectors, translated fragments and the base class of the
room and region subentry flows. Sections are UI only: stored data are flat (§3.2).
"""

import copy
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import probatio
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from ..const import SUBENTRY_REGION
from ..logic import model as m
from ..logic.outdoor import Direction
from ..logic.prefill import (
    OWN_PLATFORM,
    EntityInfo,
    Scope,
    classify,
    suggest_climate_devices,
    suggest_metric_list,
    suggest_sources,
)
from ..logic.sources import Metric
from ..registry import entity_infos
from .preview import (
    DOT_SEPARATOR,
    NotTaken,
    PreviewRun,
    Texts,
    area_name,
    async_run_preview,
    async_texts,
)

# Entity filters of the area selectors: a list means "or" (S2, S6, S7)
AREA_ENTITY_FILTER = [
    {"domain": "sensor", "device_class": "temperature"},
    {"domain": "climate"},
]
OUTDOOR_ENTITY_FILTER = [{"domain": "sensor", "device_class": "temperature"}]

SECTION_HUMIDITY_PRESSURE = "humidity_pressure"
SECTION_CLIMATE = "climate"
SECTION_ADVANCED = "advanced"
_SECTIONS = (SECTION_HUMIDITY_PRESSURE, SECTION_CLIMATE, SECTION_ADVANCED)
MAX_AGE_LIMIT = 1440  # minutes

_METRIC_KEYS = (
    (Metric.HUMIDITY, m.CONF_HUMIDITY),
    (Metric.PRESSURE, m.CONF_PRESSURE),
)


# Choice lists (U6)


def _candidates(
    infos: Sequence[EntityInfo], metric: Metric, scope: Scope
) -> list[EntityInfo]:
    by_device: dict[str, list[EntityInfo]] = defaultdict(list)
    for info in infos:
        if info.device_id is not None:
            by_device[info.device_id].append(info)
    return [
        info
        for info in infos
        if classify(info, by_device.get(info.device_id or "", []), metric, scope)
        is not None
    ]


def _context_filter(
    candidates: Sequence[EntityInfo], area_id: str, chosen: Sequence[str]
) -> list[str]:
    """The area's candidates plus those without an area plus the chosen ones (U6).

    The area filter is lifted when it finds nothing.
    """
    near = [c.entity_id for c in candidates if c.area_id in (area_id, None)]
    found = near or [c.entity_id for c in candidates]
    return sorted({*found, *chosen})


def source_choices(
    infos: Sequence[EntityInfo],
    area_id: str,
    metric: Metric,
    scope: Scope,
    chosen: Sequence[str],
) -> list[str]:
    return _context_filter(_candidates(infos, metric, scope), area_id, chosen)


def climate_choices(
    infos: Sequence[EntityInfo], area_id: str, chosen: Sequence[str]
) -> list[str]:
    climates = [
        i for i in infos if i.domain == "climate" and i.platform != OWN_PLATFORM
    ]
    return _context_filter(climates, area_id, chosen)


# Suggestions (R6)


@dataclass(frozen=True, slots=True)
class Suggested:
    lists: dict[str, list[str]]
    not_taken: tuple[NotTaken, ...]


def suggest(infos: Sequence[EntityInfo], area_id: str, scope: Scope) -> Suggested:
    """Sources (and climate devices of rooms) for an area, with the excluded ones."""
    temperature = suggest_sources(area_id, infos, Metric.TEMPERATURE, scope)
    lists = {m.CONF_TEMPERATURE: list(temperature.sources)}
    for metric, key in _METRIC_KEYS:
        lists[key] = suggest_metric_list(
            temperature.sources, area_id, infos, metric, scope
        )
    if scope is Scope.ROOM:
        lists[m.CONF_CLIMATE_DEVICES] = suggest_climate_devices(area_id, infos)
    values = {i.entity_id: i.value for i in infos}
    return Suggested(
        lists,
        tuple(NotTaken(e, r, values.get(e)) for e, r in temperature.excluded),
    )


def resuggest(
    infos: Sequence[EntityInfo],
    data: Mapping[str, Any],
    area_id: str,
    scope: Scope,
) -> Suggested:
    """New suggestions after an area change; chosen sources without an area stay."""
    suggested = suggest(infos, area_id, scope)
    with_area = {i.entity_id for i in infos if i.area_id is not None}
    lists = {
        key: [
            *new,
            *(e for e in data.get(key, ()) if e not in with_area and e not in new),
        ]
        for key, new in suggested.lists.items()
    }
    return Suggested(lists, suggested.not_taken)


# Selectors and form data


def sources_selector(choices: list[str]) -> EntitySelector:
    return EntitySelector(
        EntitySelectorConfig(multiple=True, reorder=True, include_entities=choices)
    )


def climate_selector(choices: list[str]) -> EntitySelector:
    return EntitySelector(
        EntitySelectorConfig(domain="climate", multiple=True, include_entities=choices)
    )


def max_age_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=1,
            max=MAX_AGE_LIMIT,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=UnitOfTime.MINUTES,
        )
    )


def option_selector(options: list[str], translation_key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            translation_key=translation_key,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def flatten(user_input: Mapping[str, Any], *, climate: bool) -> dict[str, Any]:
    """Form input to the flat stored data (§3.2)."""
    data = {k: v for k, v in user_input.items() if k not in _SECTIONS}
    data[m.CONF_TEMPERATURE] = list(data.get(m.CONF_TEMPERATURE, ()))
    lists = user_input.get(SECTION_HUMIDITY_PRESSURE, {})
    for _, key in _METRIC_KEYS:
        data[key] = list(lists.get(key, ()))
    if climate:
        data[m.CONF_CLIMATE_DEVICES] = list(
            user_input.get(SECTION_CLIMATE, {}).get(m.CONF_CLIMATE_DEVICES, ())
        )
    if (
        max_age := user_input.get(SECTION_ADVANCED, {}).get(m.CONF_MAX_AGE)
    ) is not None:
        data[m.CONF_MAX_AGE] = int(max_age)
    return data


def nest(data: Mapping[str, Any], *, climate: bool) -> dict[str, Any]:
    """Stored data to suggested form values."""
    values: dict[str, Any] = {
        k: v
        for k, v in data.items()
        if k
        not in (
            m.CONF_HUMIDITY,
            m.CONF_PRESSURE,
            m.CONF_CLIMATE_DEVICES,
            m.CONF_MAX_AGE,
        )
    }
    values[SECTION_HUMIDITY_PRESSURE] = {
        key: data[key] for _, key in _METRIC_KEYS if key in data
    }
    if climate:
        values[SECTION_CLIMATE] = {
            m.CONF_CLIMATE_DEVICES: data.get(m.CONF_CLIMATE_DEVICES, [])
        }
    if m.CONF_MAX_AGE in data:
        values[SECTION_ADVANCED] = {m.CONF_MAX_AGE: data[m.CONF_MAX_AGE]}
    return values


# Configured objects


def subentry_by_area(
    entry: ConfigEntry, subentry_type: str, skip: str | None = None
) -> dict[str, ConfigSubentry]:
    return {
        sub.data[m.CONF_AREA]: sub
        for sub in entry.subentries.values()
        if sub.subentry_type == subentry_type and sub.subentry_id != skip
    }


def region_by_direction(
    entry: ConfigEntry, skip: str | None = None
) -> dict[str, ConfigSubentry]:
    return {
        sub.data[m.CONF_DIRECTION]: sub
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_REGION and sub.subentry_id != skip
    }


def sides_line(hass: HomeAssistant, texts: Texts, entry: ConfigEntry) -> str:
    """Which direction has which outdoor side (S6 description)."""
    regions = region_by_direction(entry)
    items = [
        texts(
            "side_item",
            direction=texts.direction(direction),
            area=area_name(hass, regions[direction].data[m.CONF_AREA]),
        )
        if direction in regions
        else texts("side_item_none", direction=texts.direction(direction))
        for direction in (d.value for d in Direction)
    ]
    return texts("sides_line", items=DOT_SEPARATOR.join(items))


class SourceFlow(ConfigSubentryFlow):
    """Base of the room and region flows: form, area change, preview, save.

    Subclasses give the head fields, the validation and the preview text; they define
    the step methods for the form and menu step IDs.
    """

    scope: Scope
    subentry_type: str
    prefix: str  # step ID prefix: `<prefix>_form`, `<prefix>_preview` ...

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._suggested_for = ""
        self._fresh = False  # sources were just suggested
        self._not_taken: tuple[NotTaken, ...] = ()

    # Hooks

    def _head_fields(self) -> dict[Any, Any]:
        """The fields before the temperature sources."""
        raise NotImplementedError

    def _validate(
        self, data: Mapping[str, Any], texts: Texts
    ) -> tuple[str, dict[str, str]] | None:
        """(error key, placeholders) for the area or direction, else None."""
        raise NotImplementedError

    def _title(self, hass: HomeAssistant, texts: Texts) -> str:
        raise NotImplementedError

    def _unique_id(self) -> str:
        raise NotImplementedError

    def _markdown(self, texts: Texts, run: PreviewRun) -> str:
        raise NotImplementedError

    # Shared behaviour

    @property
    def _climate(self) -> bool:
        return self.scope is Scope.ROOM

    @property
    def _own_id(self) -> str | None:
        if self.source != SOURCE_RECONFIGURE:
            return None
        return self._get_reconfigure_subentry().subentry_id

    def _start(self, head: Mapping[str, Any]) -> None:
        """Add: suggestions for the chosen area."""
        area_id = head[m.CONF_AREA]
        suggested = suggest(entity_infos(self.hass), area_id, self.scope)
        self._data = {**head, **suggested.lists}
        self._suggested_for = area_id
        self._not_taken = suggested.not_taken
        self._fresh = True

    def _load(self) -> None:
        """Reconfigure: the stored data."""
        self._data = copy.deepcopy(dict(self._get_reconfigure_subentry().data))
        self._suggested_for = self._data[m.CONF_AREA]
        self._not_taken = ()
        self._fresh = False

    def _schema(self, infos: Sequence[EntityInfo]) -> probatio.Schema:
        area_id, chosen = self._suggested_for, self._data
        fields: dict[Any, Any] = self._head_fields()
        fields[probatio.Required(m.CONF_TEMPERATURE)] = sources_selector(
            source_choices(
                infos,
                area_id,
                Metric.TEMPERATURE,
                self.scope,
                chosen.get(m.CONF_TEMPERATURE, ()),
            )
        )
        fields[probatio.Required(SECTION_HUMIDITY_PRESSURE)] = section(
            probatio.Schema(
                {
                    probatio.Optional(key): sources_selector(
                        source_choices(
                            infos, area_id, metric, self.scope, chosen.get(key, ())
                        )
                    )
                    for metric, key in _METRIC_KEYS
                }
            ),
            {"collapsed": True},
        )
        if self._climate:
            fields[probatio.Required(SECTION_CLIMATE)] = section(
                probatio.Schema(
                    {
                        probatio.Optional(m.CONF_CLIMATE_DEVICES): climate_selector(
                            climate_choices(
                                infos,
                                area_id,
                                chosen.get(m.CONF_CLIMATE_DEVICES, ()),
                            )
                        )
                    }
                ),
                {"collapsed": self.source == SOURCE_RECONFIGURE},
            )
        fields[probatio.Required(SECTION_ADVANCED)] = section(
            probatio.Schema({probatio.Optional(m.CONF_MAX_AGE): max_age_selector()}),
            {"collapsed": True},
        )
        return probatio.Schema(fields)

    async def _async_show_form(
        self,
        step_id: str,
        errors: dict[str, str] | None = None,
        placeholders: Mapping[str, str] | None = None,
    ) -> SubentryFlowResult:
        texts = await async_texts(self.hass)
        entry = self._get_entry()
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                self._schema(entity_infos(self.hass)),
                nest(self._data, climate=self._climate),
            ),
            errors=errors or {},
            description_placeholders={
                "area": area_name(self.hass, self._suggested_for),
                "sides": sides_line(self.hass, texts, entry),
                "suggested": texts(
                    "suggested_hint", area=area_name(self.hass, self._suggested_for)
                )
                + "\n\n"
                if self._fresh
                else "",
                **(placeholders or {}),
            },
        )

    async def _async_form(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        if user_input is None:
            return await self._async_show_form(step_id)
        data = flatten(user_input, climate=self._climate)
        self._data = data
        texts = await async_texts(self.hass)
        if (problem := self._validate(data, texts)) is not None:
            return await self._async_show_form(
                step_id, {"base": problem[0]}, problem[1]
            )
        if (area_id := data[m.CONF_AREA]) != self._suggested_for:
            suggested = resuggest(entity_infos(self.hass), data, area_id, self.scope)
            self._data = {**data, **suggested.lists}
            self._not_taken = suggested.not_taken
            self._suggested_for = area_id
            self._fresh = True
            return await self._async_show_form(f"{self.prefix}_form_changed")
        if not data[m.CONF_TEMPERATURE]:
            return await self._async_show_form(step_id, {"base": "no_temperature"})
        return await self._async_preview()

    async def _async_preview(self) -> SubentryFlowResult:
        texts = await async_texts(self.hass)
        run = await async_run_preview(
            self.hass,
            self._get_entry(),
            self._own_id,
            self.subentry_type,
            self._data,
        )
        return self.async_show_menu(
            step_id=f"{self.prefix}_preview",
            menu_options=[f"{self.prefix}_save", f"{self.prefix}_adjust"],
            description_placeholders={
                "area": area_name(self.hass, self._data[m.CONF_AREA]),
                "preview": self._markdown(texts, run),
            },
        )

    async def _async_save(self) -> SubentryFlowResult:
        title = self._title(self.hass, await async_texts(self.hass))
        unique_id = self._unique_id()
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=title,
                data=self._data,
                unique_id=unique_id,
            )
        return self.async_create_entry(
            title=title, data=self._data, unique_id=unique_id
        )
