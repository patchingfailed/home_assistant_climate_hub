"""Previews: one-shot engine runs turned into markdown (docs/integration.md 9.1, I1).

Texts come from the `common` translations of the instance language, because a flow
does not know the user's language (I16).
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import translation
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..logic import const as logic_const
from ..logic import model as m
from ..logic.engine import Comfort, EngineResult, EngineState, evaluate
from ..logic.outdoor import Direction, fallback_chain
from ..logic.prefill import Exclusion
from ..logic.sources import Candidate, Metric, Resolution, Stage, Status
from ..registry import build_model_from
from ..snapshot import async_fetch_forecast, build_snapshot

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


def entity_name(hass: HomeAssistant, entity_id: str) -> str:
    """The friendly name, else the registry name, else the entity ID."""
    state = hass.states.get(entity_id)
    if state is not None and (name := state.attributes.get("friendly_name")):
        return str(name)
    entry = er.async_get(hass).async_get(entity_id)
    return str((entry and (entry.name or entry.original_name)) or entity_id)


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


async def async_run_preview(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry_id: str | None,
    subentry_type: str,
    data: Mapping[str, Any],
) -> PreviewRun:
    """One engine run with the pending data applied to the model.

    A loaded hub lends its state, comfort values and forecast; otherwise (first
    setup) the state is empty, the comfort values are the defaults and the forecast is
    fetched once.
    """
    pending_id = subentry_id or PENDING_ID
    triples = [
        (sub.subentry_id, sub.subentry_type, sub.data)
        for sub in entry.subentries.values()
        if sub.subentry_id != subentry_id
    ]
    triples.append((pending_id, subentry_type, data))
    model = build_model_from(hass, entry.options, triples)
    if entry.state is ConfigEntryState.LOADED:
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
        forecast = (
            await async_fetch_forecast(hass, model.weather) if model.weather else None
        )
    snapshot = build_snapshot(hass, model, forecast)
    result, _ = evaluate(model, snapshot, state, comfort, dt_util.now())
    return PreviewRun(pending_id, model, result)


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


def _chain_sentence(
    hass: HomeAssistant, texts: Texts, model: m.HouseModel, direction: Direction
) -> str:
    """ "Fällt Osten aus, springen Norden (Straße) und Süden (Garten) ein, ..." (S7)."""
    configured = {r.direction for r in model.regions.values()}
    parts = [texts("chain_start", direction=texts.direction(direction)) + " "]
    first = True
    for stage, directions in fallback_chain(direction, configured)[1:]:
        if stage is Stage.WEATHER:
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
    return "".join(parts) + texts("chain_end")


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
