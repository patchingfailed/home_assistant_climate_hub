"""Pure evaluation of the whole house (docs/integration.md §4, docs/logic.md §2).

One call per coordinator update: orchestrates the logic modules in the order of the
adapter contract (logic §14) and isolates every object (N2): a failing region, room
or hub part is reported in `failures`, keeps its previous state, and its dependants
see missing data.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial

from . import const
from .comfort import (
    Dryness,
    Position,
    Relation,
    Trend,
    TrendState,
    comfort_position,
    outside_dryness,
    outside_relation,
)
from .comfort import trend as compute_trend
from .cover import (
    CoverAdvice,
    CoverInput,
    CoverPosition,
    CoverReason,
    CoverResult,
    CoverState,
    any_cover_to_close,
    facing_azimuth,
)
from .cover import cover as compute_cover
from .house import HouseValue, Outage, OutageState, any_of, indoor_average, outages
from .model import HouseModel, RegionModel, RoomModel, Settings, WindowModel
from .outdoor import (
    Direction,
    HouseOutdoor,
    OutdoorReason,
    OutdoorValue,
    OutdoorValues,
    RegionOwn,
    WeatherOffsets,
    WeatherReadings,
    house_outdoor,
    learn_weather_offsets,
    resolve_direction,
)
from .psychro import absolute_humidity, dew_point
from .recommendation import (
    ClimateDevice,
    GoalState,
    RecommendationResult,
    RoomInput,
    open_while_conditioning,
    recommend,
    warnings,
)
from .sources import Metric, Reading, Resolution, SourceState, Stage, Status, resolve
from .strategy import (
    ForecastBias,
    ForecastPoint,
    Strategy,
    StrategyResult,
    daily_strategy,
    update_forecast_bias,
)
from .window import (
    Debounced,
    Level,
    RoomWindows,
    WindowLevel,
    WindowState,
    contact_level,
    debounce,
    open_since,
    room_windows,
    ventilating,
    window_level,
)

# Inputs (§4.1)


@dataclass(frozen=True, slots=True)
class Comfort:
    c_min: float
    c_max: float
    threshold: float


@dataclass(frozen=True, slots=True)
class Contact:
    raw: str | None
    last_changed: datetime | None


@dataclass(frozen=True, slots=True)
class Forecast:
    points: tuple[ForecastPoint, ...]
    hourly: bool


@dataclass(frozen=True, slots=True)
class Snapshot:
    readings: Mapping[tuple[str, Metric], Reading]  # statuses set by the adapter
    contacts: Mapping[str, Contact]
    climate: Mapping[str, ClimateDevice]
    covers: Mapping[str, CoverPosition]
    weather: WeatherReadings | None
    clouds: float | None
    forecast: Forecast | None
    sun_azimuth: float | None
    sun_elevation: float | None


# State, persisted (§4.2)


@dataclass(frozen=True, slots=True)
class RoomState:
    sources: Mapping[Metric, SourceState]
    trend_state: TrendState
    position: Position | None
    relation: Relation | None
    dryness: Dryness | None
    trend: Trend | None
    goal: GoalState | None


@dataclass(frozen=True, slots=True)
class RegionState:
    sources: Mapping[Metric, SourceState]


@dataclass(frozen=True, slots=True)
class WindowStore:
    debounced: Debounced | None
    open_since: datetime | None
    cover: CoverState | None


@dataclass(frozen=True, slots=True)
class HubState:
    weather_offsets: WeatherOffsets | None
    forecast_bias: ForecastBias | None
    strategy: Strategy | None
    outages: OutageState | None


@dataclass(frozen=True, slots=True)
class EngineState:
    rooms: Mapping[str, RoomState]
    regions: Mapping[str, RegionState]
    windows: Mapping[str, WindowStore]
    hub: HubState

    @classmethod
    def empty(cls) -> EngineState:
        """Start-up value: every object starts fresh."""
        return cls({}, {}, {}, HubState(None, None, None, None))


# Results (§4.5)


@dataclass(frozen=True, slots=True)
class RoomResult:
    temperature: Resolution
    humidity: Resolution
    pressure: Resolution
    absolute_humidity: float | None
    dew_point: float | None
    outdoor: OutdoorValues
    temperature_difference: float | None
    humidity_difference: float | None
    humidity_after_ventilating: float | None
    position: Position | None
    relation: Relation | None
    trend: Trend | None
    recommendation: RecommendationResult
    windows: RoomWindows | None
    cooling_down: bool | None
    heating_up: bool | None
    open_while_conditioning: bool | None


@dataclass(frozen=True, slots=True)
class RegionResult:
    own: RegionOwn
    values: OutdoorValues


@dataclass(frozen=True, slots=True)
class WindowResult:
    level: WindowLevel
    state: WindowState
    cover: CoverResult


@dataclass(frozen=True, slots=True)
class HouseResult:
    strategy: StrategyResult
    indoor: HouseValue
    outdoor: HouseOutdoor
    any_cooling_down: bool | None
    any_heating_up: bool | None
    any_open_while_conditioning: bool | None
    any_cover_to_close: bool
    covers_to_close: tuple[tuple[str, CoverReason], ...]  # window IDs
    outages: tuple[Outage, ...]  # keyed "<object id>/<entity id>"


@dataclass(frozen=True, slots=True)
class EngineResult:
    rooms: Mapping[str, RoomResult]
    regions: Mapping[str, RegionResult]
    windows: Mapping[str, WindowResult]
    house: HouseResult | None
    failures: Mapping[str, str]  # object ID -> exception text


_NO_VALUE = OutdoorValue(None, Stage.NONE, (), OutdoorReason.NO_DATA, None)
_NO_OUTDOOR = OutdoorValues(_NO_VALUE, _NO_VALUE, _NO_VALUE, _NO_VALUE, _NO_VALUE)
_NO_HOUSE_OUTDOOR = HouseOutdoor(None, Stage.NONE, None, None, {})
_NO_STRATEGY = StrategyResult(None, None, None, None, None, None, None)
_FRESH_ROOM = RoomState({}, TrendState(), None, None, None, None, None)
_NO_CONTACT = Contact(None, None)
_NO_WINDOW_STATE = WindowState(None, None, None)
_NO_DEVICE = ClimateDevice(None, None)
_NO_COVER = CoverResult(CoverAdvice.NONE, CoverReason.NO_DATA)


def _attempt[T](
    failures: dict[str, str], key: str, call: Callable[[], T], fallback: T
) -> T:
    """Run one part of the evaluation; record its failure and use the fallback."""
    try:
        return call()
    except Exception as exc:
        failures[key] = f"{type(exc).__name__}: {exc}"
        return fallback


def _readings(snap: Snapshot, ids: Sequence[str], metric: Metric) -> list[Reading]:
    return [
        snap.readings.get((entity_id, metric))
        or Reading(entity_id, None, Status.MISSING, None)
        for entity_id in ids
    ]


def _resolve_metrics(
    snap: Snapshot,
    model: RoomModel | RegionModel,
    previous: Mapping[Metric, SourceState],
    now: datetime,
) -> tuple[dict[Metric, Resolution], dict[Metric, SourceState]]:
    """Step 1 and 5: resolve the three metrics of one room or region."""
    resolutions: dict[Metric, Resolution] = {}
    states: dict[Metric, SourceState] = {}
    for metric in Metric:
        bounds = const.HUMIDITY_RANGE if metric is Metric.HUMIDITY else None
        resolutions[metric], states[metric] = resolve(
            _readings(snap, model.sources[metric], metric),
            model.max_age,
            previous.get(metric),
            now,
            bounds,
        )
    return resolutions, states


def _outage_statuses(
    object_id: str, resolutions: Mapping[Metric, Resolution]
) -> dict[str, Status]:
    """Step 10: an entity is invalid when all its readings are; first metric counts."""
    per_entity: dict[str, list[Status]] = {}
    for metric in Metric:
        for candidate in resolutions[metric].candidates:
            per_entity.setdefault(candidate.entity_id, []).append(candidate.status)
    return {
        f"{object_id}/{entity_id}": Status.OK if Status.OK in found else found[0]
        for entity_id, found in per_entity.items()
    }


def _evaluate_region(
    region: RegionModel,
    snap: Snapshot,
    prev: RegionState | None,
    now: datetime,
) -> tuple[RegionOwn, RegionState, dict[str, Status]]:
    """Step 1: the region's own sources."""
    resolutions, states = _resolve_metrics(
        snap, region, prev.sources if prev else {}, now
    )
    own = RegionOwn(
        region.direction,
        resolutions[Metric.TEMPERATURE],
        resolutions[Metric.HUMIDITY],
        resolutions[Metric.PRESSURE],
    )
    return own, RegionState(states), _outage_statuses(region.id, resolutions)


