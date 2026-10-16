"""Source pre-fill, follow and room proposal (docs/logic.md §11)."""

from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from .const import (
    HUMIDITY_RANGE,
    PRESSURE_RANGE,
    REGION_TEMPERATURE_RANGE,
    ROOM_TEMPERATURE_RANGE,
)
from .sources import Metric

OWN_PLATFORM = "climate_hub"
HELPER_PLATFORMS = frozenset(
    {
        "template",
        "min_max",
        "statistics",
        "filter",
        "derivative",
        "integration",
        "trend",
        "threshold",
        "compensation",
        "group",
        "thermal_comfort",
    }
)
ACTUATOR_DOMAINS = frozenset(
    {
        "light",
        "switch",
        "cover",
        "climate",
        "fan",
        "media_player",
        "lock",
        "vacuum",
        "humidifier",
        "water_heater",
        "valve",
        "siren",
    }
)
CONTACT_CLASSES = frozenset({"window", "door", "opening", "garage_door"})
MOTION_CLASSES = frozenset({"motion", "occupancy", "presence"})
_METRIC_CLASSES = {
    Metric.TEMPERATURE: frozenset({"temperature"}),
    Metric.HUMIDITY: frozenset({"humidity"}),
    Metric.PRESSURE: frozenset({"atmospheric_pressure", "pressure"}),
}


class Scope(StrEnum):
    ROOM = "room"
    REGION = "region"


class Tier(IntEnum):
    CLIMATE_GRADE = 1
    SINGLE_VALUE = 2
    CLIMATE_ENTITY = 3


class Exclusion(StrEnum):
    DIAGNOSTIC = "diagnostic"
    HELPER = "helper"
    NO_DEVICE = "no_device"
    CONTACT = "contact"
    MOTION = "motion"
    SECONDARY = "secondary"
    SEVERAL_TEMPERATURES = "several_temperatures"
    IMPLAUSIBLE = "implausible"


@dataclass(frozen=True, slots=True)
class EntityInfo:
    entity_id: str
    name: str
    domain: str
    device_class: str | None
    platform: str
    category: str | None  # None, "diagnostic", "config"
    device_id: str | None
    area_id: str | None  # effective area: entity area, else device area
    value: float | None  # in the metric's unit; climate: current_temperature
    has_current_humidity: bool = False  # climate only


@dataclass(frozen=True, slots=True)
class Suggestion:
    sources: tuple[str, ...]
    excluded: tuple[tuple[str, Exclusion], ...]


@dataclass(frozen=True, slots=True)
class AreaInfo:
    area_id: str
    name: str
    floor_name: str | None
    floor_level: int | None


# Ordered (area_id, pre_checked) pairs
type RoomProposal = tuple[tuple[str, bool], ...]


def _is_sensor(entity: EntityInfo, metric: Metric) -> bool:
    return entity.domain == "sensor" and entity.device_class in _METRIC_CLASSES[metric]


def _is_candidate(entity: EntityInfo, metric: Metric, scope: Scope) -> bool:
    if _is_sensor(entity, metric):
        return True
    if entity.domain != "climate":
        return False
    if metric is Metric.TEMPERATURE:
        return True
    return (
        metric is Metric.HUMIDITY
        and scope is Scope.ROOM
        and entity.has_current_humidity
    )


def _range(metric: Metric, scope: Scope) -> tuple[float, float]:
    if metric is Metric.HUMIDITY:
        return HUMIDITY_RANGE
    if metric is Metric.PRESSURE:
        return PRESSURE_RANGE
    if scope is Scope.ROOM:
        return ROOM_TEMPERATURE_RANGE
    return REGION_TEMPERATURE_RANGE


def _implausible(entity: EntityInfo, metric: Metric, scope: Scope) -> bool:
    low, high = _range(metric, scope)
    return entity.value is not None and not low <= entity.value <= high


def _has_binary(pool: Iterable[EntityInfo], classes: Collection[str]) -> bool:
    return any(
        e.domain == "binary_sensor" and e.category is None and e.device_class in classes
        for e in pool
    )


def _has_sensor(pool: Iterable[EntityInfo], metric: Metric) -> bool:
    return any(_is_sensor(e, metric) and e.category is None for e in pool)


def classify(
    entity: EntityInfo,
    device_entities: Sequence[EntityInfo],
    metric: Metric,
    scope: Scope,
) -> Tier | Exclusion | None:
    """Tier or exclusion of a candidate; None if never offered (rules 1-12)."""
    if entity.platform == OWN_PLATFORM or not _is_candidate(entity, metric, scope):
        return None
    if entity.category is not None:
        return Exclusion.DIAGNOSTIC
    if entity.platform in HELPER_PLATFORMS:
        return Exclusion.HELPER
    if entity.device_id is None:
        return Exclusion.NO_DEVICE
    if entity.domain == "climate" and scope is Scope.ROOM:
        if _implausible(entity, metric, scope):
            return Exclusion.IMPLAUSIBLE
        return Tier.CLIMATE_ENTITY
    pool = [*(e for e in device_entities if e.entity_id != entity.entity_id), entity]
    if _has_binary(pool, CONTACT_CLASSES):
        return Exclusion.CONTACT
    if _has_binary(pool, MOTION_CLASSES):
        return Exclusion.MOTION
    if any(e.domain in ACTUATOR_DOMAINS and e.category is None for e in pool):
        return Exclusion.SECONDARY
    if metric is Metric.TEMPERATURE:
        temperatures = [
            e
            for e in pool
            if _is_sensor(e, metric)
            and e.category is None
            and e.platform not in HELPER_PLATFORMS
        ]
        if len(temperatures) > 1:
            return Exclusion.SEVERAL_TEMPERATURES
    if _implausible(entity, metric, scope):
        return Exclusion.IMPLAUSIBLE
    companion = Metric.HUMIDITY if metric is Metric.TEMPERATURE else Metric.TEMPERATURE
    return Tier.CLIMATE_GRADE if _has_sensor(pool, companion) else Tier.SINGLE_VALUE


