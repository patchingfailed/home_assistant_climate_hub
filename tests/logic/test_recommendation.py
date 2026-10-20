"""Table cases of docs/logic.md §9."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.climate_hub.logic.comfort import (
    Dryness,
    Position,
    Relation,
    Trend,
    comfort_position,
    outside_dryness,
    outside_relation,
)
from custom_components.climate_hub.logic.psychro import absolute_humidity, dew_point
from custom_components.climate_hub.logic.recommendation import (
    ClimateDevice,
    Goal,
    GoalState,
    Reason,
    Recommendation,
    RoomInput,
    open_while_conditioning,
    recommend,
    warnings,
)
from custom_components.climate_hub.logic.strategy import Strategy

R = Recommendation
G = Goal
S = Strategy
BURST = timedelta(minutes=10)
D0 = datetime(2026, 10, 13, tzinfo=UTC)


def at(hour: int, minute: int = 0) -> datetime:
    return D0.replace(hour=hour, minute=minute)


def room(
    *,
    t_in: float | None,
    t_out: float | None,
    rh_in: float = 50.0,
    rh_out: float = 50.0,
    strategy: Strategy | None = S.NEUTRAL,
    c_min: float = 20.0,
    c_max: float = 24.0,
    has_windows: bool = True,
    has_side: bool = True,
    ventilating: bool | None = False,
    ventilating_since: datetime | None = None,
    trend: Trend | None = Trend.STEADY,
    prev_states: tuple | None = None,
) -> tuple[RoomInput, tuple]:
    """Room input with position, relation and dryness derived like the adapter."""
    prev_pos, prev_rel, prev_dry = prev_states or (None, None, None)
    position = comfort_position(t_in, c_min, c_max, prev_pos)
    relation = outside_relation(t_out, t_in, prev_rel)
    if t_in is None or t_out is None:
        dew, dryness = None, None
    else:
        dew = dew_point(t_out, rh_out)
        dryness = outside_dryness(
            absolute_humidity(t_out, rh_out), absolute_humidity(t_in, rh_in), prev_dry
        )
    inp = RoomInput(
        t_in=t_in,
        rh_in=rh_in,
        t_out=t_out,
        dew_point_out=dew,
        c_min=c_min,
        c_max=c_max,
        position=position,
        relation=relation,
        dryness=dryness,
        trend=trend,
        strategy=strategy,
        has_windows=has_windows,
        has_side=has_side,
        ventilating=ventilating if has_windows else None,
        ventilating_since=ventilating_since,
        humidity_threshold=60.0,
        burst_duration=BURST,
    )
    return inp, (position, relation, dryness)


def test_scenario_11_neutral_day():
    state = None
    comfort = None
    rows = [
        (at(10, 0), 24.6, False, None, R.OPEN, Reason.COOL_ROOM, G.COOL),
        (at(10, 10), 24.4, True, at(10, 1), R.KEEP_OPEN, Reason.COOL_ROOM, G.COOL),
        (at(10, 40), 23.9, True, at(10, 1), R.KEEP_OPEN, Reason.COOL_ROOM, G.COOL),
        (at(11, 20), 22.0, True, at(10, 1), R.CLOSE, Reason.IN_RANGE, None),
        (at(11, 30), 22.3, False, None, R.KEEP_CLOSED, Reason.IN_RANGE, None),
    ]
    for now, t_in, vent, since, rec, reason, goal in rows:
        inp, comfort_new = room(
            t_in=t_in,
            t_out=19.0,
            ventilating=vent,
            ventilating_since=since,
            prev_states=comfort,
        )
        result, state = recommend(inp, state, now)
        comfort = comfort_new
        assert (result.recommendation, result.reason, state.goal) == (rec, reason, goal)


def test_scenario_11_alternative_continues_from_1040():
    state = GoalState(G.COOL, at(10, 0))
    prev = (Position.ABOVE, Relation.COLDER, Dryness.SIMILAR)
    inp, _ = room(
        t_in=23.0,
        t_out=22.9,
        ventilating=True,
        ventilating_since=at(10, 1),
        prev_states=prev,
    )
    result, state = recommend(inp, state, at(11, 0))
    assert (result.recommendation, result.reason, state.goal) == (
        R.CLOSE,
        Reason.IN_RANGE,
        None,
    )


def test_scenario_9_bathroom_burst():
    state = None
    comfort = None
    pause = at(8, 13)
    # time, RH in, ventilating, since, recommendation, reason, goal, pause, cooling-down
    rows = [
        (at(7, 0), 68, False, None, R.OPEN, Reason.BURST_DRY, G.BURST, None, False),
        (
            at(7, 2),
            67,
            True,
            at(7, 2),
            R.KEEP_OPEN,
            Reason.BURST_DRY,
            G.BURST,
            None,
            False,
        ),
        (
            at(7, 11),
            63,
            True,
            at(7, 2),
            R.KEEP_OPEN,
            Reason.BURST_DRY,
            G.BURST,
            None,
            False,
        ),
        (
            at(7, 12),
            62,
            True,
            at(7, 2),
            R.CLOSE,
            Reason.BURST_DONE,
            G.BURST_DONE,
            None,
            True,
        ),
        (
            at(7, 13),
            62,
            False,
            None,
            R.KEEP_CLOSED,
            Reason.BURST_DONE,
            G.BURST_DONE,
            pause,
            False,
        ),
        (
            at(8, 0),
            63,
            False,
            None,
            R.KEEP_CLOSED,
            Reason.BURST_DONE,
            G.BURST_DONE,
            pause,
            False,
        ),
        (at(8, 13), 63, False, None, R.OPEN, Reason.BURST_DRY, G.BURST, None, False),
        (
            at(8, 40),
            55,
            False,
            None,
            R.KEEP_CLOSED,
            Reason.OUTSIDE_COLDER,
            None,
            None,
            False,
        ),
    ]
    for now, rh_in, vent, since, rec, reason, goal, pause_until, cooling in rows:
        inp, comfort_new = room(
            t_in=21.0,
            t_out=3.0,
            rh_in=rh_in,
            rh_out=85.0,
            strategy=S.PREVENT_COOL_DOWN,
            ventilating=vent,
            ventilating_since=since,
            prev_states=comfort,
        )
        result, state = recommend(inp, state, now)
        comfort = comfort_new
        assert (result.recommendation, result.reason, state.goal) == (rec, reason, goal)
        assert state.pause_until == pause_until
        cooling_down, heating_up = warnings(
            strategy=inp.strategy,
            relation=inp.relation,
            trend=inp.trend,
            ventilating=inp.ventilating,
            ventilating_since=inp.ventilating_since,
            wanted_open=result.wanted_open,
            burst_duration=BURST,
            now=now,
        )
        assert (cooling_down, heating_up) == (cooling, False)


def test_scenario_9_dry_outside_air_is_drier():
    assert absolute_humidity(3.0, 85.0) == pytest.approx(5.05, abs=0.01)
    assert absolute_humidity(21.0, 68.0) == pytest.approx(12.43, abs=0.01)


GOAL_DRY = GoalState(G.DRY, at(9, 0))
GOAL_COOL = GoalState(G.COOL, at(9, 0))

OTHER_CASES = [
    # id, strategy, t_in, ventilating, rh_in, t_out, rh_out, before, rec, reason
    (
        1,
        S.PREVENT_COOL_DOWN,
        21.0,
        False,
        50,
        5,
        80,
        None,
        R.KEEP_CLOSED,
        Reason.OUTSIDE_COLDER,
    ),
    (2, S.PREVENT_COOL_DOWN, 25.0, False, 50, 5, 80, None, R.OPEN, Reason.COOL_ROOM),
    (3, S.PREVENT_HEAT_UP, 22.0, False, 50, 16, 70, None, R.OPEN, Reason.PRE_COOL),
    (4, S.PREVENT_HEAT_UP, 20.0, True, 50, 16, 70, GOAL_COOL, R.CLOSE, Reason.IN_RANGE),
    (
        5,
        S.PREVENT_HEAT_UP,
        22.0,
        True,
        50,
        28,
        40,
        None,
        R.CLOSE,
        Reason.OUTSIDE_WARMER,
    ),
    (6, S.NEUTRAL, 19.0, False, 50, 23, 40, None, R.OPEN, Reason.WARM_ROOM),
    (7, S.NEUTRAL, 19.0, False, 50, 10, 70, None, R.KEEP_CLOSED, Reason.OUTSIDE_COLDER),
    (8, S.NEUTRAL, 25.0, False, 50, 27, 40, None, R.KEEP_CLOSED, Reason.OUTSIDE_WARMER),
    (9, S.NEUTRAL, 25.0, False, 50, 24.8, 50, None, R.KEEP_CLOSED, Reason.NO_BENEFIT),
    (10, S.NEUTRAL, 22.0, False, 65, 21.8, 40, None, R.OPEN, Reason.DRY_ROOM),
    (11, S.NEUTRAL, 22.0, True, 58, 21.8, 40, GOAL_DRY, R.KEEP_OPEN, Reason.DRY_ROOM),
    (12, S.NEUTRAL, 22.0, True, 55, 21.8, 40, GOAL_DRY, R.CLOSE, Reason.IN_RANGE),
    (13, S.NEUTRAL, 20.0, False, 65, 24, 70, None, R.KEEP_CLOSED, Reason.IN_RANGE),
    (14, S.NEUTRAL, 19.9, False, 65, 24, 70, None, R.KEEP_CLOSED, Reason.OUTSIDE_HUMID),
    (18, None, 24.6, False, 50, 19, 70, None, R.OPEN, Reason.COOL_ROOM),
    # A2: heat-up day, room below the comfort range, outside warmer: warming wanted
    ("A2", S.PREVENT_HEAT_UP, 19.0, False, 50, 23, 40, None, R.OPEN, Reason.WARM_ROOM),
]


@pytest.mark.parametrize(
    ("strategy", "t_in", "vent", "rh_in", "t_out", "rh_out", "before", "rec", "reason"),
    [c[1:] for c in OTHER_CASES],
    ids=[f"case{c[0]}" for c in OTHER_CASES],
)
def test_other_cases(strategy, t_in, vent, rh_in, t_out, rh_out, before, rec, reason):
    inp, _ = room(
        t_in=t_in,
        t_out=t_out,
        rh_in=rh_in,
        rh_out=rh_out,
        strategy=strategy,
        ventilating=vent,
        ventilating_since=at(8, 0) if vent else None,
    )
    result, _ = recommend(inp, before, at(9, 30))
    assert (result.recommendation, result.reason) == (rec, reason)


def test_case_14_reports_humidity_after_ventilating():
    inp, _ = room(t_in=19.9, t_out=24.0, rh_in=65, rh_out=70)
    result, _ = recommend(inp, None, at(9, 0))
    assert result.humidity_after_ventilating == pytest.approx(89.9, abs=0.1)


@pytest.mark.parametrize(
    ("strategy", "t_in", "t_out", "rh_out", "rec"),
    [
        (S.NEUTRAL, 24.6, 19.0, 70, R.OPEN),  # case 15
        (S.PREVENT_COOL_DOWN, 21.0, 5.0, 80, R.CLOSE),  # case 16
    ],
    ids=["case15", "case16"],
)
def test_no_windows_only_open_or_close(strategy, t_in, t_out, rh_out, rec):
    inp, _ = room(
        t_in=t_in, t_out=t_out, rh_out=rh_out, strategy=strategy, has_windows=False
    )
    result, _ = recommend(inp, None, at(9, 0))
    assert result.recommendation == rec


@pytest.mark.parametrize("prev", [None, GOAL_COOL])
def test_case_17_no_data_keeps_goal_state(prev):
    inp, _ = room(t_in=22.0, t_out=None)
    result, state = recommend(inp, prev, at(9, 0))
    assert (result.recommendation, result.reason) == (R.NONE, Reason.NO_DATA)
    assert result.wanted_open is None
    assert state == (prev or GoalState())


@pytest.mark.parametrize("prev", [None, GOAL_COOL])
def test_room_without_side_has_its_own_reason(prev):
    """Structural, so it wins over missing values and the comfort range."""
    for t_out in (19.0, None):
        inp, _ = room(t_in=22.0, t_out=t_out, rh_out=70, has_side=False)
        result, state = recommend(inp, prev, at(9, 0))
        assert (result.recommendation, result.reason) == (R.NONE, Reason.NO_SIDE)
        assert result.wanted_open is None
        assert state == (prev or GoalState())


def test_case_19_comfort_range_invalid():
    inp, _ = room(t_in=22.0, t_out=19.0, rh_out=70, c_min=24.0, c_max=20.0)
    result, state = recommend(inp, GOAL_COOL, at(9, 0))
    assert (result.recommendation, result.reason) == (
        R.NONE,
        Reason.COMFORT_RANGE_INVALID,
    )
    assert state == GOAL_COOL


def test_case_14_guard_ends_cooling_before_the_middle():
    state, comfort = None, None
    t_in, step = 26.0, 0
    outcomes = []
    while t_in > 20.0:
        inp, comfort = room(
            t_in=t_in, t_out=20.0, rh_out=70, ventilating=False, prev_states=comfort
        )
        result, state = recommend(inp, state, at(9, 0) + timedelta(minutes=step))
        outcomes.append((t_in, result))
        t_in -= 0.5
        step += 10
    _, first = outcomes[0]
    assert (first.recommendation, first.reason) == (R.OPEN, Reason.COOL_ROOM)
    assert first.humidity_after_ventilating == pytest.approx(48.7, abs=0.1)
    ended = next((t, r) for t, r in outcomes if r.reason == Reason.OUTSIDE_HUMID)
    assert ended[0] > 22.0
    assert ended[1].recommendation == R.KEEP_CLOSED
    at_22 = next(r for t, r in outcomes if t == 22.0)
    assert at_22.humidity_after_ventilating == pytest.approx(61.9, abs=0.1)
    assert state.goal is None
    assert state.humid_guard


def test_no_windows_burst_clock_from_goal_start_pause_from_burst_end():
    kwargs = {
        "t_in": 21.0,
        "t_out": 3.0,
        "rh_out": 85.0,
        "strategy": S.PREVENT_COOL_DOWN,
        "has_windows": False,
    }
    start = at(7, 0)
    inp, _ = room(rh_in=68, **kwargs)
    result, state = recommend(inp, None, start)
    assert (result.recommendation, result.reason) == (R.OPEN, Reason.BURST_DRY)
    assert state == GoalState(G.BURST, start)

    result, state = recommend(inp, state, at(7, 9))
    assert (result.recommendation, result.reason) == (R.OPEN, Reason.BURST_DRY)

    result, state = recommend(inp, state, at(7, 10))
    assert (result.recommendation, result.reason) == (R.CLOSE, Reason.BURST_DONE)
    assert state.goal == G.BURST_DONE
    assert state.pause_until == at(8, 10)

    result, state = recommend(inp, state, at(8, 9))
    assert result.reason == Reason.BURST_DONE

    result, state = recommend(inp, state, at(8, 10))
    assert (result.recommendation, result.reason) == (R.OPEN, Reason.BURST_DRY)
    assert state == GoalState(G.BURST, at(8, 10))


def test_pause_blocks_restart_after_goal_ended():
    inp, _ = room(
        t_in=21.0,
        t_out=3.0,
        rh_in=68,
        rh_out=85.0,
        strategy=S.PREVENT_COOL_DOWN,
        ventilating=False,
    )
    pause = GoalState(None, None, at(8, 13))
    result, state = recommend(inp, pause, at(8, 0))
    assert (result.recommendation, result.reason) == (
        R.KEEP_CLOSED,
        Reason.OUTSIDE_COLDER,
    )
    assert state.pause_until == at(8, 13)
    result, _ = recommend(inp, pause, at(8, 13))
    assert result.reason == Reason.BURST_DRY


def test_new_burst_after_an_expired_pause_gets_its_own_pause():
    kwargs = dict(
        t_in=21.0, t_out=3.0, rh_in=68, rh_out=85.0, strategy=S.PREVENT_COOL_DOWN
    )
    expired = GoalState(None, None, at(8, 13))
    inp, _ = room(ventilating=False, **kwargs)
    result, state = recommend(inp, expired, at(9, 0))
    assert (result.reason, state.goal, state.pause_until) == (
        Reason.BURST_DRY,
        G.BURST,
        None,
    )
    inp, _ = room(ventilating=True, ventilating_since=at(9, 2), **kwargs)
    result, state = recommend(inp, state, at(9, 12))
    assert result.reason == Reason.BURST_DONE
    inp, _ = room(ventilating=False, **kwargs)
    result, state = recommend(inp, state, at(9, 13))
    assert (result.recommendation, result.reason) == (
        R.KEEP_CLOSED,
        Reason.BURST_DONE,
    )
    assert state.pause_until == at(10, 13)


def test_dry_goal_turns_into_burst_when_it_becomes_harmful():
    inp, _ = room(
        t_in=21.0,
        t_out=3.0,
        rh_in=68,
        rh_out=85.0,
        strategy=S.PREVENT_COOL_DOWN,
        ventilating=True,
        ventilating_since=at(7, 0),
    )
    result, state = recommend(inp, GoalState(G.DRY, at(6, 0)), at(7, 5))
    assert (result.recommendation, result.reason) == (R.KEEP_OPEN, Reason.BURST_DRY)
    assert state.goal == G.BURST


def test_missing_humidity_ends_humidity_goal_and_keeps_pause():
    inp, _ = room(t_in=22.0, t_out=21.8, rh_out=40)
    inp_no_rh = replace(inp, rh_in=None)
    prev = GoalState(G.BURST_DONE, at(7, 0), at(8, 0))
    _, state = recommend(inp_no_rh, prev, at(7, 30))
    assert state.goal is None
    assert state.pause_until == at(8, 0)


def test_thermal_start_replaces_humidity_goal_and_keeps_pause():
    inp, _ = room(t_in=25.0, t_out=19.0, ventilating=False)
    prev = GoalState(G.BURST_DONE, at(7, 0), at(8, 0))
    result, state = recommend(inp, prev, at(7, 30))
    assert (result.recommendation, result.reason) == (R.OPEN, Reason.COOL_ROOM)
    assert state == GoalState(G.COOL, at(7, 30), at(8, 0))


def test_burst_waits_for_ventilation_to_start_with_windows():
    inp, _ = room(
        t_in=21.0,
        t_out=3.0,
        rh_in=68,
        rh_out=85.0,
        strategy=S.PREVENT_COOL_DOWN,
        ventilating=None,
    )
    result, state = recommend(inp, GoalState(G.BURST, at(7, 0)), at(9, 0))
    assert result.reason == Reason.BURST_DRY
    assert state.goal == G.BURST


WARNING_CASES = [
    (S.PREVENT_COOL_DOWN, Relation.COLDER, Trend.STEADY, 12, False, True, False),
    (S.PREVENT_COOL_DOWN, Relation.COLDER, Trend.STEADY, 8, False, False, False),
    (S.PREVENT_COOL_DOWN, Relation.COLDER, Trend.STEADY, 30, True, False, False),
    (S.PREVENT_HEAT_UP, Relation.WARMER, Trend.STEADY, 15, False, False, True),
    (S.PREVENT_HEAT_UP, Relation.COLDER, Trend.RISING, 15, False, False, True),
    (S.PREVENT_HEAT_UP, Relation.COLDER, Trend.RISING, 15, True, False, False),
    (S.NEUTRAL, Relation.COLDER, Trend.STEADY, 60, False, False, False),
]


@pytest.mark.parametrize(
    ("strategy", "relation", "trend", "minutes", "wanted", "cooling", "heating"),
    WARNING_CASES,
)
def test_warnings(strategy, relation, trend, minutes, wanted, cooling, heating):
    now = at(12, 0)
    result = warnings(
        strategy=strategy,
        relation=relation,
        trend=trend,
        ventilating=True,
        ventilating_since=now - timedelta(minutes=minutes),
        wanted_open=wanted,
        burst_duration=BURST,
        now=now,
    )
    assert result == (cooling, heating)


@pytest.mark.parametrize(
    ("ventilating", "expected"), [(False, (False, False)), (None, (None, None))]
)
def test_warnings_without_ventilation(ventilating, expected):
    result = warnings(
        strategy=S.PREVENT_COOL_DOWN,
        relation=Relation.COLDER,
        trend=Trend.RISING,
        ventilating=ventilating,
        ventilating_since=None,
        wanted_open=False,
        burst_duration=BURST,
        now=at(12, 0),
    )
    assert result == expected


def test_warnings_wanted_none_counts_as_not_open():
    result = warnings(
        strategy=S.PREVENT_COOL_DOWN,
        relation=Relation.COLDER,
        trend=Trend.STEADY,
        ventilating=True,
        ventilating_since=at(11, 0),
        wanted_open=None,
        burst_duration=BURST,
        now=at(12, 0),
    )
    assert result == (True, False)


IDLE = ClimateDevice("idle", None)


@pytest.mark.parametrize(
    ("devices", "ventilating", "minutes", "expected"),
    [
        ((ClimateDevice("heating", None),), True, 12, True),
        ((IDLE,), True, 12, False),
        ((ClimateDevice(None, "heat"),), True, 12, True),
        ((ClimateDevice(None, "off"),), True, 12, False),
        ((ClimateDevice("heating", None),), True, 5, False),
        ((ClimateDevice(None, None), IDLE), True, 12, False),
        ((ClimateDevice("cooling", None),), None, 0, None),
        ((ClimateDevice("cooling", None),), False, 0, False),
    ],
    ids=[
        "heating",
        "idle",
        "mode-heat",
        "mode-off",
        "too-short",
        "unavailable-and-idle",
        "ventilating-unknown",
        "not-ventilating",
    ],
)
def test_open_while_conditioning(devices, ventilating, minutes, expected):
    now = at(12, 0)
    result = open_while_conditioning(
        devices=devices,
        ventilating=ventilating,
        ventilating_since=now - timedelta(minutes=minutes) if ventilating else None,
        burst_duration=BURST,
        now=now,
    )
    assert result is expected
