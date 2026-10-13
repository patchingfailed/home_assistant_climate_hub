"""Table cases of docs/logic.md §4."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.climate_hub.logic import const
from custom_components.climate_hub.logic.sources import (
    Offset,
    Reading,
    SourceState,
    Stage,
    Status,
    effective_status,
    learn,
    resolve,
)

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
MAX_AGE = timedelta(minutes=40)
HOUR = timedelta(hours=1)


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return NOW.replace(hour=hour, minute=minute, second=second)


def ok(entity_id: str, value: float, reported_at: datetime) -> Reading:
    return Reading(entity_id, value, Status.OK, reported_at)


def bad(entity_id: str, status: Status) -> Reading:
    return Reading(entity_id, None, status, None)


def offset(learned: float, *, paired: timedelta = 8 * HOUR, at_=NOW) -> Offset:
    return Offset(learned, paired, at_, learned)


def state(offsets, *, rank1="s1", winner=None, switched_at=None, anchor=None):
    return SourceState(offsets, rank1, winner, switched_at, anchor)


LEARNED = {"s2": offset(0.3), "s3": offset(1.2)}


@pytest.mark.parametrize(
    ("readings", "value", "source", "stage", "applied", "reason"),
    [
        (
            [
                ok("s1", 21.4, at(11, 55)),
                ok("s2", 21.7, at(11, 50)),
                ok("s3", 22.6, at(11, 58)),
            ],
            21.4,
            "s1",
            Stage.PRIMARY,
            None,
            None,
        ),
        (
            [
                ok("s1", 21.4, at(11, 15)),
                ok("s2", 21.7, at(11, 50)),
                ok("s3", 22.6, at(11, 58)),
            ],
            21.4,
            "s2",
            Stage.FALLBACK,
            0.3,
            Status.STALE,
        ),
        (
            [
                ok("s1", 21.4, at(11, 20)),
                ok("s2", 21.7, at(11, 50)),
                ok("s3", 22.6, at(11, 58)),
            ],
            21.4,
            "s1",
            Stage.PRIMARY,
            None,
            None,
        ),
        (
            [
                bad("s1", Status.UNAVAILABLE),
                bad("s2", Status.UNAVAILABLE),
                ok("s3", 22.6, at(11, 58)),
            ],
            21.4,
            "s3",
            Stage.FALLBACK,
            1.2,
            Status.UNAVAILABLE,
        ),
        (
            [
                bad("s1", Status.NOT_NUMERIC),
                ok("s2", 21.7, at(11, 50)),
                ok("s3", 22.6, at(11, 58)),
            ],
            21.4,
            "s2",
            Stage.FALLBACK,
            0.3,
            Status.NOT_NUMERIC,
        ),
        (
            [
                bad("s1", Status.UNIT),
                ok("s2", 21.7, at(11, 50)),
                ok("s3", 22.6, at(11, 58)),
            ],
            21.4,
            "s2",
            Stage.FALLBACK,
            0.3,
            Status.UNIT,
        ),
        (
            [
                bad("s1", Status.UNAVAILABLE),
                bad("s2", Status.UNAVAILABLE),
                bad("s3", Status.UNAVAILABLE),
            ],
            None,
            None,
            Stage.NONE,
            None,
            Status.UNAVAILABLE,
        ),
        ([], None, None, Stage.NONE, None, None),
    ],
    ids=["1", "2", "3", "4", "5", "6", "7", "8"],
)
def test_resolution(readings, value, source, stage, applied, reason):
    start = state(LEARNED, winner=source)
    result, _ = resolve(readings, MAX_AGE, start, NOW, None)
    assert result.value == (None if value is None else pytest.approx(value))
    assert result.source == source
    assert result.stage is stage
    assert result.offset == (None if applied is None else pytest.approx(applied))
    assert result.reason == reason
    assert result.rank == (None if source is None else int(source[1:]))
    assert len(result.candidates) == len(readings)


def test_humidity_clamp():
    readings = [bad("s1", Status.UNAVAILABLE), ok("s2", 99.0, at(11, 55))]
    start = state({"s2": offset(-2.0)}, winner="s2")
    result, _ = resolve(readings, MAX_AGE, start, NOW, const.HUMIDITY_RANGE)
    assert result.value == 100.0
    assert result.offset == -2.0


def test_fallback_without_offset_entry_applies_zero():
    readings = [bad("s1", Status.UNAVAILABLE), ok("s2", 21.7, at(11, 55))]
    result, _ = resolve(readings, MAX_AGE, state({}, winner="s2"), NOW, None)
    assert result.value == 21.7
    assert result.offset == 0.0


@pytest.mark.parametrize(
    ("reported_at", "expected"),
    [
        (NOW, Status.OK),
        (NOW - MAX_AGE, Status.OK),
        (NOW - MAX_AGE - timedelta(seconds=1), Status.STALE),
        (None, Status.STALE),
    ],
)
def test_effective_status(reported_at, expected):
    assert (
        effective_status(Reading("s1", 20.0, Status.OK, reported_at), MAX_AGE, NOW)
        is expected
    )
    assert (
        effective_status(Reading("s1", None, Status.UNIT, NOW), MAX_AGE, NOW)
        is Status.UNIT
    )


@pytest.mark.parametrize(
    ("before", "sample", "dt", "after"),
    [
        (1.0, 1.2, timedelta(minutes=1), 1.000416),
        (1.0, 2.0, timedelta(minutes=10), 1.0206),
        (1.0, 2.0, timedelta(hours=2), 1.0606),
    ],
)
def test_learning_single_sample(before, sample, dt, after):
    previous = Offset(before, timedelta(0), NOW - dt, before)
    assert learn(previous, sample, NOW).learned == pytest.approx(after, abs=1e-4)


def test_learning_first_sample():
    first = learn(None, 1.0, NOW)
    assert first == Offset(1.0, timedelta(0), NOW, 1.0)


@pytest.mark.parametrize(
    ("minutes", "after"), [(60, 1.118), (480, 1.632), (1440, 1.950)]
)
def test_learning_constant_sample(minutes, after):
    current = Offset(1.0, timedelta(0), NOW, 1.0)
    for i in range(1, minutes + 1):
        current = learn(current, 2.0, NOW + timedelta(minutes=i))
    assert current.learned == pytest.approx(after, abs=1e-3)
    assert current.last_deviation == 2.0
    assert current.paired == min(timedelta(minutes=minutes), 8 * HOUR)


def three(s1, s2, s3):
    return [s1, s2, s3]


def test_learning_gate_primary_wins():
    readings = three(ok("s1", 21.0, NOW), ok("s2", 21.5, NOW), ok("s3", 22.0, NOW))
    _, new = resolve(readings, MAX_AGE, None, NOW, None)
    assert set(new.offsets) == {"s2", "s3"}
    assert new.offsets["s2"].learned == pytest.approx(0.5)
    assert new.offsets["s3"].learned == pytest.approx(1.0)


def test_learning_gate_fallback_wins():
    readings = three(
        bad("s1", Status.UNAVAILABLE), ok("s2", 21.5, NOW), ok("s3", 22.0, NOW)
    )
    start = state({"s2": offset(0.5), "s3": offset(1.0)}, winner="s2")
    result, new = resolve(readings, MAX_AGE, start, NOW, None)
    assert result.value == pytest.approx(21.0)
    assert new.offsets["s2"] == start.offsets["s2"]
    assert new.offsets["s3"].last_deviation == pytest.approx(1.0)
    assert new.offsets["s3"].last_sample_at == NOW


def test_invalid_source_never_learns():
    readings = three(
        ok("s1", 21.0, NOW), bad("s2", Status.UNAVAILABLE), ok("s3", 22.0, at(10, 0))
    )
    _, new = resolve(readings, MAX_AGE, None, NOW, None)
    assert new.offsets == {}


@pytest.mark.parametrize(
    ("now", "deviation_at", "expected"),
    [
        (at(12, 0), at(11, 59), 1.6),
        (at(12, 30), at(11, 59), 1.3),
        (at(13, 0), at(11, 59), 1.0),
        (at(13, 30), at(11, 59), 1.0),
        (at(12, 0), at(11, 0), 1.0),
    ],
    ids=["12:00", "12:30", "13:00", "13:30", "old deviation"],
)
def test_glide(now, deviation_at, expected):
    s2 = Offset(1.0, 8 * HOUR, deviation_at, 1.6)
    start = state({"s2": s2}, winner="s1")
    stale_s1 = ok("s1", 20.0, at(11, 0))
    takeover = at(12, 0)
    readings = [stale_s1, ok("s2", 22.0, takeover)]
    result, new = resolve(readings, MAX_AGE, start, takeover, None)
    if now != takeover:
        readings = [stale_s1, ok("s2", 22.0, now)]
        result, new = resolve(readings, MAX_AGE, new, now, None)
    assert result.offset == pytest.approx(expected)
    assert result.value == pytest.approx(22.0 - expected)


def test_no_glide_for_higher_ranked_takeover_or_start_up():
    readings = [ok("s1", 21.0, NOW), ok("s2", 22.0, NOW)]
    start = state({"s2": offset(1.0)}, winner="s2", switched_at=at(11, 50), anchor=1.6)
    _, new = resolve(readings, MAX_AGE, start, NOW, None)
    assert (new.winner, new.switched_at, new.anchor) == ("s1", None, None)
    fallback = [bad("s1", Status.UNAVAILABLE), ok("s2", 22.0, NOW)]
    _, new = resolve(fallback, MAX_AGE, state({"s2": offset(1.0)}), NOW, None)
    assert (new.switched_at, new.anchor) == (None, None)


def rebase_start():
    return state(LEARNED, winner="s1")


def fresh(*ids):
    return [ok(entity_id, 20.0, NOW) for entity_id in ids]


def _learned(new, entity_id):
    return new.offsets[entity_id].learned


def test_rebase_new_rank1_moves_up():
    _, new = resolve(fresh("s3", "s1", "s2"), MAX_AGE, rebase_start(), NOW, None)
    assert new.rank1 == "s3"
    assert "s3" not in new.offsets
    # offsets are re-based first, then this evaluation learns against 20.0
    assert new.offsets["s1"].last_sample_at == NOW


def test_rebase_values_before_learning():
    readings = [
        bad("s3", Status.UNAVAILABLE),
        bad("s1", Status.UNAVAILABLE),
        bad("s2", Status.UNAVAILABLE),
    ]
    _, new = resolve(readings, MAX_AGE, rebase_start(), NOW, None)
    assert "s3" not in new.offsets
    assert _learned(new, "s1") == pytest.approx(-1.2)
    assert _learned(new, "s2") == pytest.approx(-0.9)
    assert new.offsets["s1"].paired == 8 * HOUR


def test_rebase_swap_keeps_offsets():
    readings = [
        bad("s1", Status.UNAVAILABLE),
        bad("s3", Status.UNAVAILABLE),
        bad("s2", Status.UNAVAILABLE),
    ]
    _, new = resolve(readings, MAX_AGE, rebase_start(), NOW, None)
    assert new.offsets == LEARNED


def test_rebase_new_entity_drops_all():
    readings = [bad("x", Status.UNAVAILABLE)] + [
        bad(i, Status.UNAVAILABLE) for i in ("s1", "s2", "s3")
    ]
    _, new = resolve(readings, MAX_AGE, rebase_start(), NOW, None)
    assert new.offsets == {}
    assert new.rank1 == "x"


def test_rebase_removed_entity_is_dropped():
    readings = [bad("s1", Status.UNAVAILABLE), bad("s2", Status.UNAVAILABLE)]
    _, new = resolve(readings, MAX_AGE, rebase_start(), NOW, None)
    assert new.offsets == {"s2": LEARNED["s2"]}


def test_rebase_clears_running_glide():
    start = state(LEARNED, winner="s1", switched_at=at(11, 50), anchor=1.5)
    readings = [bad("s3", Status.UNAVAILABLE), ok("s1", 21.0, NOW)]
    _, new = resolve(readings, MAX_AGE, start, NOW, None)
    assert (new.switched_at, new.anchor) == (None, None)
