"""Per-source readings, spread and setpoint deviation of a room
(docs/logic.md §16; R16, R17).
"""

import re
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from . import const
from .recommendation import ClimateDevice
from .sources import Candidate, Status

_SPLIT = re.compile(r"[\s_\-]+")
_CLIMATE_PREFIX = "climate."


def tokens(text: str) -> list[str]:
    """Split at runs of whitespace, `_` and `-`, without empty tokens."""
    return [t for t in _SPLIT.split(text) if t]


def _is_metric_word(token: str, metric_words: Collection[str]) -> bool:
    folded = token.casefold()
    return any(
        folded == word
        or (len(folded) >= const.LABEL_PREFIX_MIN and word.startswith(folded))
        for word in metric_words
    )


def _label(
    full_name: str, area_words: Collection[str], metric_words: Collection[str]
) -> str:
    kept = [
        t
        for t in tokens(full_name)
        if t.casefold() not in area_words and not _is_metric_word(t, metric_words)
    ]
    if not kept:
        return full_name.strip()
    label = " ".join(kept)
    return label[0].upper() + label[1:] if label[0].islower() else label


def labels(
    names: Sequence[tuple[str, str]],
    area_words: Collection[str],
    metric_words: Collection[str],
) -> dict[str, str]:
    """Short label per entity: the name without area and metric words (R16).

    `names` are (entity ID, full name) pairs in rank order. A label that several
    entities share falls back to their full names; a full name that is still shared
    falls back to the entity ID."""
    areas = {w.casefold() for w in area_words}
    metrics = [w.casefold() for w in metric_words]
    full = {entity_id: name.strip() for entity_id, name in names}
    short = {entity_id: _label(name, areas, metrics) for entity_id, name in names}
    short_counts = Counter(short.values())
    named = {
        entity_id: full[entity_id] if short_counts[label] > 1 else label
        for entity_id, label in short.items()
    }
    named_counts = Counter(named.values())
    return {
        entity_id: entity_id if named_counts[label] > 1 else label
        for entity_id, label in named.items()
    }


def spread(candidates: Sequence[Candidate]) -> float | None:
    """Largest minus smallest fresh value of a room's sources (R16).

    A radiator thermostat measures at the radiator, not in a zone of the room, so
    `climate.*` sources only count when the room has fewer than two other sources."""
    sensors = [c for c in candidates if not c.entity_id.startswith(_CLIMATE_PREFIX)]
    pool = sensors if len(sensors) >= 2 else candidates
    values = [c.value for c in pool if c.status is Status.OK and c.value is not None]
    if len(values) < 2:
        return None
    return max(values) - min(values)


@dataclass(frozen=True, slots=True)
class Setpoint:
    device: str | None  # entity ID of the device whose setpoint counts
    low: float | None  # equal to `high` for a single setpoint
    high: float | None
    deviation: float | None  # room temperature minus setpoint; 0 inside a range


def setpoint_deviation(
    t_room: float | None, devices: Sequence[tuple[str, ClimateDevice]]
) -> Setpoint:
    """Deviation of the room temperature from the first regulating device's setpoint."""
    for entity_id, device in devices:
        if device.hvac_mode not in const.REGULATING_MODES:
            continue
        if device.target is not None:
            low = high = device.target
        elif device.target_low is not None and device.target_high is not None:
            low = min(device.target_low, device.target_high)
            high = max(device.target_low, device.target_high)
        else:
            continue
        if t_room is None:
            deviation = None
        elif t_room > high:
            deviation = t_room - high
        elif t_room < low:
            deviation = t_room - low
        else:
            deviation = 0.0
        return Setpoint(entity_id, low, high, deviation)
    return Setpoint(None, None, None, None)
