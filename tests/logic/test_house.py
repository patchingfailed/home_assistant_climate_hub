"""Table cases of docs/logic.md §12."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.climate_hub.logic.const import DEFAULT_REPAIR_DELAY
from custom_components.climate_hub.logic.house import (
    HouseValue,
    OutageState,
    any_of,
    indoor_average,
    outages,
)
from custom_components.climate_hub.logic.sources import Status

TZ = ZoneInfo("Europe/Berlin")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 13, hour, minute, tzinfo=TZ)


@pytest.mark.parametrize(
    ("rooms", "expected"),
    [
        ([21.0, 22.0, 23.5], HouseValue(pytest.approx(22.17, abs=0.01), 21.0, 23.5)),
        ([21.0, None], HouseValue(21.0, 21.0, 21.0)),
        ([None, None], HouseValue(None, None, None)),
    ],
)
def test_indoor_average(rooms, expected):
    assert indoor_average(rooms) == expected


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ([False, False], False),
        ([False, True, None], True),
        ([False, None], None),
        ([], None),
    ],
)
def test_any_of(flags, expected):
    assert any_of(flags) is expected


def _run(timeline: list[tuple[datetime, Status]]) -> tuple[list, OutageState]:
    state = None
    reported: list = []
    for now, status in timeline:
        reported, state = outages(
            {"sensor.t": status}, state, now, DEFAULT_REPAIR_DELAY
        )
    return reported, state


@pytest.mark.parametrize(
    ("timeline", "outage"),
    [
        ([(at(6), Status.UNAVAILABLE), (at(11, 59), Status.UNAVAILABLE)], False),
        ([(at(6), Status.UNAVAILABLE), (at(12), Status.UNAVAILABLE)], True),
        (
            [
                (at(6), Status.STALE),
                (at(10), Status.OK),
                (at(12), Status.STALE),
            ],
            False,
        ),
    ],
    ids=["before delay", "at delay", "cleared when valid again"],
)
def test_outages(timeline, outage):
    reported, _ = _run(timeline)
    assert bool(reported) is outage
    if outage:
        assert reported[0].entity_id == "sensor.t"
        assert reported[0].invalid_since == at(6)
        assert reported[0].status is Status.UNAVAILABLE


def test_outage_survives_a_restart_and_forgets_removed_sources():
    _, state = _run([(at(6), Status.UNAVAILABLE)])
    reported, state = outages(
        {"sensor.t": Status.UNAVAILABLE, "sensor.h": Status.OK},
        state,
        at(12),
        DEFAULT_REPAIR_DELAY,
    )
    assert [o.entity_id for o in reported] == ["sensor.t"]
    _, state = outages({"sensor.h": Status.OK}, state, at(13), DEFAULT_REPAIR_DELAY)
    assert state.invalid_since == {}
