"""Source resolution and offset learning (docs/logic.md §4; R2, R4, R5, R7, R8)."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from . import const


class Status(StrEnum):
    """Reading status; the adapter sets all but `STALE`."""

    OK = "ok"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    NOT_NUMERIC = "not_numeric"
    UNIT = "unit"
    MISSING = "missing"
    STALE = "stale"


class Stage(StrEnum):
    """Where a value came from; shared with the outdoor module."""

    PRIMARY = "primary"
    FALLBACK = "fallback"
    NEIGHBOUR = "neighbour"
    OPPOSITE = "opposite"
    WEATHER = "weather"
    NONE = "none"


class Metric(StrEnum):
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    PRESSURE = "pressure"


@dataclass(frozen=True, slots=True)
class Reading:
    entity_id: str
    value: float | None  # in the metric's unit; None unless status is OK
    status: Status
    reported_at: datetime | None


@dataclass(frozen=True, slots=True)
class Offset:
    learned: float  # moving average of (source - reference)
    paired: timedelta  # accumulated paired time, capped at the time constant
    last_sample_at: datetime
    last_deviation: float  # most recent (source - reference)


@dataclass(frozen=True, slots=True)
class SourceState:
    offsets: Mapping[str, Offset]
    rank1: str | None  # entity at rank 1 when the offsets were last updated
    winner: str | None
    switched_at: datetime | None  # when the winner took over from a higher rank
    anchor: float | None  # winner's deviation at `switched_at` (glide start)


@dataclass(frozen=True, slots=True)
class Candidate:
    entity_id: str
    status: Status  # after the staleness check
    value: float | None  # raw value
    offset: float | None  # learned offset, None while there is no sample
    learned: bool  # paired for at least `OFFSET_LEARNED_AFTER`


@dataclass(frozen=True, slots=True)
class Resolution:
    value: float | None
    source: str | None
    rank: int | None  # 1-based
    stage: Stage
    offset: float | None  # applied offset, only for FALLBACK
    reason: Status | None  # status of the rank-1 source when stage is not PRIMARY
    candidates: tuple[Candidate, ...]


def effective_status(reading: Reading, max_age: timedelta, now: datetime) -> Status:
    """Rule 1: `OK` only with a value no older than `max_age`, else `STALE`."""
    if reading.status is not Status.OK:
        return reading.status
    if reading.reported_at is None or now - reading.reported_at > max_age:
        return Status.STALE
    return Status.OK


def learn(offset: Offset | None, sample: float, now: datetime) -> Offset:
    """Rule 4: fold one deviation sample into the moving average."""
    if offset is None:
        return Offset(sample, timedelta(0), now, sample)
    dt = min(now - offset.last_sample_at, const.OFFSET_SAMPLE_CAP)
    alpha = 1 - math.exp(-dt / const.OFFSET_TIME_CONSTANT)
    return Offset(
        learned=offset.learned + alpha * (sample - offset.learned),
        paired=min(offset.paired + dt, const.OFFSET_TIME_CONSTANT),
        last_sample_at=now,
        last_deviation=sample,
    )


def _rebase(
    offsets: Mapping[str, Offset], old_rank1: str | None, new_rank1: str | None
) -> dict[str, Offset]:
    """Rule 7: express all offsets relative to the new rank-1 entity."""
    new = offsets.get(new_rank1) if new_rank1 is not None else None
    if new is None:
        return {}
    shifted = {
        entity_id: replace(
            offset,
            learned=offset.learned - new.learned,
            last_deviation=offset.last_deviation - new.learned,
        )
        for entity_id, offset in offsets.items()
        if entity_id != new_rank1
    }
    if old_rank1 is not None:
        shifted[old_rank1] = Offset(
            learned=-new.learned,
            paired=new.paired,
            last_sample_at=new.last_sample_at,
            last_deviation=-new.last_deviation,
        )
    return shifted


def _glide_start(
    winner: str,
    previous_winner: str | None,
    ids: Sequence[str],
    offsets: Mapping[str, Offset],
    max_age: timedelta,
    now: datetime,
) -> tuple[datetime | None, float | None]:
    """Rule 6: `(switched_at, anchor)` of the winner; both None without a glide."""
    if winner == ids[0] or previous_winner not in ids:
        return None, None
    if ids.index(winner) < ids.index(previous_winner):
        return None, None
    entry = offsets.get(winner)
    if entry is None:
        return None, None
    fresh = now - entry.last_sample_at <= max_age
    return now, entry.last_deviation if fresh else entry.learned


def _applied_offset(
    entry: Offset | None,
    switched_at: datetime | None,
    anchor: float | None,
    now: datetime,
) -> float:
    """Rules 3 and 6: the learned offset, eased in from the anchor after a takeover."""
    if entry is None:
        return 0.0
    if switched_at is None or anchor is None:
        return entry.learned
    remaining = max(0.0, 1 - (now - switched_at) / const.OFFSET_GLIDE)
    return entry.learned + (anchor - entry.learned) * remaining


def resolve(
    readings: Sequence[Reading],
    max_age: timedelta,
    state: SourceState | None,
    now: datetime,
    bounds: tuple[float, float] | None,
) -> tuple[Resolution, SourceState]:
    """Resolve one metric from ranked readings and update the offset state."""
    ids = [reading.entity_id for reading in readings]
    statuses = [effective_status(reading, max_age, now) for reading in readings]
    previous = state or SourceState({}, None, None, None, None)
    rank1 = ids[0] if ids else None

    offsets = {k: v for k, v in previous.offsets.items() if k in ids}
    switched_at, anchor = previous.switched_at, previous.anchor
    if rank1 != previous.rank1:
        old_rank1 = previous.rank1 if previous.rank1 in ids else None
        offsets = _rebase(offsets, old_rank1, rank1)
        switched_at = anchor = None

    index = next((i for i, s in enumerate(statuses) if s is Status.OK), None)
    if index is None:
        resolution = Resolution(
            value=None,
            source=None,
            rank=None,
            stage=Stage.NONE,
            offset=None,
            reason=statuses[0] if statuses else None,
            candidates=_candidates(readings, statuses, offsets),
        )
        return resolution, SourceState(offsets, rank1, None, None, None)

    winner = ids[index]
    if winner != previous.winner:
        switched_at, anchor = _glide_start(
            winner, previous.winner, ids, offsets, max_age, now
        )
    elif index == 0:
        switched_at = anchor = None

    raw = readings[index].value
    assert raw is not None  # status OK carries a value
    applied = None
    value = raw
    if index > 0:
        applied = _applied_offset(offsets.get(winner), switched_at, anchor, now)
        value = raw - applied
    if bounds is not None:
        value = min(max(value, bounds[0]), bounds[1])

    for i in range(index + 1, len(readings)):
        sample = readings[i].value
        if statuses[i] is Status.OK and sample is not None:
            offsets[ids[i]] = learn(offsets.get(ids[i]), sample - value, now)

    resolution = Resolution(
        value=value,
        source=winner,
        rank=index + 1,
        stage=Stage.PRIMARY if index == 0 else Stage.FALLBACK,
        offset=applied,
        reason=None if index == 0 else statuses[0],
        candidates=_candidates(readings, statuses, offsets),
    )
    return resolution, SourceState(offsets, rank1, winner, switched_at, anchor)


def _candidates(
    readings: Sequence[Reading],
    statuses: Sequence[Status],
    offsets: Mapping[str, Offset],
) -> tuple[Candidate, ...]:
    result = []
    for reading, status in zip(readings, statuses, strict=True):
        entry = offsets.get(reading.entity_id)
        result.append(
            Candidate(
                entity_id=reading.entity_id,
                status=status,
                value=reading.value,
                offset=None if entry is None else entry.learned,
                learned=entry is not None
                and entry.paired >= const.OFFSET_LEARNED_AFTER,
            )
        )
    return tuple(result)
