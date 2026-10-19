"""Previews: one-shot engine runs turned into markdown (docs/integration.md 9.1, I1).

Texts come from the `common` translations of the instance language, because a flow
does not know the user's language (I16).
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import translation
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..labels import entity_name
from ..logic import const as logic_const
from ..logic import model as m
from ..logic.cover import CoverAdvice, CoverResult
from ..logic.engine import (
    Comfort,
    EngineResult,
    EngineState,
    Forecast,
    WindowResult,
    evaluate,
)
from ..logic.outdoor import Direction, fallback_chain
from ..logic.prefill import Exclusion
from ..logic.recommendation import Recommendation
from ..logic.sources import Candidate, Metric, Resolution, Stage, Status
from ..logic.strategy import Strategy
from ..logic.window import Level, OpenLeaves
from ..registry import build_model_from
from ..snapshot import async_fetch_forecast, build_snapshot, read_weather

PENDING_ID = "pending"
_BLOCK = "\n\n"
DOT_SEPARATOR = " · "
COMMA_SEPARATOR = ", "


class Texts:
    """The `common` translations of the instance language."""

    def __init__(self, strings: Mapping[str, str]) -> None:
        prefix = f"component.{DOMAIN}.common."
        self._strings = {
            key.removeprefix(prefix): value
            for key, value in strings.items()
            if key.startswith(prefix)
        }

    def __call__(self, key: str, **values: object) -> str:
        return self._strings[key].format(**values)

    def number(self, value: float, decimals: int = 1, *, signed: bool = False) -> str:
        """A number with the language's decimal separator."""
        text = f"{value:+.{decimals}f}" if signed else f"{value:.{decimals}f}"
        return text.replace(".", self._strings["number_decimal"])

    def direction(self, direction: str) -> str:
        return self(f"direction_{direction}")

    def join_and(self, items: Iterable[str]) -> str:
        """Join with the translated word for "and"."""
        return f" {self('and')} ".join(items)


async def async_texts(hass: HomeAssistant) -> Texts:
    return Texts(
        await translation.async_get_translations(
            hass, hass.config.language, "common", {DOMAIN}
        )
    )


def area_name(hass: HomeAssistant, area_id: str) -> str:
    area = ar.async_get(hass).async_get_area(area_id)
    return area_id if area is None else area.name


@dataclass(frozen=True, slots=True)
class NotTaken:
    """A candidate that was not suggested, and why (S4, S6)."""

    entity_id: str
    reason: Exclusion
    value: float | None


@dataclass(frozen=True, slots=True)
class PreviewRun:
    subentry_id: str  # of the pending object
    model: m.HouseModel
    result: EngineResult


@dataclass(frozen=True, slots=True)
class HouseRun:
    """An engine run over a whole pending configuration (S4, S10)."""

    model: m.HouseModel
    result: EngineResult


@dataclass(frozen=True, slots=True)
class PlanItem:
    """A room or outdoor side the house plan would create (S4, S10)."""

    subentry_id: str  # a placeholder until the subentry exists
    subentry_type: str
    area_id: str
    data: Mapping[str, Any]
    not_taken: tuple[NotTaken, ...]


class WeatherKind(StrEnum):
    NONE = "none"  # no weather entity chosen
    UNAVAILABLE = "unavailable"  # no state, unavailable or without a temperature
    NO_FORECAST = "no_forecast"  # values, but no forecast (a mirrored entity)
    HOURLY = "hourly"
    DAILY = "daily"


@dataclass(frozen=True, slots=True)
class WeatherStatus:
    """What the chosen weather entity delivers right now (S4, S9)."""

    kind: WeatherKind
    temperature: float | None = None
    humidity: float | None = None
    forecast: Forecast | None = None  # the test fetch, reused by the house run


async def async_weather_status(
    hass: HomeAssistant, weather_id: str | None
) -> WeatherStatus:
    """The current values and one test fetch of the forecast."""
    if not weather_id:
        return WeatherStatus(WeatherKind.NONE)
    readings, _ = read_weather(hass, weather_id)
    if readings is None or readings.temperature.value is None:
        return WeatherStatus(WeatherKind.UNAVAILABLE)
    forecast = await async_fetch_forecast(hass, weather_id)
    kind = (
        WeatherKind.NO_FORECAST
        if forecast is None
        else WeatherKind.HOURLY
        if forecast.hourly
        else WeatherKind.DAILY
    )
    return WeatherStatus(
        kind, readings.temperature.value, readings.humidity.value, forecast
    )


