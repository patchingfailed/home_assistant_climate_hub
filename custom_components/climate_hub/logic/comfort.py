"""Comfort position, outside relation and dryness, temperature trend (docs/logic.md §6).

Every state is a hysteresis band: entered at the enter threshold, kept until the exit
threshold is crossed. `prev` of `None` (start-up) uses the enter thresholds only.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .const import (
    DRYNESS_ENTER,
    DRYNESS_EXIT,
    POSITION_HYSTERESIS,
    RELATION_ENTER,
    RELATION_EXIT,
    TREND_ENTER,
    TREND_EXIT,
    TREND_MIN_SPAN,
    TREND_SAMPLE_INTERVAL,
    TREND_WINDOW,
)


class Position(StrEnum):
    BELOW = "below"
    WITHIN = "within"
    ABOVE = "above"


class Relation(StrEnum):
    COLDER = "colder"
    SIMILAR = "similar"
    WARMER = "warmer"


class Dryness(StrEnum):
    DRIER = "drier"
    SIMILAR = "similar"
    MORE_HUMID = "more_humid"


class Trend(StrEnum):
    FALLING = "falling"
    STEADY = "steady"
    RISING = "rising"


@dataclass(frozen=True, slots=True)
class TrendState:
    """Temperature samples of the last `TREND_WINDOW`, oldest first (persisted)."""

    samples: tuple[tuple[datetime, float], ...] = ()


def _band[S: StrEnum](
    diff: float, enter: float, exit_: float, prev: S | None, low: S, mid: S, high: S
) -> S:
    """Three-state hysteresis on a signed difference."""
    if diff <= -enter or (prev == low and diff < -exit_):
        return low
    if diff >= enter or (prev == high and diff > exit_):
        return high
    return mid


def comfort_position(
    t: float | None, c_min: float, c_max: float, prev: Position | None
) -> Position | None:
    """Position of the room temperature against the comfort range (rule 1)."""
    if t is None or c_min >= c_max:
        return None
    if t > c_max or (prev == Position.ABOVE and t > c_max - POSITION_HYSTERESIS):
        return Position.ABOVE
    if t < c_min or (prev == Position.BELOW and t < c_min + POSITION_HYSTERESIS):
        return Position.BELOW
    return Position.WITHIN


def outside_relation(
    t_out: float | None, t_in: float | None, prev: Relation | None
) -> Relation | None:
    """Outside temperature compared to inside (rule 2)."""
    if t_out is None or t_in is None:
        return None
    return _band(
        t_out - t_in,
        RELATION_ENTER,
        RELATION_EXIT,
        prev,
        Relation.COLDER,
        Relation.SIMILAR,
        Relation.WARMER,
    )


def outside_dryness(
    ah_out: float | None, ah_in: float | None, prev: Dryness | None
) -> Dryness | None:
    """Outside absolute humidity compared to inside (rule 3)."""
    if ah_out is None or ah_in is None:
        return None
    return _band(
        ah_out - ah_in,
        DRYNESS_ENTER,
        DRYNESS_EXIT,
        prev,
        Dryness.DRIER,
        Dryness.SIMILAR,
        Dryness.MORE_HUMID,
    )


def _slope(samples: tuple[tuple[datetime, float], ...]) -> float:
    """Least-squares slope in K/h."""
    xs = [(at - samples[0][0]).total_seconds() / 3600 for at, _ in samples]
    ys = [value for _, value in samples]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    sxx = sum((x - x_mean) ** 2 for x in xs)
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    return sxy / sxx


def trend(
    state: TrendState, t: float | None, now: datetime, prev: Trend | None
) -> tuple[Trend | None, TrendState]:
    """Temperature trend over the last hour with its updated samples (rule 4)."""
    samples = tuple(s for s in state.samples if now - s[0] <= TREND_WINDOW)
    if t is not None and (not samples or now - samples[-1][0] >= TREND_SAMPLE_INTERVAL):
        samples += ((now, t),)
    new_state = TrendState(samples)
    if t is None or len(samples) < 2 or samples[-1][0] - samples[0][0] < TREND_MIN_SPAN:
        return None, new_state
    slope = _slope(samples)
    result = _band(
        slope,
        TREND_ENTER,
        TREND_EXIT,
        prev,
        Trend.FALLING,
        Trend.STEADY,
        Trend.RISING,
    )
    return result, new_state
