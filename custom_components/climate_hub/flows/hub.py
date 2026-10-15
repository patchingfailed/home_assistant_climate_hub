"""Hub-level flow parts: first setup scan and house plan (docs/integration.md 9.2, 9.6).

Shared by the config flow (S1-S4, S10) and the options flow. Everything here reads
Home Assistant but holds no flow state.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import probatio
from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigSubentry,
    ConfigSubentryData,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import translation
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from ..const import DOMAIN, SUBENTRY_REGION, SUBENTRY_ROOM
from ..logic import const as logic_const
from ..logic import model as m
from ..logic.outdoor import Direction
from ..logic.prefill import (
    CONTACT_CLASSES,
    AreaInfo,
    EntityInfo,
    Scope,
    propose_rooms,
    suggest_sources,
)
from ..logic.sources import Metric
from ..registry import area_infos
from .common import (
    is_text_sensor,
    region_by_direction,
    region_title,
    region_unique_id,
    resuggest,
    room_unique_id,
    subentry_by_area,
    suggest,
)
from .preview import DOT_SEPARATOR, PlanItem, Texts, area_name

CONF_ROOMS = "rooms"
CONF_OUTDOOR = "outdoor"
SECTION_TIMING = "timing"
DIRECTIONS = tuple(d.value for d in Direction)

type Plan = dict[
    str, dict[str, Any]
]  # direction -> {outdoor: area | None, rooms: [area]}

# Defaults of the hub options that are not logic defaults of their own
DEFAULT_TIMING: dict[str, Any] = {
    m.CONF_MAX_AGE: int(logic_const.DEFAULT_MAX_AGE.total_seconds() // 60),
    m.CONF_BURST_DURATION: int(
        logic_const.DEFAULT_BURST_DURATION.total_seconds() // 60
    ),
    m.CONF_HUMIDITY_THRESHOLD: logic_const.DEFAULT_HUMIDITY_THRESHOLD,
    m.CONF_REPAIR_DELAY: int(logic_const.DEFAULT_REPAIR_DELAY.total_seconds() // 3600),
}
_FORECAST_FEATURES = (
    WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY
)


# Options


def default_options(weather: str | None, area_sync: bool) -> dict[str, Any]:
    """All option keys; the weather entity is absent when there is none (§3.1)."""
    options: dict[str, Any] = {m.CONF_AREA_SYNC: area_sync, **DEFAULT_TIMING}
    if weather:
        options[m.CONF_WEATHER] = weather
    return options


def default_weather(hass: HomeAssistant) -> str | None:
    """The first weather entity that can deliver a forecast."""
    for entity_id in sorted(hass.states.async_entity_ids("weather")):
        state = hass.states.get(entity_id)
        if state is not None and (
            state.attributes.get("supported_features", 0) & _FORECAST_FEATURES
        ):
            return entity_id
    return None


# Scan (S1, S2)


async def async_outside_words(hass: HomeAssistant) -> list[str]:
    """Outside words of the instance language and English (I16)."""
    words: list[str] = []
    for language in dict.fromkeys((hass.config.language, "en")):
        strings = await translation.async_get_translations(
            hass, language, "common", {DOMAIN}
        )
        raw = strings.get(f"component.{DOMAIN}.common.outside_words", "")
        words.extend(word.strip() for word in raw.split(",") if word.strip())
    return list(dict.fromkeys(words))


def count_contacts(hass: HomeAssistant, infos: Sequence[EntityInfo]) -> int:
    """Window and door contacts: binary sensors of the contact classes, text sensors."""
    return sum(
        1
        for info in infos
        if info.category is None
        and (
            (info.domain == "binary_sensor" and info.device_class in CONTACT_CLASSES)
            or is_text_sensor(hass, info)
        )
    )


@dataclass(frozen=True, slots=True)
class Scan:
    rooms: int  # proposed and pre-checked
    outdoor: int  # proposed but not pre-checked: may be outside
    contacts: int
    weather: int


async def async_scan(hass: HomeAssistant, infos: Sequence[EntityInfo]) -> Scan:
    proposal = propose_rooms(area_infos(hass), infos, await async_outside_words(hass))
    return Scan(
        rooms=sum(1 for _, checked in proposal if checked),
        outdoor=sum(1 for _, checked in proposal if not checked),
        contacts=count_contacts(hass, infos),
        weather=len(hass.states.async_entity_ids("weather")),
    )


async def async_room_proposal(
    hass: HomeAssistant, infos: Sequence[EntityInfo]
) -> tuple[tuple[str, bool], ...]:
    return propose_rooms(area_infos(hass), infos, await async_outside_words(hass))


def room_options(
    hass: HomeAssistant, texts: Texts, proposal: Sequence[tuple[str, bool]]
) -> list[SelectOptionDict]:
    """Labels "{floor} · {area}" (S2)."""
    areas = {a.area_id: a for a in area_infos(hass)}
    return [
        SelectOptionDict(
            value=area_id,
            label=(areas[area_id].floor_name or texts("no_floor"))
            + DOT_SEPARATOR
            + areas[area_id].name,
        )
        for area_id, _ in proposal
    ]


# House plan (S3, S10)


def empty_plan() -> Plan:
    return {d: {CONF_OUTDOOR: None, CONF_ROOMS: []} for d in DIRECTIONS}


def plan_values(plan: Plan) -> dict[str, dict[str, Any]]:
    """Plan to suggested form values (an empty outdoor area is left out)."""
    return {
        d: {
            CONF_ROOMS: list(side[CONF_ROOMS]),
            **({CONF_OUTDOOR: side[CONF_OUTDOOR]} if side[CONF_OUTDOOR] else {}),
        }
        for d, side in plan.items()
    }


def plan_from_input(user_input: dict[str, Any]) -> Plan:
    plan = empty_plan()
    for direction in DIRECTIONS:
        side = user_input.get(direction) or {}
        plan[direction] = {
            CONF_OUTDOOR: side.get(CONF_OUTDOOR) or None,
            CONF_ROOMS: list(side.get(CONF_ROOMS) or []),
        }
    return plan


def plan_from_entry(entry: ConfigEntry) -> tuple[list[str], Plan]:
    """Rooms and the plan, read from the room and region subentries."""
    rooms: list[str] = []
    plan = empty_plan()
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_ROOM:
            rooms.append(sub.data[m.CONF_AREA])
            if (side := sub.data.get(m.CONF_SIDE)) in plan:
                plan[side][CONF_ROOMS].append(sub.data[m.CONF_AREA])
        elif sub.subentry_type == SUBENTRY_REGION:
            plan[sub.data[m.CONF_DIRECTION]][CONF_OUTDOOR] = sub.data[m.CONF_AREA]
    return rooms, plan


def outdoor_candidates(
    infos: Sequence[EntityInfo],
    areas: Sequence[AreaInfo],
    rooms: Collection[str],
    keep: Collection[str],
) -> list[str]:
    """Areas that could be an outdoor side: not a room, a temperature source to take."""
    return [
        area.area_id
        for area in sorted(areas, key=lambda a: a.name.casefold())
        if area.area_id not in rooms
        and (
            area.area_id in keep
            or suggest_sources(
                area.area_id, infos, Metric.TEMPERATURE, Scope.REGION
            ).sources
        )
    ]


def area_options(
    hass: HomeAssistant, area_ids: Sequence[str]
) -> list[SelectOptionDict]:
    return [
        SelectOptionDict(value=area_id, label=area_name(hass, area_id))
        for area_id in area_ids
    ]


def plan_schema(
    rooms: list[SelectOptionDict], outdoor: list[SelectOptionDict]
) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(direction): section(
                probatio.Schema(
                    {
                        probatio.Optional(CONF_OUTDOOR): SelectSelector(
                            SelectSelectorConfig(
                                options=outdoor, mode=SelectSelectorMode.DROPDOWN
                            )
                        ),
                        probatio.Optional(CONF_ROOMS): SelectSelector(
                            SelectSelectorConfig(
                                options=rooms,
                                multiple=True,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    }
                ),
                {"collapsed": False},
            )
            for direction in DIRECTIONS
        }
    )


def validate_plan(
    hass: HomeAssistant, texts: Texts, plan: Plan
) -> tuple[str, dict[str, str]] | None:
    """(error key, placeholders) for the plan, else None (S3)."""
    seen: set[str] = set()
    for direction in DIRECTIONS:
        for room in plan[direction][CONF_ROOMS]:
            if room in seen:
                return "room_two_sides", {"area": area_name(hass, room), "side": ""}
            seen.add(room)
    sides: dict[str, str] = {}
    for direction in DIRECTIONS:
        if (area_id := plan[direction][CONF_OUTDOOR]) is None:
            continue
        if area_id in sides:
            return "outdoor_twice", {
                "area": area_name(hass, area_id),
                "side": texts.direction(sides[area_id]),
            }
        sides[area_id] = direction
    return None


def _item(
    infos: Sequence[EntityInfo],
    subentry_type: str,
    subentry_id: str,
    head: dict[str, Any],
    scope: Scope,
) -> PlanItem:
    suggested = suggest(infos, head[m.CONF_AREA], scope)
    return PlanItem(
        subentry_id,
        subentry_type,
        head[m.CONF_AREA],
        {**head, **suggested.lists},
        suggested.not_taken,
    )


def build_items(
    infos: Sequence[EntityInfo], rooms: Sequence[str], plan: Plan
) -> tuple[list[PlanItem], list[PlanItem]]:
    """Rooms and outdoor sides with suggested sources (first setup)."""
    side_of = {room: d for d in DIRECTIONS for room in plan[d][CONF_ROOMS]}
    room_items = [
        _item(
            infos,
            SUBENTRY_ROOM,
            room_unique_id(area_id),
            {m.CONF_AREA: area_id, m.CONF_SIDE: side_of.get(area_id, m.SIDE_NONE)},
            Scope.ROOM,
        )
        for area_id in rooms
    ]
    region_items = [
        _item(
            infos,
            SUBENTRY_REGION,
            region_unique_id(d),
            {m.CONF_AREA: area_id, m.CONF_DIRECTION: d},
            Scope.REGION,
        )
        for d in DIRECTIONS
        if (area_id := plan[d][CONF_OUTDOOR])
    ]
    return room_items, region_items


def subentry_data(
    hass: HomeAssistant, texts: Texts, item: PlanItem
) -> ConfigSubentryData:
    if item.subentry_type == SUBENTRY_ROOM:
        title, unique_id = area_name(hass, item.area_id), room_unique_id(item.area_id)
    else:
        direction = item.data[m.CONF_DIRECTION]
        title = region_title(hass, texts, direction, item.area_id)
        unique_id = region_unique_id(direction)
    return ConfigSubentryData(
        data=dict(item.data),
        subentry_type=item.subentry_type,
        title=title,
        unique_id=unique_id,
    )


# Reconfigure (S10)


@dataclass(frozen=True, slots=True)
class PlanChange:
    """What saving the house plan does to the subentries."""

    room_sides: tuple[tuple[ConfigSubentry, str], ...]  # room, new side
    removed: tuple[ConfigSubentry, ...]  # regions
    changed: tuple[tuple[ConfigSubentry, PlanItem], ...]  # regions with a new area
    added: tuple[PlanItem, ...]  # new regions

    @property
    def regions(self) -> list[PlanItem]:
        """The sides whose sources are suggested anew (I17)."""
        return [*(item for _, item in self.changed), *self.added]


def plan_changes(
    entry: ConfigEntry, infos: Sequence[EntityInfo], plan: Plan
) -> PlanChange:
    side_of = {room: d for d in DIRECTIONS for room in plan[d][CONF_ROOMS]}
    room_sides = tuple(
        (sub, side_of.get(area_id, m.SIDE_NONE))
        for area_id, sub in subentry_by_area(entry, SUBENTRY_ROOM).items()
        if sub.data.get(m.CONF_SIDE) != side_of.get(area_id, m.SIDE_NONE)
    )
    existing = region_by_direction(entry)
    removed: list[ConfigSubentry] = []
    changed: list[tuple[ConfigSubentry, PlanItem]] = []
    added: list[PlanItem] = []
    for direction in DIRECTIONS:
        area_id = plan[direction][CONF_OUTDOOR]
        sub = existing.get(direction)
        if area_id is None:
            if sub is not None:
                removed.append(sub)
        elif sub is None:
            added.append(
                _item(
                    infos,
                    SUBENTRY_REGION,
                    region_unique_id(direction),
                    {m.CONF_AREA: area_id, m.CONF_DIRECTION: direction},
                    Scope.REGION,
                )
            )
        elif sub.data[m.CONF_AREA] != area_id:
            suggested = resuggest(infos, sub.data, area_id, Scope.REGION)
            changed.append(
                (
                    sub,
                    PlanItem(
                        sub.subentry_id,
                        SUBENTRY_REGION,
                        area_id,
                        {**sub.data, m.CONF_AREA: area_id, **suggested.lists},
                        suggested.not_taken,
                    ),
                )
            )
    return PlanChange(room_sides, tuple(removed), tuple(changed), tuple(added))


def final_items(entry: ConfigEntry, change: PlanChange) -> list[PlanItem]:
    """All rooms and sides as they would be after saving, for the preview run."""
    new_side = {sub.subentry_id: side for sub, side in change.room_sides}
    gone = {sub.subentry_id for sub in change.removed}
    replaced = {sub.subentry_id: item for sub, item in change.changed}
    items: list[PlanItem] = []
    for sub in entry.subentries.values():
        if sub.subentry_id in gone:
            continue
        if sub.subentry_id in replaced:
            items.append(replaced[sub.subentry_id])
            continue
        data = (
            {**sub.data, m.CONF_SIDE: new_side[sub.subentry_id]}
            if sub.subentry_id in new_side
            else sub.data
        )
        items.append(
            PlanItem(
                sub.subentry_id, sub.subentry_type, sub.data[m.CONF_AREA], data, ()
            )
        )
    items.extend(change.added)
    return items


def new_subentry(hass: HomeAssistant, texts: Texts, item: PlanItem) -> ConfigSubentry:
    created = subentry_data(hass, texts, item)
    return ConfigSubentry(
        data=MappingProxyType(created["data"]),
        subentry_type=created["subentry_type"],
        title=created["title"],
        unique_id=created["unique_id"],
    )