def weather_line(texts: Texts, status: WeatherStatus) -> str:
    """ "Wetterdienst: 12,5 °C · 89 %, Vorhersage stündlich." and its variants."""
    if status.kind is WeatherKind.NONE:
        return texts("weather_none")
    if status.kind is WeatherKind.UNAVAILABLE or status.temperature is None:
        return texts("weather_unavailable")
    temperature = texts.number(status.temperature)
    values = (
        texts("weather_values_temperature", temperature=temperature)
        if status.humidity is None
        else texts(
            "weather_values",
            temperature=temperature,
            humidity=texts.number(status.humidity, 0),
        )
    )
    if status.kind is WeatherKind.NO_FORECAST:
        return texts("weather_no_forecast", values=values)
    if status.kind is WeatherKind.HOURLY:
        return texts("weather_hourly", values=values)
    return texts("weather_daily", values=values)


async def _async_evaluate(
    hass: HomeAssistant,
    entry: ConfigEntry | None,
    options: Mapping[str, Any],
    triples: Iterable[tuple[str, str, Mapping[str, Any]]],
    weather: WeatherStatus | None = None,
) -> tuple[m.HouseModel, EngineResult]:
    """One engine run. A loaded hub lends its state, comfort values and forecast;
    otherwise (first setup) the state is empty, the comfort values are the defaults and
    the forecast is fetched once, or taken from the `weather` status that fetched it.
    """
    model = build_model_from(hass, options, triples)
    if entry is not None and entry.state is ConfigEntryState.LOADED:
        coordinator = entry.runtime_data.coordinator
        state, comfort, forecast = (
            coordinator.state,
            coordinator.comfort,
            coordinator.forecast,
        )
    else:
        state = EngineState.empty()
        comfort = Comfort(
            logic_const.DEFAULT_COMFORT_MIN,
            logic_const.DEFAULT_COMFORT_MAX,
            logic_const.DEFAULT_STRATEGY_THRESHOLD,
        )
        if weather is not None:
            forecast = weather.forecast
        else:
            forecast = (
                await async_fetch_forecast(hass, model.weather)
                if model.weather
                else None
            )
    snapshot = build_snapshot(hass, model, forecast)
    result, _ = evaluate(model, snapshot, state, comfort, dt_util.now())
    return model, result


async def async_run_preview(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry_id: str | None,
    subentry_type: str,
    data: Mapping[str, Any],
    extra: Iterable[PlanItem] = (),
) -> PreviewRun:
    """One engine run with the pending data applied to the model.

    `extra` are pending objects that would be created along (a window's room).
    """
    pending_id = subentry_id or PENDING_ID
    triples = [
        (sub.subentry_id, sub.subentry_type, sub.data)
        for sub in entry.subentries.values()
        if sub.subentry_id != subentry_id
    ]
    triples.append((pending_id, subentry_type, data))
    triples.extend((i.subentry_id, i.subentry_type, i.data) for i in extra)
    model, result = await _async_evaluate(hass, entry, entry.options, triples)
    return PreviewRun(pending_id, model, result)


async def async_run_house(
    hass: HomeAssistant,
    entry: ConfigEntry | None,
    options: Mapping[str, Any],
    items: Iterable[PlanItem],
    weather: WeatherStatus | None = None,
) -> HouseRun:
    """One engine run over pending rooms, outdoor sides and windows."""
    triples = [(i.subentry_id, i.subentry_type, i.data) for i in items]
    model, result = await _async_evaluate(hass, entry, options, triples, weather)
    return HouseRun(model, result)


# Markdown


def _value_lines(
    hass: HomeAssistant, texts: Texts, resolution: Resolution
) -> list[str]:
    """The current value with its source rank and the ready fallbacks."""
    if resolution.value is None or resolution.source is None:
        return [texts("preview_none")]
    lines = [
        texts(
            "preview_now",
            value=texts.number(resolution.value),
            source=entity_name(hass, resolution.source),
            rank=resolution.rank,
        )
    ]
    spares = [
        _spare_line(hass, texts, rank, candidate)
        for rank, candidate in enumerate(resolution.candidates, 1)
        if candidate.entity_id != resolution.source
        and candidate.status is Status.OK
        and candidate.value is not None
    ]
    if spares:
        lines.append(f"{texts('preview_spare_head')}\n\n" + "\n".join(spares))
    return lines


