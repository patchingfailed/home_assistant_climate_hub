"""House-level values: indoor average, "any room" flags, source outages.

docs/logic.md §12; H4, H5. House outdoor (O7) lives in the outdoor module.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean

from .sources import Status


@dataclass(frozen=True, slots=True)
class HouseValue:
    value: float | None
    minimum: float | None
    maximum: float | None


@dataclass(frozen=True, slots=True)
class OutageState:
    """Persisted: per configured source the time it was first seen invalid."""

    invalid_since: Mapping[str, datetime]


@dataclass(frozen=True, slots=True)
class Outage:
    entity_id: str
    status: Status
    invalid_since: datetime


def indoor_average(rooms: Sequence[float | None]) -> HouseValue:
    """Rule 1: mean, min and max of the rooms with a value."""
    values = [value for value in rooms if value is not None]
    if not values:
        return HouseValue(None, None, None)
    return HouseValue(fmean(values), min(values), max(values))


def any_of(flags: Sequence[bool | None]) -> bool | None:
    """Rule 3: three-valued "any" (§1); no flags at all is unknown."""
    if True in flags:
        return True
    if not flags or None in flags:
        return None
    return False


def outages(
    statuses: Mapping[str, Status],
    state: OutageState | None,
    now: datetime,
    delay: timedelta,
) -> tuple[list[Outage], OutageState]:
    """Rule 4 (H5): sources invalid for at least `delay`.

    `statuses` holds every configured source with its status after the staleness
    check (`Candidate.status` of §4). Sources no longer configured are forgotten.
    """
    previous = state.invalid_since if state is not None else {}
    invalid_since = {
        entity_id: previous.get(entity_id, now)
        for entity_id, status in statuses.items()
        if status is not Status.OK
    }
    reported = [
        Outage(entity_id, statuses[entity_id], since)
        for entity_id, since in invalid_since.items()
        if now - since >= delay
    ]
    return reported, OutageState(invalid_since)
