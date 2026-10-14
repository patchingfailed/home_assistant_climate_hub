"""JSON codec of the persisted engine state (docs/integration.md §7).

Pure: turns `EngineState` and `Comfort` into JSON-safe structures and back.
Datetimes are ISO 8601 with offset, timedeltas seconds, `StrEnum` values their value,
`Level` its lower-case name, `WeatherOffsets` keys `"<direction>/<metric>"`.
"""

import logging
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from . import const
from .comfort import Dryness, Position, Relation, Trend, TrendState
from .cover import CoverReason, CoverState, CoverWanted
from .engine import (
    Comfort,
    EngineState,
    HubState,
    RegionState,
    RoomState,
    WindowStore,
)
from .house import OutageState
from .model import HouseModel
from .outdoor import Direction, WeatherOffsets
from .recommendation import Goal, GoalState
from .sources import Metric, Offset, SourceState
from .strategy import ForecastBias, Strategy
from .window import Debounced, Level

_LOGGER = logging.getLogger(__package__)

_DECODE_ERRORS = (KeyError, ValueError, TypeError, AttributeError, OverflowError)

# Dump helpers


def _dt(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _enum(value: StrEnum | None) -> str | None:
    return None if value is None else value.value


def _level(value: Level | None) -> str | None:
    return None if value is None else value.name.lower()


def _sources(sources: Mapping[Metric, SourceState]) -> dict[str, Any]:
    return {metric.value: _dump_source(state) for metric, state in sources.items()}


def _dump_offset(offset: Offset) -> dict[str, Any]:
    return {
        "learned": offset.learned,
        "paired": offset.paired.total_seconds(),
        "last_sample_at": offset.last_sample_at.isoformat(),
        "last_deviation": offset.last_deviation,
    }


def _dump_source(state: SourceState) -> dict[str, Any]:
    return {
        "offsets": {key: _dump_offset(o) for key, o in state.offsets.items()},
        "rank1": state.rank1,
        "winner": state.winner,
        "switched_at": _dt(state.switched_at),
        "anchor": state.anchor,
    }


def _dump_goal(goal: GoalState) -> dict[str, Any]:
    return {
        "goal": _enum(goal.goal),
        "started_at": _dt(goal.started_at),
        "pause_until": _dt(goal.pause_until),
        "humid_guard": goal.humid_guard,
    }


def _dump_room(room: RoomState) -> dict[str, Any]:
    return {
        "sources": _sources(room.sources),
        "trend_state": [[t.isoformat(), v] for t, v in room.trend_state.samples],
        "position": _enum(room.position),
        "relation": _enum(room.relation),
        "dryness": _enum(room.dryness),
        "trend": _enum(room.trend),
        "goal": None if room.goal is None else _dump_goal(room.goal),
    }


def _dump_window(window: WindowStore) -> dict[str, Any]:
    debounced = window.debounced
    cover = window.cover
    return {
        "debounced": None
        if debounced is None
        else {
            "raw": _level(debounced.raw),
            "raw_since": debounced.raw_since.isoformat(),
            "published": _level(debounced.published),
            "ventilating_since": _dt(debounced.ventilating_since),
        },
        "open_since": _dt(window.open_since),
        "cover": None
        if cover is None
        else {
            "wanted": _enum(cover.wanted),
            "reason": _enum(cover.reason),
            "since": _dt(cover.since),
            "relation": _enum(cover.relation),
            "heat_risk": cover.heat_risk,
        },
    }


def _dump_bias(bias: ForecastBias) -> dict[str, Any]:
    return {
        "bias_max": bias.bias_max,
        "bias_min": bias.bias_min,
        "samples": bias.samples,
        "day": None if bias.day is None else bias.day.isoformat(),
        "day_f_max": bias.day_f_max,
        "day_f_min": bias.day_f_min,
        "obs_max": bias.obs_max,
        "obs_min": bias.obs_min,
        "covered": bias.covered.total_seconds(),
        "last_at": _dt(bias.last_at),
    }


def _dump_hub(hub: HubState) -> dict[str, Any]:
    return {
        "weather_offsets": None
        if hub.weather_offsets is None
        else {
            f"{direction.value}/{metric.value}": _dump_offset(offset)
            for (direction, metric), offset in hub.weather_offsets.offsets.items()
        },
        "forecast_bias": None
        if hub.forecast_bias is None
        else _dump_bias(hub.forecast_bias),
        "strategy": _enum(hub.strategy),
        "outages": None
        if hub.outages is None
        else {k: v.isoformat() for k, v in hub.outages.invalid_since.items()},
    }


def dump_state(state: EngineState) -> dict[str, Any]:
    """Return the JSON-safe form of the engine state."""
    return {
        "rooms": {rid: _dump_room(r) for rid, r in state.rooms.items()},
        "regions": {
            rid: {"sources": _sources(r.sources)} for rid, r in state.regions.items()
        },
        "windows": {wid: _dump_window(w) for wid, w in state.windows.items()},
        "hub": _dump_hub(state.hub),
    }


def dump_comfort(comfort: Comfort) -> dict[str, float]:
    """Return the JSON-safe form of the comfort values."""
    return {
        "min": comfort.c_min,
        "max": comfort.c_max,
        "threshold": comfort.threshold,
    }


# Load helpers (raise on malformed input; callers isolate per object)


def _load_dt(value: Any) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("datetime without offset")
    return parsed


def _opt_dt(value: Any) -> datetime | None:
    return None if value is None else _load_dt(value)


def _float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("number expected")
    return float(value)


def _opt_float(value: Any) -> float | None:
    return None if value is None else _float(value)


def _opt_str(value: Any) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError("string expected")
    return value


def _opt_enum[E: StrEnum](cls: type[E], value: Any) -> E | None:
    return None if value is None else cls(value)


def _opt_level(value: Any) -> Level | None:
    return None if value is None else Level[value.upper()]


def _seconds(value: Any) -> timedelta:
    return timedelta(seconds=_float(value))


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError("bool expected")
    return value


def _load_offset(data: Mapping[str, Any]) -> Offset:
    return Offset(
        learned=_float(data["learned"]),
        paired=_seconds(data["paired"]),
        last_sample_at=_load_dt(data["last_sample_at"]),
        last_deviation=_float(data["last_deviation"]),
    )


def _load_source(data: Mapping[str, Any]) -> SourceState:
    return SourceState(
        offsets={str(k): _load_offset(v) for k, v in data["offsets"].items()},
        rank1=_opt_str(data["rank1"]),
        winner=_opt_str(data["winner"]),
        switched_at=_opt_dt(data["switched_at"]),
        anchor=_opt_float(data["anchor"]),
    )


def _load_sources(data: Mapping[str, Any]) -> dict[Metric, SourceState]:
    return {Metric(k): _load_source(v) for k, v in data.items()}


def _load_goal(data: Mapping[str, Any]) -> GoalState:
    return GoalState(
        goal=_opt_enum(Goal, data["goal"]),
        started_at=_opt_dt(data["started_at"]),
        pause_until=_opt_dt(data["pause_until"]),
        humid_guard=_bool(data["humid_guard"]),
    )


def _load_room(data: Mapping[str, Any]) -> RoomState:
    goal = data["goal"]
    return RoomState(
        sources=_load_sources(data["sources"]),
        trend_state=TrendState(
            tuple((_load_dt(t), _float(v)) for t, v in data["trend_state"])
        ),
        position=_opt_enum(Position, data["position"]),
        relation=_opt_enum(Relation, data["relation"]),
        dryness=_opt_enum(Dryness, data["dryness"]),
        trend=_opt_enum(Trend, data["trend"]),
        goal=None if goal is None else _load_goal(goal),
    )


def _load_region(data: Mapping[str, Any]) -> RegionState:
    return RegionState(sources=_load_sources(data["sources"]))


def _load_window(data: Mapping[str, Any]) -> WindowStore:
    debounced = data["debounced"]
    cover = data["cover"]
    return WindowStore(
        debounced=None
        if debounced is None
        else Debounced(
            raw=_opt_level(debounced["raw"]),
            raw_since=_load_dt(debounced["raw_since"]),
            published=_opt_level(debounced["published"]),
            ventilating_since=_opt_dt(debounced["ventilating_since"]),
        ),
        open_since=_opt_dt(data["open_since"]),
        cover=None
        if cover is None
        else CoverState(
            wanted=_opt_enum(CoverWanted, cover["wanted"]),
            reason=_opt_enum(CoverReason, cover["reason"]),
            since=_opt_dt(cover["since"]),
            relation=_opt_enum(Relation, cover["relation"]),
            heat_risk=_bool(cover["heat_risk"]),
        ),
    )


def _load_bias(data: Mapping[str, Any]) -> ForecastBias:
    samples = data["samples"]
    if isinstance(samples, bool) or not isinstance(samples, int):
        raise TypeError("int expected")
    day = data["day"]
    return ForecastBias(
        bias_max=_opt_float(data["bias_max"]),
        bias_min=_opt_float(data["bias_min"]),
        samples=samples,
        day=None if day is None else date.fromisoformat(day),
        day_f_max=_opt_float(data["day_f_max"]),
        day_f_min=_opt_float(data["day_f_min"]),
        obs_max=_opt_float(data["obs_max"]),
        obs_min=_opt_float(data["obs_min"]),
        covered=_seconds(data["covered"]),
        last_at=_opt_dt(data["last_at"]),
    )


def _load_hub(data: Mapping[str, Any]) -> HubState:
    offsets = data["weather_offsets"]
    bias = data["forecast_bias"]
    outages = data["outages"]
    weather_offsets = None
    if offsets is not None:
        parsed: dict[tuple[Direction, Metric], Offset] = {}
        for key, value in offsets.items():
            direction, metric = key.split("/")
            parsed[(Direction(direction), Metric(metric))] = _load_offset(value)
        weather_offsets = WeatherOffsets(parsed)
    return HubState(
        weather_offsets=weather_offsets,
        forecast_bias=None if bias is None else _load_bias(bias),
        strategy=_opt_enum(Strategy, data["strategy"]),
        outages=None
        if outages is None
        else OutageState({str(k): _load_dt(v) for k, v in outages.items()}),
    )


def _load_objects[T](
    data: Any, known: Mapping[str, Any], loader: Callable[[Any], T], kind: str
) -> dict[str, T]:
    """Decode the objects present in the model; a bad one is skipped (starts fresh)."""
    result: dict[str, T] = {}
    if not isinstance(data, Mapping):
        return result
    for object_id, raw in data.items():
        if object_id not in known:
            continue
        try:
            result[object_id] = loader(raw)
        except _DECODE_ERRORS as err:
            _LOGGER.debug("Stored %s %s starts fresh: %r", kind, object_id, err)
    return result


def load_state(data: Mapping[str, Any] | None, model: HouseModel) -> EngineState:
    """Decode the engine state, keeping only objects the model still has."""
    if not isinstance(data, Mapping):
        return EngineState.empty()
    hub = EngineState.empty().hub
    if "hub" in data:
        try:
            hub = _load_hub(data["hub"])
        except _DECODE_ERRORS as err:
            _LOGGER.debug("Stored hub state starts fresh: %r", err)
    return EngineState(
        rooms=_load_objects(data.get("rooms"), model.rooms, _load_room, "room"),
        regions=_load_objects(
            data.get("regions"), model.regions, _load_region, "region"
        ),
        windows=_load_objects(
            data.get("windows"), model.windows, _load_window, "window"
        ),
        hub=hub,
    )


def load_comfort(data: Mapping[str, Any] | None) -> Comfort:
    """Decode the comfort values; a missing or invalid value gets its default."""
    values = data if isinstance(data, Mapping) else {}

    def number(key: str, default: float) -> float:
        value = values.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return default
        return float(value)

    c_min = number("min", const.DEFAULT_COMFORT_MIN)
    c_max = number("max", const.DEFAULT_COMFORT_MAX)
    threshold = number("threshold", const.DEFAULT_STRATEGY_THRESHOLD)
    if c_min >= c_max:
        c_min, c_max = const.DEFAULT_COMFORT_MIN, const.DEFAULT_COMFORT_MAX
    return Comfort(c_min, c_max, threshold)
