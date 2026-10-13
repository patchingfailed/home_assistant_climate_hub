"""Cover recommendation per window (docs/logic.md §10).

Recommends what to do with a window's cover; it never moves one. The wanted state is
held for `COVER_HOLD` before it flips between closed and open (rule 7).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .comfort import Position, Relation, outside_relation
from .const import (
    COVER_CLOSED_POSITION,
    COVER_HOLD,
    HEAT_RISK_ENTER,
    HEAT_RISK_EXIT,
    NIGHT_ELEVATION,
    SUN_MAX_ANGLE,
    SUN_MAX_CLOUDS,
    SUN_MIN_ELEVATION,
)
from .outdoor import Direction
from .strategy import Strategy
from .window import Level

_DIRECTION_AZIMUTH = {
    Direction.N: 0.0,
    Direction.E: 90.0,
    Direction.S: 180.0,
    Direction.W: 270.0,
}
_UNKNOWN_STATES = frozenset({"opening", "closing", "unavailable", "unknown"})


class CoverAdvice(StrEnum):
    CLOSE = "close"
    KEEP_CLOSED = "keep_closed"
    OPEN = "open"
    KEEP_OPEN = "keep_open"
    NONE = "none"


class CoverReason(StrEnum):
    SUN_HEAT = "sun_heat"
    HEAT_BARRIER = "heat_barrier"
    INSULATE = "insulate"
    SOLAR_GAIN = "solar_gain"
    NO_HEAT_RISK = "no_heat_risk"
    NO_SUN = "no_sun"
    NIGHT = "night"
    WINDOW_OPEN = "window_open"
    NO_DATA = "no_data"
    NO_ROOM = "no_room"


class CoverWanted(StrEnum):
    CLOSED = "closed"
    OPEN = "open"


class CoverPosition(StrEnum):
    CLOSED = "closed"
    NOT_CLOSED = "not_closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CoverInput:
    has_room: bool
    sun_azimuth: float | None
    sun_elevation: float | None
    clouds: float | None
    facing: float
    t_room: float | None
    c_min: float
    c_max: float
    position: Position | None
    t_out: float | None
    strategy: Strategy | None
    window_level: Level | None
    cover: CoverPosition | None


@dataclass(frozen=True, slots=True)
class CoverState:
    """Persisted per window; `since` is when the current wanted state began."""

    wanted: CoverWanted | None = None
    reason: CoverReason | None = None
    since: datetime | None = None
    relation: Relation | None = None
    heat_risk: bool = False


@dataclass(frozen=True, slots=True)
class CoverResult:
    advice: CoverAdvice
    reason: CoverReason


def facing_azimuth(direction: Direction, exact: float | None) -> float:
    """Facing of a window: exact degrees if given, else the compass side (SH4)."""
    return exact if exact is not None else _DIRECTION_AZIMUTH[direction]


def cover_position(state: str | None, current_position: float | None) -> CoverPosition:
    """Cover state from its entity state and position (rule 8)."""
    if state in _UNKNOWN_STATES or (state is None and current_position is None):
        return CoverPosition.UNKNOWN
    if current_position is not None:
        closed = current_position <= COVER_CLOSED_POSITION
    else:
        closed = state == "closed"
    return CoverPosition.CLOSED if closed else CoverPosition.NOT_CLOSED


def _raw_wanted(
    inp: CoverInput, relation: Relation | None, heat_risk: bool
) -> tuple[CoverWanted | None, CoverReason]:
    """Wanted cover state and reason before guard and hold (rules 1, 3-5)."""
    if not inp.has_room:
        return None, CoverReason.NO_ROOM
    if inp.sun_azimuth is None or inp.sun_elevation is None or inp.t_room is None:
        return None, CoverReason.NO_DATA
    gain_welcome = inp.position == Position.BELOW or (
        inp.t_out is not None and inp.t_out < inp.c_min
    )
    if inp.sun_elevation < NIGHT_ELEVATION:
        if relation == Relation.COLDER and (
            inp.strategy == Strategy.PREVENT_COOL_DOWN or inp.position == Position.BELOW
        ):
            return CoverWanted.CLOSED, CoverReason.INSULATE
        return None, CoverReason.NIGHT
    angle = abs((inp.sun_azimuth - inp.facing + 180) % 360 - 180)
    sun_on_window = (
        inp.sun_elevation >= SUN_MIN_ELEVATION
        and angle <= SUN_MAX_ANGLE
        and (inp.clouds is None or inp.clouds <= SUN_MAX_CLOUDS)
    )
    if sun_on_window and gain_welcome:
        return CoverWanted.OPEN, CoverReason.SOLAR_GAIN
    if sun_on_window and heat_risk:
        return CoverWanted.CLOSED, CoverReason.SUN_HEAT
    if (
        inp.strategy == Strategy.PREVENT_HEAT_UP
        and relation == Relation.WARMER
        and not gain_welcome
    ):
        return CoverWanted.CLOSED, CoverReason.HEAT_BARRIER
    if sun_on_window:
        return CoverWanted.OPEN, CoverReason.NO_HEAT_RISK
    return CoverWanted.OPEN, CoverReason.NO_SUN


def _hold(
    wanted: CoverWanted | None,
    reason: CoverReason,
    prev: CoverState | None,
    now: datetime,
) -> tuple[CoverWanted | None, CoverReason, datetime]:
    """Keep the previous wanted state until it was held for `COVER_HOLD` (rule 7)."""
    if prev is None or prev.since is None or prev.reason is None:
        return wanted, reason, now
    if wanted == prev.wanted:
        return wanted, reason, prev.since
    if wanted is None or prev.wanted is None or now - prev.since >= COVER_HOLD:
        return wanted, reason, now
    return prev.wanted, prev.reason, prev.since


def _advice(wanted: CoverWanted | None, cover: CoverPosition | None) -> CoverAdvice:
    """Map the wanted state to advice by the cover state (rule 8)."""
    if wanted == CoverWanted.CLOSED:
        closed = cover == CoverPosition.CLOSED
        return CoverAdvice.KEEP_CLOSED if closed else CoverAdvice.CLOSE
    if wanted == CoverWanted.OPEN:
        not_closed = cover == CoverPosition.NOT_CLOSED
        return CoverAdvice.KEEP_OPEN if not_closed else CoverAdvice.OPEN
    return CoverAdvice.NONE


def cover(
    inp: CoverInput, prev: CoverState | None, now: datetime
) -> tuple[CoverResult, CoverState]:
    """Cover advice and reason for one window (SH1, SH2, SH4, D16)."""
    relation = outside_relation(inp.t_out, inp.t_room, prev.relation if prev else None)
    heat_risk = inp.t_room is not None and (
        inp.t_room >= inp.c_max - HEAT_RISK_ENTER
        or (
            prev is not None
            and prev.heat_risk
            and inp.t_room >= inp.c_max - HEAT_RISK_EXIT
        )
    )
    wanted, reason = _raw_wanted(
        inp, relation, inp.strategy == Strategy.PREVENT_HEAT_UP or heat_risk
    )
    wanted, reason, since = _hold(wanted, reason, prev, now)
    # After the hold: a held "closed" must not lock someone out either (rule 6).
    if wanted == CoverWanted.CLOSED and inp.window_level == Level.OPEN:
        wanted, reason, since = None, CoverReason.WINDOW_OPEN, now
    state = CoverState(wanted, reason, since, relation, heat_risk)
    return CoverResult(_advice(wanted, inp.cover), reason), state


def any_cover_to_close(
    results: Mapping[str, CoverResult],
) -> tuple[bool, tuple[tuple[str, CoverReason], ...]]:
    """True if any window wants its cover closed, with those windows (rule 9)."""
    closing = tuple(
        (window, result.reason)
        for window, result in results.items()
        if result.advice in (CoverAdvice.CLOSE, CoverAdvice.KEEP_CLOSED)
    )
    return bool(closing), closing
