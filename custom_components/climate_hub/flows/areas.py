"""Area sync in the flows: the setup preview block, the consent step and the switch
hint of the room and region forms (docs/integration.md 9.1, R11).

Reads the areas live. Nothing here writes to an area.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import SelectOptionDict

from ..area_sync import area_fields, own_entities
from ..const import SUBENTRY_REGION
from ..labels import entity_name
from ..logic import model as m
from ..logic.area_sync import FIELDS, foreign
from ..logic.sources import Metric
from .preview import COMMA_SEPARATOR, HouseRun, PlanItem, Texts, area_name

_BLOCK = "\n\n"
_TEMPERATURE = Metric.TEMPERATURE.value
_HUMIDITY = Metric.HUMIDITY.value


@dataclass(frozen=True, slots=True)
class PlannedArea:
    """The area of a planned room or outdoor side, as the fields hold it now."""

    area_id: str
    is_region: bool
    wanted: tuple[str, ...]  # the fields Climate Hub would write
    foreign: dict[str, str]  # wanted field -> the sensor in it
    ranks: dict[str, int]  # sensor -> rank in the object's temperature or humidity list

    @property
    def sensors(self) -> list[str]:
        """The foreign sensors, each once, in field order."""
        return list(dict.fromkeys(self.foreign.values()))


def _ranks(
    sources: Mapping[Metric, Sequence[str]], sensors: Iterable[str | None]
) -> dict[str, int]:
    """The 1-based place of each sensor in the temperature, else the humidity list."""
    ranks: dict[str, int] = {}
    for sensor in sensors:
        for metric in (Metric.TEMPERATURE, Metric.HUMIDITY):
            if sensor is not None and sensor in sources[metric]:
                ranks[sensor] = sources[metric].index(sensor) + 1
                break
    return ranks


def planned_areas(
    hass: HomeAssistant, run: HouseRun, items: Iterable[PlanItem]
) -> list[PlannedArea]:
    """Per area of the planned rooms and sides (rooms first, so a side wins a shared
    area, integration.md §11 point 1). At first setup no Climate Hub entity exists, so
    every filled field counts as foreign."""
    found: dict[str, PlannedArea] = {}
    for item in items:
        subject = run.model.rooms.get(item.subentry_id) or run.model.regions.get(
            item.subentry_id
        )
        current = area_fields(hass, item.area_id)
        if subject is None or not current:
            continue
        wanted = tuple(
            f for f in FIELDS if f == _TEMPERATURE or subject.sources[Metric(f)]
        )
        others = {f: foreign(current[f], None) for f in wanted}
        found[item.area_id] = PlannedArea(
            item.area_id,
            item.subentry_type == SUBENTRY_REGION,
            wanted,
            {f: s for f, s in others.items() if s is not None},
            _ranks(subject.sources, others.values()),
        )
    return list(found.values())


def consent_options(
    hass: HomeAssistant, areas: Iterable[PlannedArea]
) -> list[SelectOptionDict]:
    """S4a: an option per area with a foreign sensor, "{area}: {sensor}[, {sensor}]"."""
    return [
        SelectOptionDict(
            value=area.area_id,
            label=f"{area_name(hass, area.area_id)}: "
            + COMMA_SEPARATOR.join(entity_name(hass, s) for s in area.sensors),
        )
        for area in areas
        if area.foreign
    ]


def _sensor(
    hass: HomeAssistant, texts: Texts, area: PlannedArea, entity_id: str
) -> str:
    name = entity_name(hass, entity_id)
    if (rank := area.ranks.get(entity_id)) is None:
        return name
    key = "plan_areas_source_side" if area.is_region else "plan_areas_source_room"
    return texts(key, sensor=name, rank=rank)


def _foreign_line(hass: HomeAssistant, texts: Texts, area: PlannedArea) -> str:
    sensors = texts.join_and(_sensor(hass, texts, area, s) for s in area.sensors)
    parts = [
        texts(
            "plan_areas_foreign", area=area_name(hass, area.area_id), sensors=sensors
        ),
        texts("plan_areas_kept"),
    ]
    parts.extend(
        texts(f"plan_areas_fill_{field}")
        for field in area.wanted
        if field not in area.foreign
    )
    return " ".join(parts)


def _replace_line(hass: HomeAssistant, texts: Texts, area: PlannedArea) -> str:
    key = (
        "plan_areas_replace_one"
        if len(area.sensors) == 1
        else "plan_areas_replace_many"
    )
    return texts(
        key,
        area=area_name(hass, area.area_id),
        sensors=texts.join_and(entity_name(hass, s) for s in area.sensors),
    )


def areas_markdown(
    hass: HomeAssistant,
    texts: Texts,
    areas: Sequence[PlannedArea],
    replace: Collection[str],
    *,
    sync: bool,
) -> str:
    """The areas part of screen S4; the one line "nothing" while the sync is off."""
    head = texts("plan_areas_head")
    if not sync or not areas:
        return _BLOCK.join([head, "- " + texts("plan_areas_off")])
    lines = []
    for key, fields in (
        ("plan_areas_empty", (_TEMPERATURE, _HUMIDITY)),
        ("plan_areas_empty_temperature", (_TEMPERATURE,)),
    ):
        names = [
            area_name(hass, a.area_id)
            for a in areas
            if not a.foreign and a.wanted == fields
        ]
        if names:
            lines.append("- " + texts(key, areas=COMMA_SEPARATOR.join(names)))
    lines.extend(
        "- "
        + (
            _replace_line(hass, texts, a)
            if a.area_id in replace
            else _foreign_line(hass, texts, a)
        )
        for a in areas
        if a.foreign
    )
    return _BLOCK.join([head, "\n".join(lines)])


# The switch of the room and region forms (S6, S7)


def replace_hint(
    hass: HomeAssistant,
    texts: Texts,
    entry: ConfigEntry,
    area_id: str,
    subject_id: str | None,
    data: dict[str, Any],
) -> str | None:
    """The text above the switch "replace area sensor", None while it is not shown.

    Shown while the hub option `area_sync` is on (absent counts as on) and the area
    holds a sensor that is not this object's own (a new object has none), or Climate
    Hub replaced a sensor there (a record with `previous`).
    """
    if not entry.options.get(m.CONF_AREA_SYNC, True):
        return None
    current = area_fields(hass, area_id)
    if not current:
        return None
    own = own_entities(hass, subject_id) if subject_id else {}
    wanted = (
        FIELDS if _HUMIDITY in own or data.get(m.CONF_HUMIDITY) else (_TEMPERATURE,)
    )
    others = [s for f in wanted if (s := foreign(current[f], own.get(f))) is not None]
    replaced: list[str] = []
    if entry.state is ConfigEntryState.LOADED:
        records = entry.runtime_data.coordinator.area_sync.get(area_id, {})
        replaced = [  # only while the field still holds what Climate Hub wrote
            r.previous
            for f, r in records.items()
            if r.previous is not None and current.get(f) == r.entity_id
        ]
    if replaced:
        sensors = list(dict.fromkeys(replaced))
        key = "area_replace_done" if len(sensors) == 1 else "area_replace_done_many"
    elif others:
        sensors = list(dict.fromkeys(others))
        key = (
            "area_replace_foreign" if len(sensors) == 1 else "area_replace_foreign_many"
        )
    else:
        return None
    return texts(
        key,
        area=area_name(hass, area_id),
        sensors=texts.join_and(entity_name(hass, s) for s in sensors),
    )