def _spare_line(
    hass: HomeAssistant, texts: Texts, rank: int, candidate: Candidate
) -> str:
    assert candidate.value is not None
    values: dict[str, object] = {
        "rank": rank,
        "source": entity_name(hass, candidate.entity_id),
        "value": texts.number(candidate.value),
    }
    if candidate.learned and candidate.offset is not None:
        return texts(
            "preview_spare_offset",
            offset=texts.number(candidate.offset, signed=True),
            **values,
        )
    return texts("preview_spare_learning", **values)


def _metric_line(
    hass: HomeAssistant,
    texts: Texts,
    resolutions: Mapping[Metric, Resolution],
    own: Collection[Metric],
) -> str:
    """Humidity and pressure with their source (R3: empty list follows)."""
    parts: list[tuple[Metric, str, str | None]] = []
    for metric, key in (
        (Metric.HUMIDITY, "preview_humidity"),
        (Metric.PRESSURE, "preview_pressure"),
    ):
        resolution = resolutions[metric]
        if resolution.value is not None:
            parts.append(
                (
                    metric,
                    texts(key, value=texts.number(resolution.value, 0)),
                    resolution.source,
                )
            )
    if not parts:
        return texts("preview_no_humidity")
    if not any(metric in own for metric, _, _ in parts):
        return texts(
            "preview_same_devices",
            parts=DOT_SEPARATOR.join(p for _, p, _ in parts),
        )
    named = [
        texts("preview_part_from", part=part, source=entity_name(hass, source))
        if metric in own and source
        else part
        for metric, part, source in parts
    ]
    return texts("preview_parts", parts=DOT_SEPARATOR.join(named))


def _own_metrics(data: Mapping[str, Any]) -> set[Metric]:
    return {
        metric
        for metric, key in (
            (Metric.HUMIDITY, m.CONF_HUMIDITY),
            (Metric.PRESSURE, m.CONF_PRESSURE),
        )
        if data.get(key)
    }


def _place(
    hass: HomeAssistant, texts: Texts, model: m.HouseModel, direction: Direction
) -> str:
    region = next((r for r in model.regions.values() if r.direction is direction), None)
    return texts(
        "place_side",
        direction=texts.direction(direction),
        area="" if region is None else area_name(hass, region.area_id),
    )


def _outside_line(hass: HomeAssistant, texts: Texts, run: PreviewRun) -> str:
    result = run.result.rooms[run.subentry_id]
    outdoor = result.outdoor.temperature
    if outdoor.value is None:
        return texts("preview_outside_none")
    if outdoor.stage is Stage.WEATHER or not outdoor.regions:
        place = texts("place_weather")
    else:
        place = texts.join_and(
            _place(hass, texts, run.model, d) for d in outdoor.regions
        )
    value = texts.number(outdoor.value)
    difference = result.temperature_difference
    if difference is None:
        return texts("preview_outside_plain", place=place, value=value)
    if round(difference, 1) == 0:
        relation = texts("relation_equal")
    else:
        relation = texts(
            "relation_warmer" if difference > 0 else "relation_colder",
            difference=texts.number(abs(difference)),
        )
    return texts("preview_outside", place=place, value=value, relation=relation)


def _not_taken_line(
    hass: HomeAssistant, texts: Texts, not_taken: Sequence[NotTaken]
) -> str:
    items = [
        texts(
            "not_taken_item_value"
            if item.reason is Exclusion.IMPLAUSIBLE and item.value is not None
            else "not_taken_item",
            name=entity_name(hass, item.entity_id),
            reason=texts(f"exclusion_{item.reason.value}"),
            value="" if item.value is None else texts.number(item.value),
        )
        for item in not_taken
    ]
    return texts("not_taken", items=COMMA_SEPARATOR.join(items))


def room_markdown(
    hass: HomeAssistant,
    texts: Texts,
    run: PreviewRun,
    data: Mapping[str, Any],
    not_taken: Sequence[NotTaken],
) -> str:
    """Screen S6 preview."""
    result = run.result.rooms.get(run.subentry_id)
    if result is None:
        return texts("preview_unavailable")
    resolutions = {
        Metric.HUMIDITY: result.humidity,
        Metric.PRESSURE: result.pressure,
    }
    lines = [
        *_value_lines(hass, texts, result.temperature),
        _metric_line(hass, texts, resolutions, _own_metrics(data)),
        _outside_line(hass, texts, run),
    ]
    if not_taken:
        lines.append(_not_taken_line(hass, texts, not_taken))
    return _BLOCK.join(lines)


