"""Table cases of docs/logic.md §8."""

from datetime import UTC, datetime

import pytest

from custom_components.climate_hub.logic.window import (
    ContactKind,
    Debounced,
    FrameConfig,
    Level,
    OpenLeaves,
    PassThroughConfig,
    WindowState,
    contact_level,
    debounce,
    open_since,
    room_windows,
    suggest_text_mapping,
    ventilating,
    window_level,
)

C, A, T, OP = Level.CLOSED, Level.AJAR, Level.TILTED, Level.OPEN

# Test data only: the real default words come from the translations.
WORDS = {
    C: frozenset(
        {"zu", "geschlossen", "verriegelt", "abgeschlossen", "closed", "locked"}
    ),
    A: frozenset({"angelehnt", "ajar"}),
    T: frozenset({"gekippt", "kipp", "tilted"}),
    OP: frozenset({"offen", "open"}),
}
MAPPING = {
    C: frozenset({"zu"}),
    A: frozenset({"angelehnt"}),
    T: frozenset({"gekippt"}),
    OP: frozenset({"offen"}),
}


def _level(marker):
    """Table marker to level: 1 open, 0 closed, ? unknown, text:<state> mapped."""
    if marker == "1":
        return OP
    if marker == "0":
        return C
    if marker == "?":
        return None
    return contact_level(marker.removeprefix("text:"), ContactKind.TEXT, MAPPING)


def _levels(**markers):
    return {name: _level(m) for name, m in markers.items() if m != "-"}


@pytest.mark.parametrize(
    ("raw", "kind", "mapping", "expected"),
    [
        ("on", ContactKind.BINARY, None, OP),
        ("off", ContactKind.BINARY, None, C),
        ("ON", ContactKind.BINARY, None, OP),
        ("unavailable", ContactKind.BINARY, None, None),
        ("unknown", ContactKind.BINARY, None, None),
        ("", ContactKind.BINARY, None, None),
        (None, ContactKind.BINARY, None, None),
        ("gekippt", ContactKind.TEXT, MAPPING, T),
        ("  Gekippt ", ContactKind.TEXT, MAPPING, T),
        ("OFFEN", ContactKind.TEXT, MAPPING, OP),
        ("Spalt", ContactKind.TEXT, MAPPING, None),
        ("unavailable", ContactKind.TEXT, MAPPING, None),
        ("unknown", ContactKind.TEXT, MAPPING, None),
        ("", ContactKind.TEXT, MAPPING, None),
        ("zu", ContactKind.TEXT, None, None),
    ],
)
def test_contact_level(raw, kind, mapping, expected):
    assert contact_level(raw, kind, mapping) is expected


@pytest.mark.parametrize(
    ("m", "d", "h", "level", "implausible"),
    [
        ("0", "-", "-", C, False),
        ("1", "-", "-", OP, False),
        ("1", "0", "-", T, False),
        ("1", "1", "-", OP, False),
        ("0", "1", "-", OP, True),
        ("0", "-", "1", A, False),
        ("1", "-", "1", OP, False),
        ("?", "-", "-", None, False),
        ("?", "1", "-", OP, False),
        ("?", "0", "-", None, False),
        ("1", "?", "-", OP, False),
        ("0", "-", "?", C, False),
        ("text:gekippt", "-", "-", T, False),
        ("text:offen", "0", "-", T, False),
        ("text:angelehnt", "1", "-", OP, True),
        ("text:Spalt", "-", "-", None, False),
    ],
)
def test_single_window(m, d, h, level, implausible):
    config = FrameConfig(
        ("m",), tilt="d" if d != "-" else None, handle="h" if h != "-" else None
    )
    result = window_level(config, _levels(m=m, d=d, h=h))
    assert result.level is level
    assert result.implausible is implausible
    assert result.open_leaves is None
    assert ventilating(result.level) is (None if level is None else level >= T)


@pytest.mark.parametrize(
    ("left", "right", "d", "level", "leaves", "implausible"),
    [
        ("0", "0", "0", C, OpenLeaves.NONE, False),
        ("1", "0", "0", T, OpenLeaves.LEFT, False),
        ("0", "1", "0", T, OpenLeaves.RIGHT, False),
        ("1", "1", "0", T, OpenLeaves.BOTH, False),
        ("1", "0", "1", OP, OpenLeaves.LEFT, False),
        ("0", "1", "1", OP, OpenLeaves.RIGHT, False),
        ("1", "1", "1", OP, OpenLeaves.BOTH, False),
        ("0", "0", "1", OP, OpenLeaves.UNKNOWN, True),
        ("1", "?", "0", T, OpenLeaves.LEFT, False),
        ("0", "?", "0", None, None, False),
        ("0", "?", "1", OP, OpenLeaves.UNKNOWN, False),
        ("1", "1", "?", OP, OpenLeaves.BOTH, False),
        ("0", "0", "?", C, OpenLeaves.NONE, False),
        ("?", "?", "0", None, None, False),
    ],
)
def test_double_leaf(left, right, d, level, leaves, implausible):
    config = FrameConfig(("l", "r"), tilt="d")
    result = window_level(config, _levels(l=left, r=right, d=d))
    assert result.level is level
    assert result.open_leaves is leaves
    assert result.implausible is implausible