# Exclusions that give way when an area has no other source (R6 last resort)
_WEAK = (Exclusion.NO_DEVICE, Exclusion.HELPER)


def _by_device(entities: Sequence[EntityInfo]) -> dict[str, list[EntityInfo]]:
    grouped: dict[str, list[EntityInfo]] = defaultdict(list)
    for entity in entities:
        if entity.device_id is not None:
            grouped[entity.device_id].append(entity)
    return grouped


def suggest_sources(
    area_id: str, entities: Sequence[EntityInfo], metric: Metric, scope: Scope
) -> Suggestion:
    """Pre-filled sources of an area in tier order plus excluded ones (R6, S4)."""
    devices = _by_device(entities)
    tiered: list[tuple[Tier, EntityInfo]] = []
    excluded: list[EntityInfo] = []
    reasons: dict[str, Exclusion] = {}
    weak_order: dict[str, int] = {}
    for entity in entities:
        if entity.area_id != area_id:
            continue
        group = devices.get(entity.device_id, []) if entity.device_id else []
        result = classify(entity, group, metric, scope)
        if isinstance(result, Tier):
            tiered.append((result, entity))
        elif result is not None:
            excluded.append(entity)
            reasons[entity.entity_id] = result
    if not tiered:
        # Last resort (R6): an area without any other source pre-fills plausible
        # entities without a device, then derived values.
        for entity in list(excluded):
            reason = reasons[entity.entity_id]
            if reason not in _WEAK or _implausible(entity, metric, scope):
                continue
            if entity.domain == "climate" and scope is Scope.REGION:
                continue
            tier = (
                Tier.CLIMATE_ENTITY if entity.domain == "climate" else Tier.SINGLE_VALUE
            )
            tiered.append((tier, entity))
            excluded.remove(entity)
            del reasons[entity.entity_id]
            weak_order[entity.entity_id] = _WEAK.index(reason)
    tiered.sort(
        key=lambda t: (
            t[0],
            weak_order.get(t[1].entity_id, 0),
            t[1].name.casefold(),
            t[1].entity_id,
        )
    )
    excluded.sort(key=lambda e: (e.name.casefold(), e.entity_id))
    return Suggestion(
        sources=tuple(e.entity_id for _, e in tiered),
        excluded=tuple((e.entity_id, reasons[e.entity_id]) for e in excluded),
    )


def follow_devices(
    temperature_sources: Sequence[str], entities: Sequence[EntityInfo], metric: Metric
) -> list[str]:
    """Humidity or pressure entities that follow the temperature devices (R3)."""
    if metric is Metric.TEMPERATURE:
        return []
    by_id = {e.entity_id: e for e in entities}
    devices = _by_device(entities)
    result: list[str] = []
    for source_id in temperature_sources:
        source = by_id.get(source_id)
        if source is None:
            continue
        if source.domain == "climate":
            found = (
                [source.entity_id]
                if metric is Metric.HUMIDITY and source.has_current_humidity
                else []
            )
        else:
            found = sorted(
                e.entity_id
                for e in devices.get(source.device_id or "", [])
                if _is_sensor(e, metric)
                and e.platform != OWN_PLATFORM
                and e.category is None
                and e.platform not in HELPER_PLATFORMS
            )
        result.extend(i for i in found if i not in result)
    return result


def suggest_metric_list(
    temperature_sources: Sequence[str],
    area_id: str,
    entities: Sequence[EntityInfo],
    metric: Metric,
    scope: Scope,
) -> list[str]:
    """Stored list at creation; empty means follow (R3)."""
    if follow_devices(temperature_sources, entities, metric):
        return []
    return list(suggest_sources(area_id, entities, metric, scope).sources)


def suggest_climate_devices(area_id: str, entities: Sequence[EntityInfo]) -> list[str]:
    """Heating and cooling devices of an area, by name (R15)."""
    found = [
        e
        for e in entities
        if e.area_id == area_id and e.domain == "climate" and e.platform != OWN_PLATFORM
    ]
    found.sort(key=lambda e: (e.name.casefold(), e.entity_id))
    return [e.entity_id for e in found]


def new_sources(
    area_id: str,
    entities: Sequence[EntityInfo],
    metric: Metric,
    scope: Scope,
    listed: Collection[str],
) -> list[str]:
    """Pre-fillable entities of the area not listed yet (R14)."""
    suggestion = suggest_sources(area_id, entities, metric, scope)
    return [i for i in suggestion.sources if i not in listed]


def propose_rooms(
    areas: Sequence[AreaInfo],
    entities: Sequence[EntityInfo],
    outside_words: Collection[str],
) -> RoomProposal:
    """Areas with a temperature source, ordered and pre-checked (S2)."""
    words = [w.casefold() for w in outside_words]
    proposed = [
        a
        for a in areas
        if suggest_sources(a.area_id, entities, Metric.TEMPERATURE, Scope.ROOM).sources
    ]
    proposed.sort(
        key=lambda a: (
            a.floor_name is None,
            a.floor_level is None,
            a.floor_level or 0,
            (a.floor_name or "").casefold(),
            a.name.casefold(),
        )
    )

    def checked(area: AreaInfo) -> bool:
        floor = (area.floor_name or "").casefold()
        if any(w in floor for w in words):
            return False
        if suggest_climate_devices(area.area_id, entities):
            return True
        return area.floor_name is not None

    return tuple((a.area_id, checked(a)) for a in proposed)
