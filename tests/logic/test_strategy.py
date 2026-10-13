"""Table cases of docs/logic.md §7."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from custom_components.climate_hub.logic.strategy import (
    ForecastBias,
    ForecastPoint,
    Strategy,
    daily_strategy,
    update_forecast_bias,
)

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
HEAT = Strategy.PREVENT_HEAT_UP
COOL = Strategy.PREVENT_COOL_DOWN
NEUTRAL = Strategy.NEUTRAL


def daily(f_max, f_min, now=NOW):
    return [ForecastPoint(now.replace(hour=0, minute=0), f_max, f_min)]


def hourly(temps, start=NOW):
    return [ForecastPoint(start + timedelta(hours=i), t) for i, t in enumerate(temps)]


def biased(samples, bias_max=None, bias_min=None):
    return ForecastBias(bias_max=bias_max, bias_min=bias_min, samples=samples)


@pytest.mark.parametrize(
    ("f_max", "f_min", "prev", "expected"),
    [
        (30, 19, NEUTRAL, HEAT),
        (26.0, 19, NEUTRAL, NEUTRAL),
        (25.6, 19, HEAT, HEAT),
        (25.5, 19, HEAT, NEUTRAL),
        (22, 10, NEUTRAL, COOL),
        (22, 18.4, COOL, COOL),
        (22, 18.5, COOL, NEUTRAL),
        (28, 8, NEUTRAL, HEAT),
    ],
)
def test_strategy_daily(f_max, f_min, prev, expected):
    result = daily_strategy(daily(f_max, f_min), False, NOW, 20, 24, 2, None, prev)
    assert result.strategy == expected
    assert (result.f_max, result.f_min) == (f_max, f_min)
    assert (result.corrected_f_max, result.corrected_f_min) == (f_max, f_min)


@pytest.mark.parametrize("prev", [None, NEUTRAL, HEAT, COOL])
@pytest.mark.parametrize("points", [None, []])
def test_no_forecast(points, prev):
    result = daily_strategy(points, False, NOW, 20, 24, 2, None, prev)
    assert result.strategy is None
    assert result.f_max is None


def test_daily_without_entry_for_today():
    yesterday = daily(30, 19, NOW - timedelta(days=1))
    result = daily_strategy(yesterday, False, NOW, 20, 24, 2, None, None)
    assert result.strategy is None


def test_daily_without_low_only_heat_up_applies():
    points = [ForecastPoint(NOW.replace(hour=0), 22.0)]
    result = daily_strategy(points, False, NOW, 20, 24, 2, None, COOL)
    assert result.strategy == NEUTRAL
    assert result.f_min is None
    assert result.corrected_f_min is None


def test_hourly_ignores_points_beyond_horizon():
    points = hourly([24.0] + [20.0] * 23 + [31.0])  # the 31 is at now + 24 h
    result = daily_strategy(points, True, NOW, 20, 24, 2, None, NEUTRAL)
    assert result.strategy == NEUTRAL
    assert result.f_max == 24.0


def test_hourly_ignores_points_before_now():
    points = hourly([40.0] + [20.0] * 24, NOW - timedelta(hours=1))
    result = daily_strategy(points, True, NOW, 20, 24, 2, None, None)
    assert result.f_max == 20.0


@pytest.mark.parametrize("prev", [None, NEUTRAL, HEAT, COOL])
def test_hourly_too_few_points(prev):
    points = hourly([30.0] * 8)
    assert daily_strategy(points, True, NOW, 20, 24, 2, None, prev).strategy is None


def test_hourly_enough_points():
    points = hourly([30.0] * 12)
    assert daily_strategy(points, True, NOW, 20, 24, 2, None, None).strategy == HEAT


def test_daily_date_is_local():
    # 23:00 UTC on the 12th is already the 13th at UTC+2
    now = datetime(2026, 10, 13, 8, 0, tzinfo=timezone(timedelta(hours=2)))
    points = [ForecastPoint(datetime(2026, 10, 12, 23, 0, tzinfo=UTC), 30.0, 19.0)]
    assert daily_strategy(points, False, now, 20, 24, 2, None, None).f_max == 30.0


@pytest.mark.parametrize(
    ("f_max", "f_min", "bias", "expected", "corrected"),
    [
        (25.0, 19, biased(3, bias_max=2.2), HEAT, (27.2, 19)),
        (25.0, 19, biased(2, bias_max=2.2), NEUTRAL, (25.0, 19)),
        (22, 19.0, biased(3, bias_min=-1.5), COOL, (22, 17.5)),
    ],
)
def test_bias_applied_from_three_samples(f_max, f_min, bias, expected, corrected):
    result = daily_strategy(daily(f_max, f_min), False, NOW, 20, 24, 2, bias, NEUTRAL)
    assert result.strategy == expected
    assert (result.corrected_f_max, result.corrected_f_min) == pytest.approx(corrected)
    assert (result.f_max, result.f_min) == (f_max, f_min)
    assert (result.bias_max, result.bias_min) == (bias.bias_max, bias.bias_min)


# Bias learning: one evaluation every 10 min, day after day.
DAY0 = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
TICK = timedelta(minutes=10)


def simulate(state, day, f_max, f_min, o_max, o_min, covered_h, hourly_points=True):
    """Evaluate a whole day; own-sensor values exist for `covered_h` hours."""
    start = DAY0 + timedelta(days=day)
    if hourly_points:
        points = hourly([f_max] + [f_min] * 22 + [f_max], start)
    else:
        points = daily(f_max, f_min, start)
    for i in range(144):
        observed = None
        if i * TICK < timedelta(hours=covered_h):
            observed = o_max if i == 50 else o_min if i == 51 else (o_max + o_min) / 2
        state = update_forecast_bias(
            state, points, hourly_points, observed, start + i * TICK
        )
    return state


def close(state, day, next_f_max=0.0, next_f_min=0.0):
    """First evaluation of the day after `day`: closes `day`, stores the next one."""
    start = DAY0 + timedelta(days=day + 1)
    points = daily(next_f_max, next_f_min, start)
    return update_forecast_bias(state, points, False, None, start)


def test_bias_learning_table():
    s = simulate(None, 0, 28.0, 15.0, 30.5, 14.0, 23.9)
    s = close(s, 0, 26.0, 15.0)
    assert (s.bias_max, s.samples) == (2.5, 1)
    s = simulate(s, 1, 26.0, 15.0, 27.5, 14.0, 24)
    s = close(s, 1, 30.0, 15.0)
    assert (s.bias_max, s.samples) == (pytest.approx(2.25), 2)
    s = simulate(s, 2, 30.0, 15.0, 32.0, 14.0, 24)
    s = close(s, 2, 25.0, 15.0)
    assert (s.bias_max, s.samples) == (pytest.approx(2.1875), 3)
    # day 4: coverage only 17 h, no sample
    s = simulate(s, 3, 25.0, 15.0, 29.0, 14.0, 17)
    assert s.covered < timedelta(hours=18)
    s = close(s, 3)
    assert (s.bias_max, s.samples) == (pytest.approx(2.1875), 3)


def test_restart_at_noon_stores_no_forecast_and_gives_no_sample():
    s = ForecastBias(bias_max=2.1875, bias_min=-1.0, samples=3, day=DAY0.date())
    noon = DAY0 + timedelta(days=1, hours=12)
    points = hourly([20.0] * 36, noon)
    s = update_forecast_bias(s, points, True, 20.0, noon)
    assert s.day_f_max is None and s.day_f_min is None
    for i in range(1, 72):
        s = update_forecast_bias(s, points, True, 27.0, noon + i * TICK)
    assert s.covered == timedelta(hours=11, minutes=50)
    s = update_forecast_bias(s, None, False, None, DAY0 + timedelta(days=2))
    assert (s.bias_max, s.bias_min, s.samples) == (2.1875, -1.0, 3)


def test_bias_clamped():
    s = simulate(None, 0, 20.0, 15.0, 29.0, 14.0, 24)
    s = close(s, 0)
    assert (s.bias_max, s.samples) == (5.0, 1)


def test_bias_min_works_the_same_way():
    s = simulate(None, 0, 28.0, 15.0, 28.0, 12.0, 24, hourly_points=False)
    s = close(s, 0, 28.0, 15.0)
    assert (s.bias_min, s.samples) == (-3.0, 1)
    s = simulate(s, 1, 28.0, 15.0, 28.0, 14.0, 24, hourly_points=False)
    s = close(s, 1)
    assert s.bias_min == pytest.approx(-3.0 + 0.25 * (-1.0 + 3.0))


def test_coverage_steps_are_capped_and_skip_missing_values():
    s = update_forecast_bias(None, daily(25, 15), False, 20.0, NOW)
    assert s.covered == timedelta(0)
    s = update_forecast_bias(s, None, False, 21.0, NOW + timedelta(hours=1))
    assert s.covered == timedelta(minutes=10)
    s = update_forecast_bias(s, None, False, None, NOW + timedelta(hours=2))
    assert s.covered == timedelta(minutes=10)
    assert (s.obs_max, s.obs_min) == (21.0, 21.0)


def test_input_state_is_not_mutated():
    s = ForecastBias(day=NOW.date(), last_at=NOW)
    update_forecast_bias(s, None, False, 20.0, NOW + TICK)
    assert s == ForecastBias(day=NOW.date(), last_at=NOW)