def test_handle_acts_on_double_leaf():
    config = FrameConfig(("l", "r"), handle="h")
    result = window_level(config, _levels(l="0", r="0", h="1"))
    assert result.level is A
    assert result.open_leaves is OpenLeaves.NONE


@pytest.mark.parametrize(
    ("inner", "outer", "level"),
    [
        ("1", "1", OP),
        ("1", "0", C),
        ("0", "1", C),
        ("1", "?", None),
        ("0", "?", C),
        ("?", "0", C),
        ("?", "?", None),
        ("text:gekippt", "1", T),
    ],
)
def test_pass_through(inner, outer, level):
    result = window_level(PassThroughConfig("i", "o"), _levels(i=inner, o=outer))
    assert result.level is level
    assert result.open_leaves is None
    assert result.implausible is False


def test_one_contact_serves_several_windows():
    levels = {"shared": OP, "other": C}
    assert window_level(FrameConfig(("shared",)), levels).level is OP
    assert window_level(FrameConfig(("other", "shared")), levels).level is OP


DAY = datetime(2026, 10, 13, 10, tzinfo=UTC)


def _at(minute, second):
    return DAY.replace(minute=minute, second=second)


def _run(steps):
    """Feed (time, raw) steps like the adapter; yield (published, open_since)."""
    state, since = None, None
    for when, raw in steps:
        state = debounce(raw, state, when)
        since = open_since(state, T, since, None)
        yield state.published, since


def test_debounce_and_open_since_timeline():
    steps = [
        (_at(0, 0), C),
        (_at(0, 2), T),
        (_at(0, 7), T),
        (_at(5, 0), OP),
        (_at(5, 5), OP),
        (_at(6, 0), C),
        (_at(6, 3), OP),
        (_at(20, 0), None),
        (_at(20, 5), None),
        (_at(30, 0), C),
        (_at(30, 5), C),
    ]
    since = _at(0, 2)
    assert list(_run(steps)) == [
        (C, None),
        (C, None),
        (T, since),
        (T, since),
        (OP, since),
        (OP, since),
        (OP, since),
        (OP, since),
        (None, since),
        (None, since),
        (C, None),
    ]


def test_open_since_is_raw_start_across_ventilating_levels():
    steps = [(_at(0, 0), C), (_at(0, 2), T), (_at(0, 4), OP), (_at(0, 9), OP)]
    assert list(_run(steps))[-1] == (OP, _at(0, 2))


def test_debounce_boundary_is_inclusive():
    state = debounce(C, None, _at(0, 0))
    state = debounce(OP, state, _at(0, 1))
    assert debounce(OP, state, _at(0, 5)).published is C
    assert debounce(OP, state, _at(0, 6)).published is OP


def test_debounce_publishes_immediately_at_startup():
    assert debounce(None, None, _at(0, 0)).published is None
    assert debounce(OP, None, _at(0, 0)).published is OP


@pytest.mark.parametrize(
    ("published", "prev", "hint", "expected"),
    [
        (OP, _at(1, 0), _at(2, 0), _at(1, 0)),  # persisted value kept
        (OP, None, _at(2, 0), _at(2, 0)),  # best effort from the contacts
        (OP, None, None, _at(0, 0)),  # first seen
        (C, _at(1, 0), _at(2, 0), None),
        (None, _at(1, 0), None, _at(1, 0)),
        (None, None, None, None),
    ],
)
def test_open_since_after_restart(published, prev, hint, expected):
    state = debounce(published, None, _at(0, 0))
    assert open_since(state, T, prev, hint) == expected


def test_open_since_min_level():
    state = Debounced(A, _at(0, 0), A, _at(0, 0))
    assert open_since(state, T, None, None) is None
    assert open_since(state, A, None, None) == _at(0, 0)


def _w(level, since=None):
    return WindowState(level, ventilating(level), since)


@pytest.mark.parametrize(
    ("windows", "level", "vent", "since"),
    [
        ([_w(C), _w(C)], C, False, None),
        ([_w(T, _at(0, 0)), _w(OP, _at(5, 0))], OP, True, _at(0, 0)),
        ([_w(C), _w(None)], None, None, None),
        ([_w(T, _at(0, 0)), _w(None)], T, True, _at(0, 0)),
        ([_w(A), _w(None)], None, None, None),
        ([_w(A), _w(C)], A, False, None),
        ([], None, False, None),
    ],
)
def test_room_windows(windows, level, vent, since):
    result = room_windows(windows)
    assert result.level is level
    assert result.ventilating is vent
    assert result.open_since == since


def test_suggest_text_mapping():
    texts = ["Gekippt", " ZU ", "open", "Spalt", "ajar", "verriegelt"]
    assert suggest_text_mapping(texts, WORDS) == {
        C: frozenset({" ZU ", "verriegelt"}),
        A: frozenset({"ajar"}),
        T: frozenset({"Gekippt"}),
        OP: frozenset({"open"}),
    }
    assert suggest_text_mapping([], WORDS) == {level: frozenset() for level in Level}