def _difference(outside: float | None, inside: float | None) -> float | None:
    return None if outside is None or inside is None else outside - inside


def _evaluate_window(
    window: WindowModel,
    snap: Snapshot,
    prev: WindowStore | None,
    now: datetime,
) -> tuple[WindowLevel, WindowState, WindowStore]:
    """Step 7: contacts to level, debounce and open since of one window."""
    contacts = {
        entity_id: snap.contacts.get(entity_id, _NO_CONTACT)
        for entity_id in window.kinds
    }
    levels = {
        entity_id: contact_level(
            contact.raw, window.kinds[entity_id], window.mappings.get(entity_id)
        )
        for entity_id, contact in contacts.items()
    }
    level = window_level(window.config, levels)
    debounced = debounce(
        level.level, prev.debounced if prev else None, now, window.min_level
    )
    # after a restart: the latest change among the contacts that report non-closed now
    changed = [
        contact.last_changed
        for entity_id, contact in contacts.items()
        if contact.last_changed is not None
        and (known := levels[entity_id]) is not None
        and known > Level.CLOSED
    ]
    since = open_since(
        debounced,
        window.min_level,
        prev.open_since if prev else None,
        max(changed, default=None),
    )
    state = WindowState(
        debounced.published, ventilating(debounced.published, window.min_level), since
    )
    store = WindowStore(debounced, since, prev.cover if prev else None)
    return level, state, store


