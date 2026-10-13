"""Table cases of docs/logic.md §6."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.climate_hub.logic.comfort import (
    Dryness,
    Position,
    Relation,
    Trend,
    TrendState,
    comfort_position,
    outside_dryness,
    outside_relation,
    trend,
)

T0 = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("t", "c_min", "c_max", "prev", "expected"),
    [
        (24.0, 20, 24, Position.WITHIN, Position.WITHIN),
        (24.1, 20, 24, Position.WITHIN, Position.ABOVE),
        (23.8, 20, 24, Position.ABOVE, Position.ABOVE),
        (23.7, 20, 24, Position.ABOVE, Position.WITHIN),
        (19.9, 20, 24, Position.WITHIN, Position.BELOW),
        (20.2, 20, 24, Position.BELOW, Position.BELOW),
        (20.3, 20, 24, Position.BELOW, Position.WITHIN),
        (22.0, 20, 24, None, Position.WITHIN),
        (22.0, 24, 20, Position.WITHIN, None),
        (None, 20, 24, Position.WITHIN, None),
    ],
)
def test_comfort_position(t, c_min, c_max, prev, expected):
    assert comfort_position(t, c_min, c_max, prev) == expected


@pytest.mark.parametrize(
    ("diff", "prev", "expected"),
    [
        (-0.4, Relation.SIMILAR, Relation.SIMILAR),
        (-0.5, Relation.SIMILAR, Relation.COLDER),
        (-0.3, Relation.COLDER, Relation.COLDER),
        (-0.25, Relation.COLDER, Relation.SIMILAR),
        (0.6, Relation.COLDER, Relation.WARMER),
        (0.3, Relation.WARMER, Relation.WARMER),
        (0.2, Relation.WARMER, Relation.SIMILAR),
        (-0.5, None, Relation.COLDER),
        (-0.3, None, Relation.SIMILAR),
    ],
)
def test_outside_relation(diff, prev, expected):
    assert outside_relation(20.0 + diff, 20.0, prev) == expected


@pytest.mark.parametrize(("t_out", "t_in"), [(None, 20.0), (5.0, None)])
def test_outside_relation_missing_input(t_out, t_in):
    assert outside_relation(t_out, t_in, Relation.COLDER) is None


@pytest.mark.parametrize(
    ("diff", "prev", "expected"),
    [
        (-0.8, Dryness.SIMILAR, Dryness.SIMILAR),
        (-1.0, Dryness.SIMILAR, Dryness.DRIER),
        (-0.6, Dryness.DRIER, Dryness.DRIER),
        (-0.5, Dryness.DRIER, Dryness.SIMILAR),
        (1.2, Dryness.DRIER, Dryness.MORE_HUMID),
        (0.6, Dryness.MORE_HUMID, Dryness.MORE_HUMID),
        (0.4, Dryness.MORE_HUMID, Dryness.SIMILAR),
        (-0.6, None, Dryness.SIMILAR),
    ],
)
def test_outside_dryness(diff, prev, expected):
    assert outside_dryness(8.0 + diff, 8.0, prev) == expected


@pytest.mark.parametrize(("ah_out", "ah_in"), [(None, 8.0), (5.0, None)])
def test_outside_dryness_missing_input(ah_out, ah_in):
    assert outside_dryness(ah_out, ah_in, Dryness.DRIER) is None


def _run(values, prev, step=timedelta(minutes=10)):
    """Feed one sample per step; `prev` applies to the last call."""
    state = TrendState()
    result = None
    for i, value in enumerate(values):
        last = i == len(values) - 1
        result, state = trend(state, value, T0 + i * step, prev if last else None)
    return result, state


@pytest.mark.parametrize(
    ("start", "step", "count", "prev", "expected"),
    [
        (21.0, 0.1, 7, Trend.STEADY, Trend.RISING),
        (21.0, 0.05, 7, Trend.RISING, Trend.RISING),
        (21.0, 0.04, 7, Trend.RISING, Trend.STEADY),
        (22.0, -0.2, 7, Trend.STEADY, Trend.FALLING),
        (21.0, 0.1, 3, Trend.RISING, None),
        (21.0, 0.05, 7, None, Trend.STEADY),
        (21.0, 0.03, 7, None, Trend.STEADY),
    ],
)
def test_trend_table(start, step, count, prev, expected):
    values = [start + i * step for i in range(count)]
    assert _run(values, prev)[0] == expected


def test_trend_without_samples_is_none():
    result, state = trend(TrendState(), None, T0, None)
    assert result is None
    assert state.samples == ()


def test_trend_none_value_adds_nothing_but_drops_old():
    state = TrendState(((T0 - timedelta(minutes=61), 20.0), (T0, 21.0)))
    result, new_state = trend(state, None, T0 + timedelta(minutes=5), Trend.RISING)
    assert result is None
    assert new_state.samples == ((T0, 21.0),)


def test_trend_at_most_one_sample_per_minute():
    _, state = trend(TrendState(), 20.0, T0, None)
    _, state = trend(state, 21.0, T0 + timedelta(seconds=59), None)
    assert len(state.samples) == 1
    _, state = trend(state, 21.0, T0 + timedelta(minutes=1), None)
    assert len(state.samples) == 2


def test_trend_drops_samples_older_than_60_minutes():
    state = TrendState(((T0, 20.0), (T0 + timedelta(minutes=1), 20.0)))
    _, kept = trend(state, 20.0, T0 + timedelta(minutes=60), None)
    assert kept.samples[0][0] == T0
    _, dropped = trend(state, 20.0, T0 + timedelta(minutes=61), None)
    assert dropped.samples[0][0] == T0 + timedelta(minutes=1)


def test_trend_does_not_mutate_input():
    state = TrendState(((T0, 20.0),))
    trend(state, 21.0, T0 + timedelta(minutes=10), None)
    assert state.samples == ((T0, 20.0),)