def _chain_parts(
    hass: HomeAssistant,
    texts: Texts,
    model: m.HouseModel,
    direction: Direction,
    *,
    weather: bool = True,
) -> str:
    """ "Norden (Straße) und Süden (Garten) springen ein, dann der Wetterdienst"."""
    configured = {r.direction for r in model.regions.values()}
    parts = []
    first = True
    for stage, directions in fallback_chain(direction, configured):
        if stage is Stage.PRIMARY:
            continue
        if stage is Stage.WEATHER:
            if weather:
                parts.append(
                    texts("chain_weather_first" if first else "chain_weather_then")
                )
            continue
        places = [
            texts(
                "chain_place",
                direction=texts.direction(d),
                area=_region_area(hass, model, d),
            )
            for d in directions
        ]
        if first:
            key = "chain_first_one" if len(places) == 1 else "chain_first_two"
            parts.append(texts(key, places=texts.join_and(places)))
        else:
            parts.append(texts("chain_then", place=places[0]))
        first = False
    return "".join(parts)


def _chain_sentence(
    hass: HomeAssistant, texts: Texts, model: m.HouseModel, direction: Direction
) -> str:
    """ "Fällt Osten aus, springen Norden (Straße) und Süden (Garten) ein, ..." (S7)."""
    return (
        texts("chain_start", direction=texts.direction(direction))
        + " "
        + _chain_parts(hass, texts, model, direction)
        + texts("chain_end")
    )


def _no_side_line(
    hass: HomeAssistant, texts: Texts, model: m.HouseModel, direction: Direction
) -> str:
    """A direction without an outdoor side: the chain that serves it (I17)."""
    chain = _chain_parts(hass, texts, model, direction, weather=bool(model.weather))
    if not chain:
        return texts("plan_no_side_no_weather", direction=texts.direction(direction))
    return texts("plan_no_side", direction=texts.direction(direction), chain=chain)


def _region_area(hass: HomeAssistant, model: m.HouseModel, direction: Direction) -> str:
    region = next(r for r in model.regions.values() if r.direction is direction)
    return area_name(hass, region.area_id)


def region_markdown(
    hass: HomeAssistant, texts: Texts, run: PreviewRun, data: Mapping[str, Any]
) -> str:
    """Screen S7 preview."""
    result = run.result.regions.get(run.subentry_id)
    if result is None:
        return texts("preview_unavailable")
    resolutions = {
        Metric.HUMIDITY: result.own.humidity,
        Metric.PRESSURE: result.own.pressure,
    }
    return _BLOCK.join(
        [
            *_value_lines(hass, texts, result.own.temperature),
            _metric_line(hass, texts, resolutions, _own_metrics(data)),
            _chain_sentence(hass, texts, run.model, result.own.direction),
        ]
    )


def _spare_names(hass: HomeAssistant, resolution: Resolution) -> list[str]:
    return [
        entity_name(hass, c.entity_id)
        for c in resolution.candidates
        if c.entity_id != resolution.source
        and c.status is Status.OK
        and c.value is not None
    ]


def _plan_value(
    hass: HomeAssistant,
    texts: Texts,
    name: str,
    temperature: Resolution,
    humidity: Resolution,
) -> str:
    if temperature.value is None or temperature.source is None:
        return texts("plan_item_none", name=name)
    parts = (
        DOT_SEPARATOR + texts("plan_humidity", value=texts.number(humidity.value, 0))
        if humidity.value is not None
        else ""
    )
    return texts(
        "plan_item_value",
        name=name,
        value=texts.number(temperature.value),
        parts=parts,
        source=entity_name(hass, temperature.source),
    )


def _plan_item(head: str, details: Iterable[str]) -> str:
    return f"- {head}\n  " + " ".join(d for d in details if d)