def _evaluate_cover(
    window: WindowModel,
    snap: Snapshot,
    prev: CoverState | None,
    published: WindowState,
    room: RoomResult | None,
    outdoor: OutdoorValues,
    strategy: Strategy | None,
    comfort: Comfort,
    now: datetime,
) -> tuple[CoverResult, CoverState | None]:
    """Step 9: cover advice of one window; `room` is `None` when its room failed."""
    has_room = window.room_id is not None
    if window.direction is None:
        facing = window.facing_degrees
    else:
        facing = facing_azimuth(window.direction, window.facing_degrees)
    if has_room and facing is None:
        return _NO_COVER, prev
    inp = CoverInput(
        has_room=has_room,
        sun_azimuth=snap.sun_azimuth,
        sun_elevation=snap.sun_elevation,
        clouds=snap.clouds,
        facing=0.0 if facing is None else facing,
        t_room=room.temperature.value if room else None,
        c_min=comfort.c_min,
        c_max=comfort.c_max,
        position=room.position if room else None,
        t_out=outdoor.temperature.value,
        strategy=strategy,
        window_level=published.level,
        cover=snap.covers.get(window.cover) if window.cover else None,
    )
    return compute_cover(inp, prev, now)


def _evaluate_room(
    room: RoomModel,
    snap: Snapshot,
    prev: RoomState | None,
    outdoor: OutdoorValues,
    strategy: Strategy | None,
    comfort: Comfort,
    settings: Settings,
    window_states: Sequence[WindowState],
    now: datetime,
) -> tuple[RoomResult, RoomState, dict[str, Status]]:
    """Steps 5, 7 (room part) and 8: derived values, windows, recommendation."""
    prev = prev or _FRESH_ROOM
    resolutions, source_states = _resolve_metrics(snap, room, prev.sources, now)
    temperature = resolutions[Metric.TEMPERATURE]
    humidity = resolutions[Metric.HUMIDITY]
    t_in, rh_in = temperature.value, humidity.value
    pair = t_in is not None and rh_in is not None
    ah_in = absolute_humidity(t_in, rh_in) if pair else None
    dp_in = dew_point(t_in, rh_in) if pair else None

    t_out = outdoor.temperature.value
    position = comfort_position(t_in, comfort.c_min, comfort.c_max, prev.position)
    relation = outside_relation(t_out, t_in, prev.relation)
    dryness = outside_dryness(outdoor.absolute_humidity.value, ah_in, prev.dryness)
    trend, trend_state = compute_trend(prev.trend_state, t_in, now, prev.trend)

    aggregated = room_windows(window_states) if window_states else None
    recommendation, goal = recommend(
        RoomInput(
            t_in=t_in,
            rh_in=rh_in,
            t_out=t_out,
            dew_point_out=outdoor.dew_point.value,
            c_min=comfort.c_min,
            c_max=comfort.c_max,
            position=position,
            relation=relation,
            dryness=dryness,
            trend=trend,
            strategy=strategy,
            has_windows=aggregated is not None,
            has_side=room.side is not None,
            ventilating=aggregated.ventilating if aggregated else None,
            ventilating_since=aggregated.open_since if aggregated else None,
            humidity_threshold=settings.humidity_threshold,
            burst_duration=settings.burst_duration,
        ),
        prev.goal,
        now,
    )
    cooling_down = heating_up = conditioning = None
    if aggregated is not None:
        cooling_down, heating_up = warnings(
            strategy=strategy,
            relation=relation,
            trend=trend,
            ventilating=aggregated.ventilating,
            ventilating_since=aggregated.open_since,
            wanted_open=recommendation.wanted_open,
            burst_duration=settings.burst_duration,
            now=now,
        )
        if room.climate_devices:
            conditioning = open_while_conditioning(
                devices=tuple(
                    snap.climate.get(entity_id, _NO_DEVICE)
                    for entity_id in room.climate_devices
                ),
                ventilating=aggregated.ventilating,
                ventilating_since=aggregated.open_since,
                burst_duration=settings.burst_duration,
                now=now,
            )
    result = RoomResult(
        temperature=temperature,
        humidity=humidity,
        pressure=resolutions[Metric.PRESSURE],
        absolute_humidity=ah_in,
        dew_point=dp_in,
        outdoor=outdoor,
        temperature_difference=_difference(t_out, t_in),
        humidity_difference=_difference(outdoor.absolute_humidity.value, ah_in),
        humidity_after_ventilating=recommendation.humidity_after_ventilating,
        position=position,
        relation=relation,
        trend=trend,
        recommendation=recommendation,
        windows=aggregated,
        cooling_down=cooling_down,
        heating_up=heating_up,
        open_while_conditioning=conditioning,
    )
    state = RoomState(
        source_states, trend_state, position, relation, dryness, trend, goal
    )
    return result, state, _outage_statuses(room.id, resolutions)


