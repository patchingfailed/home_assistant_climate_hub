"""Daily strategy from the forecast and the learned forecast bias (docs/logic.md §7).

The strategy is a hysteresis on the expected daily maximum and minimum. The bias
learns the difference between the house's own outdoor sensors and the forecast.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import StrEnum

from .const import (
    BIAS_CLAMP,
    BIAS_COVERAGE_STEP_CAP,
    BIAS_MIN_COVERAGE,
    BIAS_MIN_DAY_POINTS,
    BIAS_MIN_SAMPLES,
    BIAS_WEIGHT,
    FORECAST_HORIZON,
    FORECAST_MIN_POINTS,
    STRATEGY_HYSTERESIS,
)


class Strategy(StrEnum):
    PREVENT_HEAT_UP = "prevent_heat_up"
    PREVENT_COOL_DOWN = "prevent_cool_down"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """Hourly: temperature. Daily: temperature is the high, `temp_low` the low."""

    start: datetime
    temperature: float
    temp_low: float | None = None


@dataclass(frozen=True, slots=True)
class ForecastBias:
    """Learned observed - forecast, plus the running day (persisted)."""

    bias_max: float | None = None
    bias_min: float | None = None
    samples: int = 0
    day: date | None = None
    day_f_max: float | None = None
    day_f_min: float | None = None
    obs_max: float | None = None
    obs_min: float | None = None
    covered: timedelta = timedelta(0)
    last_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StrategyResult:
    strategy: Strategy | None
    f_max: float | None
    f_min: float | None
    corrected_f_max: float | None
    corrected_f_min: float | None
    bias_max: float | None
    bias_min: float | None


def _local_date(point: ForecastPoint, now: datetime) -> date:
    return point.start.astimezone(now.tzinfo).date()


def _horizon_extremes(
    points: Sequence[ForecastPoint], hourly: bool, now: datetime
) -> tuple[float, float | None] | None:
    """Raw (f_max, f_min) of the next 24 h (hourly) or of today (daily), or None."""
    if hourly:
        temps = [
            p.temperature for p in points if now <= p.start < now + FORECAST_HORIZON
        ]
        if len(temps) < FORECAST_MIN_POINTS:
            return None
        return max(temps), min(temps)
    today = now.date()
    for p in points:
        if _local_date(p, now) == today:
            return p.temperature, p.temp_low
    return None


def _day_forecast(
    points: Sequence[ForecastPoint] | None, hourly: bool, now: datetime
) -> tuple[float | None, float | None]:
    """Forecast extremes for the local date of `now` (rule 7), or (None, None)."""
    if not points:
        return None, None
    today = now.date()
    if hourly:
        temps = [p.temperature for p in points if _local_date(p, now) == today]
        if len(temps) < BIAS_MIN_DAY_POINTS:
            return None, None
        return max(temps), min(temps)
    for p in points:
        if _local_date(p, now) == today:
            return p.temperature, p.temp_low
    return None, None


def _learn(
    bias: float | None, forecast: float | None, observed: float | None
) -> tuple[float | None, bool]:
    """Move the bias by one sample, clamped; unchanged without a sample."""
    if forecast is None or observed is None:
        return bias, False
    sample = observed - forecast
    new = sample if bias is None else bias + BIAS_WEIGHT * (sample - bias)
    return max(-BIAS_CLAMP, min(BIAS_CLAMP, new)), True


def update_forecast_bias(
    state: ForecastBias | None,
    points: Sequence[ForecastPoint] | None,
    hourly: bool,
    observed: float | None,
    now: datetime,
) -> ForecastBias:
    """Track the day and learn the bias (A14, D15, rule 7).

    `observed` is the house outdoor temperature from the regions' own sensors,
    None when it comes from the weather stage or is missing.
    """
    state = state or ForecastBias()
    today = now.date()
    if state.day == today:
        if observed is None:
            return replace(state, last_at=now)
        step = (
            min(now - state.last_at, BIAS_COVERAGE_STEP_CAP)
            if state.last_at is not None
            else timedelta(0)
        )
        return replace(
            state,
            obs_max=observed if state.obs_max is None else max(state.obs_max, observed),
            obs_min=observed if state.obs_min is None else min(state.obs_min, observed),
            covered=state.covered + step,
            last_at=now,
        )

    bias_max, bias_min, samples = state.bias_max, state.bias_min, state.samples
    if state.day is not None and state.covered >= BIAS_MIN_COVERAGE:
        bias_max, got_max = _learn(bias_max, state.day_f_max, state.obs_max)
        bias_min, got_min = _learn(bias_min, state.day_f_min, state.obs_min)
        samples += got_max or got_min
    f_max, f_min = _day_forecast(points, hourly, now)
    return ForecastBias(
        bias_max=bias_max,
        bias_min=bias_min,
        samples=samples,
        day=today,
        day_f_max=f_max,
        day_f_min=f_min,
        last_at=now,
    )


def _beyond(value: float, limit: float, kept: bool, above: bool) -> bool:
    """Enter beyond `limit`; when `kept`, stay until 0.5 inside of it."""
    margin = STRATEGY_HYSTERESIS if kept else 0.0
    return value > limit - margin if above else value < limit + margin


def daily_strategy(
    points: Sequence[ForecastPoint] | None,
    hourly: bool,
    now: datetime,
    c_min: float,
    c_max: float,
    threshold: float,
    bias: ForecastBias | None,
    prev: Strategy | None,
) -> StrategyResult:
    """Strategy with hysteresis on the bias-corrected forecast (rules 1-6)."""
    extremes = _horizon_extremes(points, hourly, now) if points else None
    bias_max = bias.bias_max if bias else None
    bias_min = bias.bias_min if bias else None
    if extremes is None:
        return StrategyResult(None, None, None, None, None, bias_max, bias_min)
    f_max, f_min = extremes
    applied = bias is not None and bias.samples >= BIAS_MIN_SAMPLES
    c_f_max = f_max + (bias_max or 0.0) if applied else f_max
    c_f_min = f_min + (bias_min or 0.0) if applied and f_min is not None else f_min
    if _beyond(c_f_max, c_max + threshold, prev == Strategy.PREVENT_HEAT_UP, True):
        strategy = Strategy.PREVENT_HEAT_UP
    elif c_f_min is not None and _beyond(
        c_f_min, c_min - threshold, prev == Strategy.PREVENT_COOL_DOWN, False
    ):
        strategy = Strategy.PREVENT_COOL_DOWN
    else:
        strategy = Strategy.NEUTRAL
    return StrategyResult(strategy, f_max, f_min, c_f_max, c_f_min, bias_max, bias_min)