def rooms_markdown(
    hass: HomeAssistant, texts: Texts, run: HouseRun, items: Sequence[PlanItem]
) -> str:
    """The rooms part of screen S4."""
    lines = []
    for item in items:
        result = run.result.rooms.get(item.subentry_id)
        if result is None:
            continue
        side = item.data[m.CONF_SIDE]
        spares = _spare_names(hass, result.temperature)
        lines.append(
            _plan_item(
                _plan_value(
                    hass,
                    texts,
                    area_name(hass, item.area_id),
                    result.temperature,
                    result.humidity,
                ),
                [
                    texts("plan_spare", sources=COMMA_SEPARATOR.join(spares))
                    if spares
                    else "",
                    texts("plan_side", side=texts.direction(side))
                    if side != m.SIDE_NONE
                    else texts("plan_side_none"),
                    _not_taken_line(hass, texts, item.not_taken)
                    if item.not_taken
                    else "",
                ],
            )
        )
    return _BLOCK.join([texts("plan_rooms_head"), "\n".join(lines)])


def regions_markdown(
    hass: HomeAssistant,
    texts: Texts,
    run: HouseRun,
    items: Sequence[PlanItem],
    *,
    missing_sides: bool,
) -> str:
    """The outdoor sides part of screens S4 and S10 (I17)."""
    lines = []
    for item in sorted(items, key=lambda i: str(i.data[m.CONF_DIRECTION])):
        result = run.result.regions.get(item.subentry_id)
        if result is None:
            continue
        direction = Direction(item.data[m.CONF_DIRECTION])
        title = texts(
            "region_title",
            direction=texts.direction(direction),
            area=area_name(hass, item.area_id),
        )
        lines.append(
            _plan_item(
                _plan_value(
                    hass, texts, title, result.own.temperature, result.own.humidity
                ),
                [
                    _chain_sentence(hass, texts, run.model, direction),
                    _not_taken_line(hass, texts, item.not_taken)
                    if item.not_taken
                    else "",
                ],
            )
        )
    if missing_sides:
        configured = {i.data[m.CONF_DIRECTION] for i in items}
        lines.extend(
            "- " + _no_side_line(hass, texts, run.model, d)
            for d in Direction
            if d.value not in configured
        )
    return _BLOCK.join([texts("plan_regions_head"), "\n".join(lines)])


def windows_markdown(
    hass: HomeAssistant, texts: Texts, run: HouseRun, items: Sequence[PlanItem]
) -> str:
    """The windows part of screen S4: each added window with its current state."""
    lines = []
    for item in items:
        result = run.result.windows.get(item.subentry_id)
        level = None if result is None else result.state.level
        lines.append(
            "- "
            + texts(
                "plan_window_item",
                title=texts(
                    "window_title",
                    area=area_name(hass, item.area_id),
                    name=item.data[m.CONF_NAME],
                ),
                state=texts("plan_window_unknown")
                if level is None
                else texts(_LEVEL_KEYS[level]),
            )
        )
    body = "\n".join(lines) if lines else "- " + texts("plan_windows_none")
    return _BLOCK.join([texts("plan_windows_head"), body])


def plan_markdown(
    hass: HomeAssistant,
    texts: Texts,
    run: HouseRun,
    rooms: Sequence[PlanItem],
    regions: Sequence[PlanItem],
    windows: Sequence[PlanItem],
    weather: WeatherStatus,
) -> str:
    """Screen S4: rooms, outdoor sides, the weather line, windows."""
    return _BLOCK.join(
        [
            rooms_markdown(hass, texts, run, rooms),
            regions_markdown(hass, texts, run, regions, missing_sides=True),
            weather_line(texts, weather),
            windows_markdown(hass, texts, run, windows),
            texts("plan_closing"),
        ]
    )


# Window preview (S8)

_LEVEL_KEYS = {
    Level.CLOSED: "level_closed",
    Level.AJAR: "level_ajar",
    Level.TILTED: "level_tilted",
    Level.OPEN: "level_open",
}
_LEAVES_KEYS = {
    OpenLeaves.LEFT: "leaves_left",
    OpenLeaves.RIGHT: "leaves_right",
    OpenLeaves.BOTH: "leaves_both",
}
_RECOMMENDATION_KEYS = {
    Recommendation.OPEN: "recommendation_open",
    Recommendation.KEEP_OPEN: "recommendation_keep_open",
    Recommendation.CLOSE: "recommendation_close",
    Recommendation.KEEP_CLOSED: "recommendation_keep_closed",
}
_STRATEGY_KEYS = {
    Strategy.PREVENT_HEAT_UP: "strategy_prevent_heat_up",
    Strategy.PREVENT_COOL_DOWN: "strategy_prevent_cool_down",
    Strategy.NEUTRAL: "strategy_neutral",
}
_COVER_KEYS = {
    CoverAdvice.CLOSE: "cover_close",
    CoverAdvice.KEEP_CLOSED: "cover_keep_closed",
    CoverAdvice.OPEN: "cover_open",
    CoverAdvice.KEEP_OPEN: "cover_keep_open",
}