def evaluate(
    model: HouseModel,
    snap: Snapshot,
    state: EngineState,
    comfort: Comfort,
    now: datetime,
) -> tuple[EngineResult, EngineState]:
    """One evaluation of the house (docs/integration.md §4.3)."""
    failures: dict[str, str] = {}
    hub = state.hub
    statuses: dict[str, Status] = {}

    # 1. Regions
    region_own: dict[Direction, RegionOwn] = {}
    region_states: dict[str, RegionState] = {}
    for region_id, region in model.regions.items():
        outcome = _attempt(
            failures,
            region_id,
            partial(_evaluate_region, region, snap, state.regions.get(region_id), now),
            None,
        )
        if outcome is None:
            if region_id in state.regions:
                region_states[region_id] = state.regions[region_id]
            continue
        region_own[region.direction], region_states[region_id], found = outcome
        statuses.update(found)

    # 2. Weather offsets, before any direction resolves
    offsets = _attempt(
        failures,
        "hub/weather_offsets",
        partial(
            learn_weather_offsets, region_own, snap.weather, hub.weather_offsets, now
        ),
        hub.weather_offsets or WeatherOffsets({}),
    )

    # 3. Directions, including rooms without a side
    outdoor: dict[Direction | None, OutdoorValues] = {
        direction: _attempt(
            failures,
            f"hub/outdoor/{direction or 'none'}",
            partial(
                resolve_direction, direction, region_own, snap.weather, offsets, now
            ),
            _NO_OUTDOOR,
        )
        for direction in (*Direction, None)
    }

    # 4. House outdoor
    house_out = _attempt(
        failures,
        "hub/outdoor",
        partial(house_outdoor, region_own, snap.weather, offsets, now),
        _NO_HOUSE_OUTDOOR,
    )

    # 6. Strategy; independent of the rooms, so it runs before them
    forecast = snap.forecast
    points = forecast.points if forecast else None
    hourly = forecast.hourly if forecast else False
    observed = None if house_out.stage is Stage.WEATHER else house_out.value
    bias = _attempt(
        failures,
        "hub/forecast_bias",
        partial(update_forecast_bias, hub.forecast_bias, points, hourly, observed, now),
        hub.forecast_bias,
    )
    strategy = _attempt(
        failures,
        "hub/strategy",
        partial(
            daily_strategy,
            points,
            hourly,
            now,
            comfort.c_min,
            comfort.c_max,
            comfort.threshold,
            bias,
            hub.strategy,
        ),
        _NO_STRATEGY,
    )

    # 7. Windows, before the rooms that aggregate them
    window_levels: dict[str, WindowLevel] = {}
    window_states: dict[str, WindowState] = {}
    stores: dict[str, WindowStore] = {}
    for window_id, window in model.windows.items():
        outcome = _attempt(
            failures,
            window_id,
            partial(_evaluate_window, window, snap, state.windows.get(window_id), now),
            None,
        )
        if outcome is None:
            if window_id in state.windows:
                stores[window_id] = state.windows[window_id]
            continue
        window_levels[window_id], window_states[window_id], stores[window_id] = outcome

    # 5 and 8. Rooms
    failed_objects = [key for key in failures if key in model.regions]
    room_results: dict[str, RoomResult] = {}
    room_states: dict[str, RoomState] = {}
    for room_id, room in model.rooms.items():
        outcome = _attempt(
            failures,
            room_id,
            partial(
                _evaluate_room,
                room,
                snap,
                state.rooms.get(room_id),
                outdoor[room.side],
                strategy.strategy,
                comfort,
                model.settings,
                [
                    window_states.get(window_id, _NO_WINDOW_STATE)
                    for window_id in room.window_ids
                ],
                now,
            ),
            None,
        )
        if outcome is None:
            failed_objects.append(room_id)
            if room_id in state.rooms:
                room_states[room_id] = state.rooms[room_id]
            continue
        room_results[room_id], room_states[room_id], found = outcome
        statuses.update(found)

    # 9. Covers
    window_results: dict[str, WindowResult] = {}
    for window_id, window in model.windows.items():
        if window_id not in window_states:
            continue
        store = stores[window_id]
        room_failed = window.room_id in failed_objects
        cover_result, cover_state = _attempt(
            failures,
            f"{window_id}/cover",
            partial(
                _evaluate_cover,
                window,
                snap,
                store.cover,
                window_states[window_id],
                None if room_failed else room_results.get(window.room_id),
                outdoor[window.direction],
                strategy.strategy,
                comfort,
                now,
            ),
            (_NO_COVER, store.cover),
        )
        stores[window_id] = replace(store, cover=cover_state)
        window_results[window_id] = WindowResult(
            window_levels[window_id], window_states[window_id], cover_result
        )

    # 10. House
    reported, outage_state = _attempt(
        failures,
        "hub/outages",
        partial(outages, statuses, hub.outages, now, model.settings.repair_delay),
        ([], hub.outages),
    )
    outage_state = _carry_over_outages(outage_state, hub.outages, failed_objects)
    house = _attempt(
        failures,
        "hub/house",
        partial(
            _house_result,
            model,
            strategy,
            house_out,
            room_results,
            window_results,
            reported,
        ),
        None,
    )

    result = EngineResult(
        rooms=room_results,
        regions={
            region_id: RegionResult(
                region_own[region.direction], outdoor[region.direction]
            )
            for region_id, region in model.regions.items()
            if region.direction in region_own
        },
        windows=window_results,
        house=house,
        failures=failures,
    )
    new_state = EngineState(
        rooms=room_states,
        regions=region_states,
        windows=stores,
        hub=HubState(
            weather_offsets=offsets,
            forecast_bias=bias,
            strategy=hub.strategy if "hub/strategy" in failures else strategy.strategy,
            outages=outage_state,
        ),
    )
    return result, new_state


