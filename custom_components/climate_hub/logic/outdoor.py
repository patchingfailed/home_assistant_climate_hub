"""Outdoor values per direction (docs/logic.md §5; O1-O7, ADR-003, D3, D15)."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from statistics import fmean

from . import const
from .psychro import absolute_humidity, dew_point
from .sources import (
    Metric,
    Offset,
    Reading,
    Resolution,
    Stage,
    Status,
    effective_status,
    learn,
)


class Direction(StrEnum):
    """Compass sides in circular order."""

    N = "n"
    E = "e"
    S = "s"
    W = "w"


class OutdoorReason(StrEnum):
    """Why an outdoor value is missing (stage NONE)."""

    NO_SIDE = "no_side"
    NO_PAIR = "no_pair"
    NO_DATA = "no_data"


_ORDER = tuple(Direction)


@dataclass(frozen=True, slots=True)
class RegionOwn:
    """One configured region with its own sources resolved (§4)."""

    direction: Direction
    temperature: Resolution
    humidity: Resolution
    pressure: Resolution


@dataclass(frozen=True, slots=True)
class WeatherReadings:
    temperature: Reading
    humidity: Reading
    pressure: Reading


@dataclass(frozen=True, slots=True)
class WeatherOffsets:
    """Persisted: per (direction, metric) the learned `weather - own` offset."""

    offsets: Mapping[tuple[Direction, Metric], Offset]


@dataclass(frozen=True, slots=True)
class OutdoorValue:
    value: float | None
    stage: Stage
    regions: tuple[Direction, ...]  # empty for WEATHER and NONE
    reason: OutdoorReason | None  # only at stage NONE
    offset: float | None  # applied weather offset, only at stage WEATHER (E6)


@dataclass(frozen=True, slots=True)
class OutdoorValues:
    temperature: OutdoorValue
    humidity: OutdoorValue
    pressure: OutdoorValue
    absolute_humidity: OutdoorValue
    dew_point: OutdoorValue


@dataclass(frozen=True, slots=True)
class HouseOutdoor:
    value: float | None
    stage: Stage  # PRIMARY, FALLBACK, WEATHER or NONE
    minimum: float | None
    maximum: float | None
    per_region: Mapping[Direction, float]


def fallback_chain(
    direction: Direction, configured: Collection[Direction]
) -> list[tuple[Stage, tuple[Direction, ...]]]:
    """Rule 1: own region, neighbours (one stage), opposite, weather."""
    index = _ORDER.index(direction)
    neighbours = {_ORDER[(index + 1) % 4], _ORDER[(index - 1) % 4]}
    stages = [
        (Stage.PRIMARY, (direction,)),
        (Stage.NEIGHBOUR, tuple(d for d in _ORDER if d in neighbours)),
        (Stage.OPPOSITE, (_ORDER[(index + 2) % 4],)),
    ]
    chain = [
        (stage, present)
        for stage, dirs in stages
        if (present := tuple(d for d in dirs if d in configured))
    ]
    chain.append((Stage.WEATHER, ()))
    return chain


def _resolution(region: RegionOwn, metric: Metric) -> Resolution:
    return {
        Metric.TEMPERATURE: region.temperature,
        Metric.HUMIDITY: region.humidity,
        Metric.PRESSURE: region.pressure,
    }[metric]


def _weather_reading(weather: WeatherReadings, metric: Metric) -> Reading:
    return {
        Metric.TEMPERATURE: weather.temperature,
        Metric.HUMIDITY: weather.humidity,
        Metric.PRESSURE: weather.pressure,
    }[metric]


def _weather_raw(
    weather: WeatherReadings | None, metric: Metric, now: datetime
) -> float | None:
    if weather is None:
        return None
    reading = _weather_reading(weather, metric)
    if effective_status(reading, const.WEATHER_MAX_AGE, now) is not Status.OK:
        return None
    return reading.value


def learn_weather_offsets(
    regions: Mapping[Direction, RegionOwn],
    weather: WeatherReadings | None,
    state: WeatherOffsets | None,
    now: datetime,
) -> WeatherOffsets:
    """Rule 9: learn `weather - own` while both are valid; drop removed regions."""
    previous = state.offsets if state is not None else {}
    offsets = {key: value for key, value in previous.items() if key[0] in regions}
    for direction, region in regions.items():
        for metric in Metric:
            raw = _weather_raw(weather, metric, now)
            own = _resolution(region, metric).value
            if raw is None or own is None:
                continue
            key = (direction, metric)
            offsets[key] = learn(offsets.get(key), raw - own, now)
    return WeatherOffsets(offsets)


def _applied_offset(
    direction: Direction | None, metric: Metric, offsets: WeatherOffsets
) -> float:
    """The direction's own offset, else the mean of the metric's offsets, else 0."""
    own = offsets.offsets.get((direction, metric)) if direction is not None else None
    if own is not None:
        return own.learned
    learned = [o.learned for (_, m), o in offsets.offsets.items() if m is metric]
    return fmean(learned) if learned else 0.0


def _corrected_weather(
    direction: Direction | None,
    metric: Metric,
    weather: WeatherReadings | None,
    offsets: WeatherOffsets,
    now: datetime,
) -> tuple[float, float] | None:
    """`(corrected value, applied offset)` of the weather, `None` if not valid."""
    raw = _weather_raw(weather, metric, now)
    if raw is None:
        return None
    applied = _applied_offset(direction, metric, offsets)
    value = raw - applied
    if metric is Metric.HUMIDITY:
        value = min(max(value, const.HUMIDITY_RANGE[0]), const.HUMIDITY_RANGE[1])
    return value, applied


def _none(reason: OutdoorReason) -> OutdoorValue:
    return OutdoorValue(None, Stage.NONE, (), reason, None)


def _resolve_metric(
    direction: Direction,
    metric: Metric,
    regions: Mapping[Direction, RegionOwn],
    weather: WeatherReadings | None,
    offsets: WeatherOffsets,
    now: datetime,
) -> OutdoorValue:
    for stage, dirs in fallback_chain(direction, regions):
        found = [
            (d, value)
            for d in dirs
            if (value := _resolution(regions[d], metric).value) is not None
        ]
        if not found:
            continue
        if stage is Stage.PRIMARY:
            stage = _resolution(regions[direction], metric).stage
        return OutdoorValue(
            fmean(value for _, value in found),
            stage,
            tuple(d for d, _ in found),
            None,
            None,
        )
    corrected = _corrected_weather(direction, metric, weather, offsets, now)
    if corrected is None:
        return _none(OutdoorReason.NO_DATA)
    return OutdoorValue(corrected[0], Stage.WEATHER, (), None, corrected[1])


def _pair(temperature: float, humidity: float) -> tuple[float, float] | None:
    ah = absolute_humidity(temperature, humidity)
    dp = dew_point(temperature, humidity)
    return None if ah is None or dp is None else (ah, dp)


def _resolve_pair(
    direction: Direction,
    regions: Mapping[Direction, RegionOwn],
    weather: WeatherReadings | None,
    offsets: WeatherOffsets,
    now: datetime,
) -> tuple[OutdoorValue, OutdoorValue]:
    """Rule 5: first stage where temperature and humidity share the same regions."""
    for stage, dirs in fallback_chain(direction, regions):
        found: list[tuple[Direction, tuple[float, float]]] = []
        for d in dirs:
            t, h = regions[d].temperature, regions[d].humidity
            if t.value is None or h.value is None:
                continue
            if (pair := _pair(t.value, h.value)) is not None:
                found.append((d, pair))
        if not found:
            continue
        if stage is Stage.PRIMARY:
            own = regions[direction]
            fallback = Stage.FALLBACK in (own.temperature.stage, own.humidity.stage)
            stage = Stage.FALLBACK if fallback else Stage.PRIMARY
        used = tuple(d for d, _ in found)
        return (
            OutdoorValue(fmean(p[0] for _, p in found), stage, used, None, None),
            OutdoorValue(fmean(p[1] for _, p in found), stage, used, None, None),
        )
    t = _corrected_weather(direction, Metric.TEMPERATURE, weather, offsets, now)
    h = _corrected_weather(direction, Metric.HUMIDITY, weather, offsets, now)
    pair = _pair(t[0], h[0]) if t is not None and h is not None else None
    if pair is None:
        missing = _none(OutdoorReason.NO_PAIR)
        return missing, missing
    return (
        OutdoorValue(pair[0], Stage.WEATHER, (), None, None),
        OutdoorValue(pair[1], Stage.WEATHER, (), None, None),
    )


def resolve_direction(
    direction: Direction | None,
    regions: Mapping[Direction, RegionOwn],
    weather: WeatherReadings | None,
    offsets: WeatherOffsets,
    now: datetime,
) -> OutdoorValues:
    """Rules 1-7: all outdoor values a direction (and its rooms) sees."""
    if direction is None:
        missing = _none(OutdoorReason.NO_SIDE)
        return OutdoorValues(missing, missing, missing, missing, missing)
    ah, dp = _resolve_pair(direction, regions, weather, offsets, now)
    return OutdoorValues(
        temperature=_resolve_metric(
            direction, Metric.TEMPERATURE, regions, weather, offsets, now
        ),
        humidity=_resolve_metric(
            direction, Metric.HUMIDITY, regions, weather, offsets, now
        ),
        pressure=_resolve_metric(
            direction, Metric.PRESSURE, regions, weather, offsets, now
        ),
        absolute_humidity=ah,
        dew_point=dp,
    )


def house_outdoor(
    regions: Mapping[Direction, RegionOwn],
    weather: WeatherReadings | None,
    offsets: WeatherOffsets,
    now: datetime,
) -> HouseOutdoor:
    """Rule 8 (O7): mean of the regions' own temperatures, else the weather."""
    per_region = {
        d: region.temperature.value
        for d, region in regions.items()
        if region.temperature.value is not None
    }
    if per_region:
        fallback = any(
            regions[d].temperature.stage is Stage.FALLBACK for d in per_region
        )
        return HouseOutdoor(
            value=fmean(per_region.values()),
            stage=Stage.FALLBACK if fallback else Stage.PRIMARY,
            minimum=min(per_region.values()),
            maximum=max(per_region.values()),
            per_region=per_region,
        )
    corrected = _corrected_weather(None, Metric.TEMPERATURE, weather, offsets, now)
    if corrected is None:
        return HouseOutdoor(None, Stage.NONE, None, None, {})
    return HouseOutdoor(corrected[0], Stage.WEATHER, None, None, {})
