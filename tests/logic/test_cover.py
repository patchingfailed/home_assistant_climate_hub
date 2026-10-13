"""Table cases of docs/logic.md section 10."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.climate_hub.logic.comfort import Position, comfort_position
from custom_components.climate_hub.logic.cover import (
    CoverAdvice,
    CoverInput,
    CoverPosition,
    CoverReason,
    CoverResult,
    CoverState,
    CoverWanted,
    any_cover_to_close,
    cover,
    cover_position,
    facing_azimuth,
)
from custom_components.climate_hub.logic.outdoor import Direction
from custom_components.climate_hub.logic.strategy import Strategy
from custom_components.climate_hub.logic.window import Level

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
HEAT, COOL, NEUTRAL = (
    Strategy.PREVENT_HEAT_UP,
    Strategy.PREVENT_COOL_DOWN,
    Strategy.NEUTRAL,
)
A, R = CoverAdvice, CoverReason


def make_input(**overrides) -> CoverInput:
    values = {
        "has_room": True,
        "sun_azimuth": 180.0,
        "sun_elevation": 40.0,
        "clouds": 20.0,
        "facing": 180.0,
        "t_room": 22.0,
        "c_min": 20.0,
        "c_max": 24.0,
        "t_out": 25.0,
        "strategy": NEUTRAL,
        "window_level": Level.CLOSED,
        "cover": None,
        **overrides,
    }
    if "position" not in overrides:
        values["position"] = comfort_position(
            values["t_room"], values["c_min"], values["c_max"], None
        )
    return CoverInput(**values)


@pytest.mark.parametrize(
    ("overrides", "advice", "reason"),
    [
        ({"strategy": HEAT}, A.CLOSE, R.SUN_HEAT),
        (
            {"strategy": HEAT, "cover": CoverPosition.CLOSED},
            A.KEEP_CLOSED,
            R.SUN_HEAT,
        ),
        ({"strategy": HEAT, "cover": CoverPosition.UNKNOWN}, A.CLOSE, R.SUN_HEAT),
        ({"strategy": HEAT, "window_level": Level.TILTED}, A.CLOSE, R.SUN_HEAT),
        ({"strategy": HEAT, "window_level": Level.OPEN}, A.NONE, R.WINDOW_OPEN),
        (
            {"sun_azimuth": 90.0, "clouds": 0.0, "strategy": HEAT},
            A.CLOSE,
            R.HEAT_BARRIER,
        ),
        (
            {"sun_azimuth": 90.0, "clouds": 0.0, "strategy": HEAT, "t_out": 20.0},
            A.OPEN,
            R.NO_SUN,
        ),
        (
            {
                "sun_azimuth": 245.0,
                "sun_elevation": 30.0,
                "cover": CoverPosition.NOT_CLOSED,
            },
            A.KEEP_OPEN,
            R.NO_SUN,
        ),
        ({"sun_elevation": 8.0, "clouds": 0.0}, A.OPEN, R.NO_SUN),
        ({"clouds": 90.0}, A.OPEN, R.NO_SUN),
        ({}, A.OPEN, R.NO_HEAT_RISK),
        ({"t_room": 23.6}, A.CLOSE, R.SUN_HEAT),
        ({"strategy": HEAT, "t_room": 19.5}, A.OPEN, R.SOLAR_GAIN),
        ({"t_room": 23.6, "t_out": 15.0}, A.OPEN, R.SOLAR_GAIN),
        (
            {
                "sun_azimuth": 350.0,
                "sun_elevation": 15.0,
                "clouds": 0.0,
                "facing": 0.0,
                "strategy": HEAT,
            },
            A.CLOSE,
            R.SUN_HEAT,
        ),
        (
            {"sun_elevation": -10.0, "strategy": COOL, "t_room": 21.0, "t_out": 5.0},
            A.CLOSE,
            R.INSULATE,
        ),
        (
            {
                "sun_elevation": -10.0,
                "strategy": COOL,
                "t_room": 21.0,
                "t_out": 5.0,
                "cover": CoverPosition.CLOSED,
            },
            A.KEEP_CLOSED,
            R.INSULATE,
        ),
        (
            {"sun_elevation": -10.0, "t_room": 19.5, "t_out": 10.0},
            A.CLOSE,
            R.INSULATE,
        ),
        ({"sun_elevation": -10.0, "t_room": 22.0, "t_out": 15.0}, A.NONE, R.NIGHT),
        (
            {"sun_elevation": -10.0, "strategy": HEAT, "t_room": 25.0, "t_out": 18.0},
            A.NONE,
            R.NIGHT,
        ),
        ({"sun_azimuth": None, "sun_elevation": None}, A.NONE, R.NO_DATA),
        ({"t_room": None}, A.NONE, R.NO_DATA),
        ({"has_room": False}, A.NONE, R.NO_ROOM),
        ({"t_out": None}, A.OPEN, R.NO_HEAT_RISK),
    ],
)
def test_cover_cases(overrides, advice, reason):
    result, _ = cover(make_input(**overrides), None, NOW)
    assert result == CoverResult(advice, reason)


def test_hold_keeps_closed_until_fifteen_minutes():
    t10 = NOW.replace(hour=10, minute=0)
    result, state = cover(make_input(t_room=23.6), None, t10)
    assert result == CoverResult(A.CLOSE, R.SUN_HEAT)
    assert state.wanted == CoverWanted.CLOSED
    assert state.since == t10

    gone = make_input(t_room=23.6, sun_elevation=5.0)
    result, held = cover(gone, state, t10 + timedelta(minutes=10))
    assert result == CoverResult(A.CLOSE, R.SUN_HEAT)
    assert held.since == t10

    result, released = cover(gone, held, t10 + timedelta(minutes=15))
    assert result == CoverResult(A.OPEN, R.NO_SUN)
    assert released.wanted == CoverWanted.OPEN
    assert released.since == t10 + timedelta(minutes=15)


def test_changes_to_and_from_none_are_immediate():
    t10 = NOW.replace(hour=10)
    _, state = cover(make_input(t_room=23.6), None, t10)
    soon = t10 + timedelta(minutes=1)
    blocked = make_input(t_room=23.6, window_level=Level.OPEN)
    result, guarded = cover(blocked, state, soon)
    assert result == CoverResult(A.NONE, R.WINDOW_OPEN)
    assert guarded.wanted is None
    result, _ = cover(make_input(t_room=23.6), guarded, soon)
    assert result == CoverResult(A.CLOSE, R.SUN_HEAT)


def test_open_window_guard_applies_to_a_held_state():
    t10 = NOW.replace(hour=10)
    _, state = cover(make_input(t_room=23.6), None, t10)
    door_open = make_input(t_room=23.6, sun_elevation=5.0, window_level=Level.OPEN)
    result, guarded = cover(door_open, state, t10 + timedelta(minutes=5))
    assert result == CoverResult(A.NONE, R.WINDOW_OPEN)
    assert guarded.wanted is None


def test_same_wanted_new_reason_updates_reason_keeps_since():
    t10 = NOW.replace(hour=10)
    _, state = cover(make_input(t_room=23.6), None, t10)
    later = t10 + timedelta(minutes=5)
    result, new = cover(make_input(strategy=HEAT, sun_elevation=5.0), state, later)
    assert result == CoverResult(A.CLOSE, R.HEAT_BARRIER)
    assert new.since == t10


def test_heat_risk_hysteresis():
    inp = make_input(t_room=23.2, position=Position.WITHIN)
    result, state = cover(inp, None, NOW)
    assert result.reason == R.NO_HEAT_RISK
    assert not state.heat_risk
    _, risk = cover(make_input(t_room=23.5), state, NOW)
    assert risk.heat_risk
    result, kept = cover(inp, CoverState(heat_risk=True), NOW)
    assert kept.heat_risk
    assert result.reason == R.SUN_HEAT
    _, released = cover(make_input(t_room=22.9), CoverState(heat_risk=True), NOW)
    assert not released.heat_risk


@pytest.mark.parametrize(
    ("direction", "exact", "expected"),
    [
        (Direction.N, None, 0),
        (Direction.E, None, 90),
        (Direction.S, None, 180),
        (Direction.W, None, 270),
        (Direction.S, 215.0, 215.0),
    ],
)
def test_facing_azimuth(direction, exact, expected):
    assert facing_azimuth(direction, exact) == expected


@pytest.mark.parametrize(
    ("state", "position", "expected"),
    [
        ("open", 100, CoverPosition.NOT_CLOSED),
        ("open", 50, CoverPosition.CLOSED),
        ("open", 51, CoverPosition.NOT_CLOSED),
        ("closed", 0, CoverPosition.CLOSED),
        ("closed", None, CoverPosition.CLOSED),
        ("open", None, CoverPosition.NOT_CLOSED),
        ("opening", 30, CoverPosition.UNKNOWN),
        ("closing", None, CoverPosition.UNKNOWN),
        ("unavailable", None, CoverPosition.UNKNOWN),
        ("unknown", 0, CoverPosition.UNKNOWN),
        (None, None, CoverPosition.UNKNOWN),
    ],
)
def test_cover_position(state, position, expected):
    assert cover_position(state, position) == expected


def test_any_cover_to_close():
    results = {
        "south": CoverResult(A.CLOSE, R.SUN_HEAT),
        "north": CoverResult(A.OPEN, R.NO_SUN),
        "east": CoverResult(A.KEEP_CLOSED, R.INSULATE),
        "west": CoverResult(A.NONE, R.NIGHT),
    }
    assert any_cover_to_close(results) == (
        True,
        (("south", R.SUN_HEAT), ("east", R.INSULATE)),
    )
    assert any_cover_to_close({"north": results["north"]}) == (False, ())
    assert any_cover_to_close({}) == (False, ())
