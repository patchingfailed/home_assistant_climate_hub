"""Area sync decisions: what to do with one area field (R11, integration §11).

Pure: the caller reads the area registry and the records and applies the result.
"""

from dataclasses import dataclass
from enum import StrEnum

FIELDS = ("temperature", "humidity")


@dataclass(frozen=True, slots=True)
class FieldRecord:
    """A field Climate Hub wrote: the entity it wrote and the sensor it replaced."""

    entity_id: str
    previous: str | None = None


class Action(StrEnum):
    LEAVE = "leave"  # touch nothing; keep or skip the record as `record` says
    KEEP = "keep"  # the field already holds what it should
    WRITE = "write"  # write `value`
    RESTORE = "restore"  # write `value` (the previous sensor, or None to empty)


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    value: str | None = None  # what to write for WRITE and RESTORE
    record: FieldRecord | None = None  # the record afterwards; None drops it


def decide(
    current: str | None,
    wanted: str,
    record: FieldRecord | None,
    replace: bool,
) -> Decision:
    """One wanted field; the first matching row of the §11 table applies."""
    if record is not None:
        if current != record.entity_id:  # 1: the user changed it
            return Decision(Action.LEAVE, record=record)
        if record.previous is not None and not replace:  # 2: consent withdrawn
            return Decision(Action.RESTORE, value=record.previous)
        if current != wanted:  # 3: our entity changed
            return Decision(
                Action.WRITE, value=wanted, record=FieldRecord(wanted, record.previous)
            )
        return Decision(Action.KEEP, record=record)  # 4
    if current == wanted:  # 5
        return Decision(Action.KEEP, record=FieldRecord(wanted))
    if current is None:  # 6
        return Decision(Action.WRITE, value=wanted, record=FieldRecord(wanted))
    if replace:  # 7
        return Decision(Action.WRITE, value=wanted, record=FieldRecord(wanted, current))
    return Decision(Action.LEAVE)  # 8: a foreign sensor without consent


def release(current: str | None, record: FieldRecord) -> Decision:
    """A recorded field no longer wanted (§11 point 5); the record is dropped."""
    if current != record.entity_id:
        return Decision(Action.LEAVE)
    return Decision(Action.RESTORE, value=record.previous)


def foreign(current: str | None, wanted: str | None) -> str | None:
    """The sensor in a field that is neither empty nor Climate Hub's wanted entity."""
    if current is None or current == wanted:
        return None
    return current
