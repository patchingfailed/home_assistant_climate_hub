"""Area sync decision table (docs/integration.md §11)."""

import pytest

from custom_components.climate_hub.logic.area_sync import (
    Action,
    Decision,
    FieldRecord,
    decide,
    foreign,
    release,
)

OURS = "sensor.ch_temp"
OLD = "sensor.ch_old"
OTHER = "sensor.other"
PREV = "sensor.previous"


@pytest.mark.parametrize(
    ("current", "wanted", "record", "replace", "expected"),
    [
        # 1: the user changed it
        (
            OTHER,
            OURS,
            FieldRecord(OURS),
            False,
            Decision(Action.LEAVE, record=FieldRecord(OURS)),
        ),
        (
            None,
            OURS,
            FieldRecord(OURS, PREV),
            True,
            Decision(Action.LEAVE, record=FieldRecord(OURS, PREV)),
        ),
        # 2: consent withdrawn, also when the recorded entity is not the wanted one
        (
            OURS,
            OURS,
            FieldRecord(OURS, PREV),
            False,
            Decision(Action.RESTORE, value=PREV),
        ),
        (
            OLD,
            OURS,
            FieldRecord(OLD, PREV),
            False,
            Decision(Action.RESTORE, value=PREV),
        ),
        # 3: our entity changed, previous stays
        (
            OLD,
            OURS,
            FieldRecord(OLD),
            False,
            Decision(Action.WRITE, OURS, FieldRecord(OURS)),
        ),
        (
            OLD,
            OURS,
            FieldRecord(OLD, PREV),
            True,
            Decision(Action.WRITE, OURS, FieldRecord(OURS, PREV)),
        ),
        # 4: keep; replace on does not trigger row 2
        (
            OURS,
            OURS,
            FieldRecord(OURS),
            False,
            Decision(Action.KEEP, record=FieldRecord(OURS)),
        ),
        (
            OURS,
            OURS,
            FieldRecord(OURS, PREV),
            True,
            Decision(Action.KEEP, record=FieldRecord(OURS, PREV)),
        ),
        # 5
        (OURS, OURS, None, False, Decision(Action.KEEP, record=FieldRecord(OURS))),
        (OURS, OURS, None, True, Decision(Action.KEEP, record=FieldRecord(OURS))),
        # 6
        (None, OURS, None, False, Decision(Action.WRITE, OURS, FieldRecord(OURS))),
        (None, OURS, None, True, Decision(Action.WRITE, OURS, FieldRecord(OURS))),
        # 7
        (
            OTHER,
            OURS,
            None,
            True,
            Decision(Action.WRITE, OURS, FieldRecord(OURS, OTHER)),
        ),
        # 8
        (OTHER, OURS, None, False, Decision(Action.LEAVE)),
    ],
)
def test_decide(current, wanted, record, replace, expected) -> None:
    assert decide(current, wanted, record, replace) == expected


@pytest.mark.parametrize(
    ("current", "record", "expected"),
    [
        (OURS, FieldRecord(OURS, PREV), Decision(Action.RESTORE, value=PREV)),
        (OURS, FieldRecord(OURS), Decision(Action.RESTORE, value=None)),
        (OTHER, FieldRecord(OURS, PREV), Decision(Action.LEAVE)),
        (None, FieldRecord(OURS), Decision(Action.LEAVE)),
    ],
)
def test_release(current, record, expected) -> None:
    assert release(current, record) == expected


@pytest.mark.parametrize(
    ("current", "wanted", "expected"),
    [
        (None, OURS, None),
        (OURS, OURS, None),
        (OTHER, OURS, OTHER),
        (OTHER, None, OTHER),
        (None, None, None),
    ],
)
def test_foreign(current, wanted, expected) -> None:
    assert foreign(current, wanted) == expected