def _carry_over_outages(
    new: OutageState | None, previous: OutageState | None, failed: Sequence[str]
) -> OutageState | None:
    """A failed object reports no statuses: keep its running invalid-since timers."""
    if new is None or previous is None or not failed:
        return new
    prefixes = tuple(f"{object_id}/" for object_id in failed)
    carried = {
        key: since
        for key, since in previous.invalid_since.items()
        if key.startswith(prefixes) and key not in new.invalid_since
    }
    return OutageState({**new.invalid_since, **carried})


def _house_result(
    model: HouseModel,
    strategy: StrategyResult,
    house_out: HouseOutdoor,
    rooms: Mapping[str, RoomResult],
    windows: Mapping[str, WindowResult],
    reported: Sequence[Outage],
) -> HouseResult:
    """Step 10: indoor average and the "any" flags over rooms that have windows."""
    with_windows = {
        room_id: room for room_id, room in rooms.items() if room.windows is not None
    }
    close, to_close = any_cover_to_close(
        {window_id: window.cover for window_id, window in windows.items()}
    )
    return HouseResult(
        strategy=strategy,
        indoor=indoor_average([room.temperature.value for room in rooms.values()]),
        outdoor=house_out,
        any_cooling_down=any_of([room.cooling_down for room in with_windows.values()]),
        any_heating_up=any_of([room.heating_up for room in with_windows.values()]),
        any_open_while_conditioning=any_of(
            [
                room.open_while_conditioning
                for room_id, room in with_windows.items()
                if model.rooms[room_id].climate_devices
            ]
        ),
        any_cover_to_close=close,
        covers_to_close=to_close,
        outages=tuple(reported),
    )
