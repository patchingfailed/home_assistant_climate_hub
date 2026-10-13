"""Window contacts to opening level, debounce, open since, room (docs/logic.md §8).

Covers W2-W12: contact mapping, the level rules for frames and pass-throughs, the
5 s debounce, the "open since" timestamp and the room aggregation.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum

from .const import CONTACT_DEBOUNCE

_NO_VALUE = frozenset({"", "unavailable", "unknown"})


class Level(IntEnum):
    CLOSED = 0
    AJAR = 1
    TILTED = 2
    OPEN = 3


class OpenLeaves(StrEnum):
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    UNKNOWN = "unknown"


class ContactKind(StrEnum):
    BINARY = "binary"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class FrameConfig:
    """One leaf (single window) or two (double leaf) plus optional refiners."""

    leaves: tuple[str, ...]
    tilt: str | None = None
    handle: str | None = None


@dataclass(frozen=True, slots=True)
class PassThroughConfig:
    """Two openings in series, one contact each (W5)."""

    inner: str
    outer: str


type WindowConfig = FrameConfig | PassThroughConfig


@dataclass(frozen=True, slots=True)
class WindowLevel:
    level: Level | None
    open_leaves: OpenLeaves | None
    implausible: bool


@dataclass(frozen=True, slots=True)
class Debounced:
    """Debounce state; `ventilating_since` is the raw start of ventilation."""

    raw: Level | None
    raw_since: datetime
    published: Level | None
    ventilating_since: datetime | None


@dataclass(frozen=True, slots=True)
class WindowState:
    level: Level | None
    ventilating: bool | None
    open_since: datetime | None


@dataclass(frozen=True, slots=True)
class RoomWindows:
    level: Level | None
    ventilating: bool | None
    open_since: datetime | None


def _normalise(text: str) -> str:
    return text.strip().casefold()


def contact_level(
    raw: str | None,
    kind: ContactKind,
    mapping: Mapping[Level, frozenset[str]] | None,
) -> Level | None:
    """Level of one contact state (W2); `None` for no value or an unmapped text."""
    if raw is None:
        return None
    state = _normalise(raw)
    if state in _NO_VALUE:
        return None
    if kind is ContactKind.BINARY:
        if state == "on":
            return Level.OPEN
        return Level.CLOSED if state == "off" else None
    for level, texts in (mapping or {}).items():
        if any(_normalise(text) == state for text in texts):
            return level
    return None


def suggest_text_mapping(
    texts: Iterable[str], words: Mapping[Level, frozenset[str]]
) -> Mapping[Level, frozenset[str]]:
    """Pre-assign known texts that match a default word of a level (S8d)."""
    suggestion: dict[Level, set[str]] = {level: set() for level in Level}
    for text in texts:
        for level, level_words in words.items():
            if _normalise(text) in {_normalise(word) for word in level_words}:
                suggestion[level].add(text)
                break
    return {level: frozenset(found) for level, found in suggestion.items()}


def ventilating(level: Level | None, min_level: Level = Level.TILTED) -> bool | None:
    """Whether a level ventilates (W3); `None` for an unknown level."""
    return None if level is None else level >= min_level


def _leaf_level(leaves: Sequence[Level | None]) -> Level | None:
    known = [level for level in leaves if level is not None]
    if len(known) == len(leaves):
        return max(known)
    # A moving leaf is certain, anything less could hide the unknown one (D9).
    top = max(known, default=None)
    return top if top is not None and top >= Level.TILTED else None


def _open_leaves(
    leaves: Sequence[Level | None], level: Level | None, implausible: bool
) -> OpenLeaves | None:
    if len(leaves) != 2 or level is None:
        return None
    if implausible:
        return OpenLeaves.UNKNOWN
    left, right = (leaf is not None and leaf > Level.AJAR for leaf in leaves)
    if left and right:
        return OpenLeaves.BOTH
    if left:
        return OpenLeaves.LEFT
    if right:
        return OpenLeaves.RIGHT
    return OpenLeaves.NONE if None not in leaves else OpenLeaves.UNKNOWN


def _frame_level(
    config: FrameConfig, levels: Mapping[str, Level | None]
) -> WindowLevel:
    leaves = [levels.get(entity_id) for entity_id in config.leaves]
    level = _leaf_level(leaves)
    tilt = levels.get(config.tilt) if config.tilt else None
    implausible = False
    if tilt is Level.OPEN:
        moved = any(leaf is not None and leaf > Level.AJAR for leaf in leaves)
        implausible = None not in leaves and not moved
        level = Level.OPEN
    elif tilt is Level.CLOSED and level is Level.OPEN:
        level = Level.TILTED
    handle = levels.get(config.handle) if config.handle else None
    if level is Level.CLOSED and handle is not None and handle > Level.CLOSED:
        level = Level.AJAR
    return WindowLevel(level, _open_leaves(leaves, level, implausible), implausible)


def _pass_through_level(
    config: PassThroughConfig, levels: Mapping[str, Level | None]
) -> Level | None:
    inner, outer = levels.get(config.inner), levels.get(config.outer)
    if inner is None or outer is None:
        # No air path through a closed opening, otherwise unknown.
        return Level.CLOSED if Level.CLOSED in (inner, outer) else None
    return min(inner, outer)


def window_level(
    config: WindowConfig, levels: Mapping[str, Level | None]
) -> WindowLevel:
    """Opening level of one window from its contacts' levels (W4-W6, W8, W12)."""
    if isinstance(config, PassThroughConfig):
        return WindowLevel(_pass_through_level(config, levels), None, False)
    return _frame_level(config, levels)


def debounce(
    raw: Level | None,
    prev: Debounced | None,
    now: datetime,
    min_level: Level = Level.TILTED,
) -> Debounced:
    """Publish the raw level once it has been unchanged for 5 s (W10)."""
    if prev is None:
        return Debounced(raw, now, raw, None)
    raw_since = prev.raw_since if raw == prev.raw else now
    published = raw if now - raw_since >= CONTACT_DEBOUNCE else prev.published
    since = prev.ventilating_since
    if raw is not None and raw < min_level:
        since = None
    elif raw is not None and since is None and not ventilating(prev.raw, min_level):
        since = now
    return Debounced(raw, raw_since, published, since)


def open_since(
    debounced: Debounced,
    min_level: Level,
    prev: datetime | None,
    startup_hint: datetime | None,
) -> datetime | None:
    """Raw time the window started ventilating (W7, D10); `prev` is persisted.

    Kept while the published level ventilates or is unknown, cleared otherwise.
    Without a persisted value after a restart the contacts' `startup_hint` is used.
    """
    active = ventilating(debounced.published, min_level)
    if active is None:
        return prev
    if not active:
        return None
    for known in (prev, debounced.ventilating_since, startup_hint):
        if known is not None:
            return known
    return debounced.raw_since


def room_windows(windows: Sequence[WindowState]) -> RoomWindows:
    """Aggregate a room's windows (W9)."""
    levels = [window.level for window in windows if window.level is not None]
    flags = [window.ventilating for window in windows]
    if True in flags:
        any_ventilating: bool | None = True
    else:
        any_ventilating = False if None not in flags else None
    level = max(levels, default=None)
    if len(levels) < len(windows) and any_ventilating is not True:
        level = None
    since = [w.open_since for w in windows if w.ventilating and w.open_since]
    return RoomWindows(level, any_ventilating, min(since, default=None))