def _facing_line(texts: Texts, window: m.WindowModel) -> str:
    """ "Ausrichtung: Norden, wie der Raum." and its variants."""
    degrees = (
        ""
        if window.facing_degrees is None
        else " "
        + texts("facing_degrees", degrees=texts.number(window.facing_degrees, 0))
    )
    if window.direction is None:
        return texts("facing_none") + degrees
    key = "facing_like_room" if window.facing is None else "facing_own"
    return texts(key, direction=texts.direction(window.direction)) + degrees


def _state_line(texts: Texts, result: WindowResult, now: datetime) -> str:
    state = result.state
    if state.level is None:
        return texts("preview_window_unknown")
    leaves = ""
    if state.level >= Level.TILTED and result.level.open_leaves in _LEAVES_KEYS:
        leaves = " " + texts(
            "preview_window_leaves",
            leaves=texts(_LEAVES_KEYS[result.level.open_leaves]),
        )
    since = ""
    if state.open_since is not None:
        minutes = int((now - state.open_since).total_seconds() // 60)
        since = ", " + (
            texts("preview_window_since", minutes=minutes)
            if minutes >= 1
            else texts("preview_window_since_short")
        )
    return texts(
        "preview_window_state",
        level=texts(_LEVEL_KEYS[state.level]),
        leaves=leaves,
        since=since,
    )


def _room_line(hass: HomeAssistant, texts: Texts, run: PreviewRun, room_id: str) -> str:
    room = run.model.rooms[room_id]
    result = run.result.rooms.get(room_id)
    area = area_name(hass, room.area_id)
    if result is None:
        return texts("preview_unavailable")
    key = _RECOMMENDATION_KEYS.get(result.recommendation.recommendation)
    if key is None:
        return texts("preview_room_no_recommendation", area=area)
    parts = []
    difference = result.temperature_difference
    if difference is not None:
        if round(difference, 1) == 0:
            parts.append(texts("preview_outside_equal"))
        else:
            parts.append(
                texts(
                    "preview_outside_warmer"
                    if difference > 0
                    else "preview_outside_colder",
                    difference=texts.number(abs(difference)),
                )
            )
    strategy = run.result.house.strategy.strategy if run.result.house else None
    if strategy is not None:
        parts.append(
            texts("preview_strategy", strategy=texts(_STRATEGY_KEYS[strategy]))
        )
    head = texts("preview_room", area=area, recommendation=texts(key))
    return head + (" " + COMMA_SEPARATOR.join(parts) + "." if parts else "")


def _cover_line(texts: Texts, cover: CoverResult) -> str:
    reason = texts(f"cover_reason_{cover.reason.value}")
    key = _COVER_KEYS.get(cover.advice)
    if key is None:
        return texts("preview_cover_none", reason=reason)
    return texts("preview_cover", advice=texts(key), reason=reason)


def window_markdown(
    hass: HomeAssistant,
    texts: Texts,
    run: PreviewRun,
    *,
    title: str | None,
    new_room: PlanItem | None,
) -> str:
    """Screen S8 preview. `title` is given when the name was left empty."""
    window = run.model.windows[run.subentry_id]
    result = run.result.windows.get(run.subentry_id)
    if result is None or window.room_id is None:
        return texts("preview_unavailable")
    lines = []
    if title is not None:
        lines.append(texts("preview_name", title=title))
    lines.append(_facing_line(texts, window))
    lines.append(_state_line(texts, result, dt_util.now()))
    lines.append(_room_line(hass, texts, run, window.room_id))
    if window.cover:
        lines.append(_cover_line(texts, result.cover))
    if new_room is not None:
        sources = [
            entity_name(hass, entity_id)
            for entity_id in dict.fromkeys(
                [
                    *new_room.data.get(m.CONF_TEMPERATURE, ()),
                    *new_room.data.get(m.CONF_CLIMATE_DEVICES, ()),
                ]
            )
        ]
        area = area_name(hass, new_room.area_id)
        lines.append(
            texts(
                "preview_room_created",
                area=area,
                sources=COMMA_SEPARATOR.join(sources),
            )
            if sources
            else texts("preview_room_created_bare", area=area)
        )
    return _BLOCK.join(lines)
