"""Ventilation recommendation, warnings, open while conditioning (docs/logic.md §9).

One evaluation per room: data check, humidity guard (D8), thermal goal (A2, D5, D6),
humidity goal (A3, A6, D7), closed reasons, then the mapping on the window state.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .comfort import Dryness, Position, Relation, Trend
from .const import BURST_PAUSE, HUMIDITY_RELEASE, PRE_COOL_START
from .psychro import humidity_after_ventilating
from .strategy import Strategy

_ACTIVE_ACTIONS = frozenset({"heating", "preheating", "cooling", "drying"})
_ACTIVE_MODES = frozenset({"heat", "cool", "heat_cool", "auto", "dry"})


class Recommendation(StrEnum):
    OPEN = "open"
    KEEP_OPEN = "keep_open"
    CLOSE = "close"
    KEEP_CLOSED = "keep_closed"
    NONE = "none"


class Reason(StrEnum):
    COOL_ROOM = "cool_room"
    PRE_COOL = "pre_cool"
    WARM_ROOM = "warm_room"
    DRY_ROOM = "dry_room"
    BURST_DRY = "burst_dry"
    BURST_DONE = "burst_done"
    OUTSIDE_COLDER = "outside_colder"
    OUTSIDE_WARMER = "outside_warmer"
    OUTSIDE_HUMID = "outside_humid"
    IN_RANGE = "in_range"
    NO_BENEFIT = "no_benefit"
    NO_DATA = "no_data"
    COMFORT_RANGE_INVALID = "comfort_range_invalid"


class Goal(StrEnum):
    COOL = "cool"
    WARM = "warm"
    DRY = "dry"
    BURST = "burst"
    BURST_DONE = "burst_done"


_HUMIDITY_GOALS = frozenset({Goal.DRY, Goal.BURST, Goal.BURST_DONE})


@dataclass(frozen=True, slots=True)
class GoalState:
    """Per room (persisted). `pause_until` blocks the next burst."""

    goal: Goal | None = None
    started_at: datetime | None = None
    pause_until: datetime | None = None
    humid_guard: bool = False


@dataclass(frozen=True, slots=True)
class RoomInput:
    t_in: float | None
    rh_in: float | None
    t_out: float | None
    dew_point_out: float | None
    c_min: float
    c_max: float
    position: Position | None
    relation: Relation | None
    dryness: Dryness | None
    trend: Trend | None
    strategy: Strategy | None
    has_windows: bool
    ventilating: bool | None
    ventilating_since: datetime | None
    humidity_threshold: float
    burst_duration: timedelta


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    recommendation: Recommendation
    reason: Reason
    wanted_open: bool | None
    humidity_after_ventilating: float | None


@dataclass(frozen=True, slots=True)
class ClimateDevice:
    hvac_action: str | None
    hvac_mode: str | None


def _outside_colder_harm(inp: RoomInput) -> bool:
    return inp.relation == Relation.COLDER and (
        inp.strategy == Strategy.PREVENT_COOL_DOWN or inp.position == Position.BELOW
    )


def _outside_warmer_harm(inp: RoomInput) -> bool:
    return inp.relation == Relation.WARMER and (
        inp.strategy == Strategy.PREVENT_HEAT_UP or inp.position == Position.ABOVE
    )


def _guard(rh_after: float | None, threshold: float, engaged: bool) -> bool:
    """Humidity guard hysteresis (D8)."""
    if rh_after is None:
        return False
    if rh_after >= threshold:
        return True
    if rh_after < threshold - HUMIDITY_RELEASE:
        return False
    return engaged


def _thermal_goal(inp: RoomInput, t_in: float, prev: Goal | None) -> Goal | None:
    """Continue the previous thermal goal, else start one (A2, A6, D5, D6)."""
    heat_up_day = inp.strategy == Strategy.PREVENT_HEAT_UP
    middle = (inp.c_min + inp.c_max) / 2
    target = inp.c_min if heat_up_day else middle
    if prev == Goal.COOL and t_in > target and inp.relation == Relation.COLDER:
        return Goal.COOL
    if prev == Goal.WARM and t_in < middle and inp.relation == Relation.WARMER:
        return Goal.WARM
    if inp.relation == Relation.COLDER and (
        inp.position == Position.ABOVE
        or (heat_up_day and t_in >= inp.c_min + PRE_COOL_START)
    ):
        return Goal.COOL
    if inp.relation == Relation.WARMER and inp.position == Position.BELOW:
        return Goal.WARM
    return None


def _humidity_goal(
    inp: RoomInput, state: GoalState, now: datetime
) -> tuple[Goal | None, datetime | None, datetime | None]:
    """Humidity goal transition (A3, A6, D7): (goal, started_at, pause_until)."""
    goal = state.goal if state.goal in _HUMIDITY_GOALS else None
    started_at, pause_until = state.started_at, state.pause_until
    if inp.rh_in is None or inp.dryness is None:
        return None, None, pause_until

    drier = inp.dryness == Dryness.DRIER
    harm = _outside_colder_harm(inp) or _outside_warmer_harm(inp)

    if goal is None:
        pause_running = pause_until is not None and now < pause_until
        if inp.rh_in > inp.humidity_threshold and drier and not pause_running:
            return (Goal.BURST if harm else Goal.DRY), now, pause_until
        return None, None, pause_until
    if not (inp.rh_in > inp.humidity_threshold - HUMIDITY_RELEASE and drier):
        return None, None, pause_until

    if goal == Goal.DRY:
        if harm:
            return Goal.BURST, now, pause_until
        return goal, started_at, pause_until
    if not harm:
        return Goal.DRY, started_at, pause_until
    if goal == Goal.BURST:
        clock = inp.ventilating_since if inp.has_windows else started_at
        if clock is None or now - clock < inp.burst_duration:
            return goal, started_at, pause_until
        if not inp.has_windows:
            pause_until = clock + inp.burst_duration + BURST_PAUSE
        return Goal.BURST_DONE, started_at, pause_until
    # BURST_DONE: wait for the pause (it starts once the window is closed), then burst
    if pause_until is None:
        if inp.has_windows and inp.ventilating is False:
            pause_until = now + BURST_PAUSE
    elif now >= pause_until:
        return Goal.BURST, now, None
    return goal, started_at, pause_until


def _closed_reason(inp: RoomInput, blocked: bool) -> Reason:
    """Why the window stays closed when no goal wants it open (step 5)."""
    if blocked:
        return Reason.OUTSIDE_HUMID
    if _outside_colder_harm(inp):
        return Reason.OUTSIDE_COLDER
    if _outside_warmer_harm(inp):
        return Reason.OUTSIDE_WARMER
    if inp.position == Position.WITHIN:
        return Reason.IN_RANGE
    return Reason.NO_BENEFIT


def _map_window(wanted_open: bool, ventilating: bool | None) -> Recommendation:
    if wanted_open:
        return Recommendation.KEEP_OPEN if ventilating else Recommendation.OPEN
    if ventilating is False:
        return Recommendation.KEEP_CLOSED
    return Recommendation.CLOSE


def recommend(
    inp: RoomInput, prev: GoalState | None, now: datetime
) -> tuple[RecommendationResult, GoalState]:
    """Recommendation for one room and the new goal state (steps 1 to 6)."""
    state = prev or GoalState()
    if inp.t_in is None or inp.t_out is None:
        none = RecommendationResult(Recommendation.NONE, Reason.NO_DATA, None, None)
        return none, state
    if inp.c_min >= inp.c_max:
        none = RecommendationResult(
            Recommendation.NONE, Reason.COMFORT_RANGE_INVALID, None, None
        )
        return none, state

    rh_after = (
        None
        if inp.dew_point_out is None
        else humidity_after_ventilating(inp.t_in, inp.dew_point_out)
    )
    guard = _guard(rh_after, inp.humidity_threshold, state.humid_guard)

    thermal = _thermal_goal(inp, inp.t_in, state.goal)
    blocked = thermal is not None and guard
    if blocked:
        thermal = None

    if thermal is not None:
        started_at = state.started_at if state.goal == thermal else now
        new = GoalState(thermal, started_at, state.pause_until, guard)
        wanted_open = True
        if thermal == Goal.WARM:
            reason = Reason.WARM_ROOM
        elif inp.strategy == Strategy.PREVENT_HEAT_UP:
            reason = Reason.PRE_COOL
        else:
            reason = Reason.COOL_ROOM
    else:
        goal, started_at, pause_until = _humidity_goal(inp, state, now)
        new = GoalState(goal, started_at, pause_until, guard)
        wanted_open = goal in (Goal.DRY, Goal.BURST)
        if goal == Goal.BURST_DONE:
            reason = Reason.BURST_DONE
        elif goal == Goal.BURST:
            reason = Reason.BURST_DRY
        elif goal == Goal.DRY:
            reason = Reason.DRY_ROOM
        else:
            reason = _closed_reason(inp, blocked)

    result = RecommendationResult(
        _map_window(wanted_open, inp.ventilating), reason, wanted_open, rh_after
    )
    return result, new


def _ventilating_long_enough(
    ventilating: bool | None,
    ventilating_since: datetime | None,
    burst_duration: timedelta,
    now: datetime,
) -> bool | None:
    if ventilating is None:
        return None
    return (
        ventilating
        and ventilating_since is not None
        and now - ventilating_since >= burst_duration
    )


def warnings(
    *,
    strategy: Strategy | None,
    relation: Relation | None,
    trend: Trend | None,
    ventilating: bool | None,
    ventilating_since: datetime | None,
    wanted_open: bool | None,
    burst_duration: timedelta,
    now: datetime,
) -> tuple[bool | None, bool | None]:
    """(cooling down, heating up) warnings of one room (A4, D12)."""
    long_enough = _ventilating_long_enough(
        ventilating, ventilating_since, burst_duration, now
    )
    if long_enough is None:
        return None, None
    unwanted = long_enough and wanted_open is not True
    cooling_down = (
        unwanted
        and strategy == Strategy.PREVENT_COOL_DOWN
        and relation == Relation.COLDER
    )
    heating_up = (
        unwanted
        and strategy == Strategy.PREVENT_HEAT_UP
        and (relation == Relation.WARMER or trend == Trend.RISING)
    )
    return cooling_down, heating_up


def _device_active(device: ClimateDevice) -> bool:
    if device.hvac_action is not None:
        return device.hvac_action in _ACTIVE_ACTIONS
    return device.hvac_mode in _ACTIVE_MODES


def open_while_conditioning(
    *,
    devices: tuple[ClimateDevice, ...],
    ventilating: bool | None,
    ventilating_since: datetime | None,
    burst_duration: timedelta,
    now: datetime,
) -> bool | None:
    """Window ventilates beyond the burst time while a device is active (A12)."""
    long_enough = _ventilating_long_enough(
        ventilating, ventilating_since, burst_duration, now
    )
    if long_enough is None:
        return None
    return long_enough and any(_device_active(d) for d in devices)
