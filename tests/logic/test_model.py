"""Table cases of docs/integration.md §3.3: the pure parsers."""

from datetime import timedelta

import pytest

from custom_components.climate_hub.logic.model import (
    RegionModel,
    RoomModel,
    Settings,
    build_house,
    parse_region,
    parse_room,
    parse_settings,
    parse_window,
)
from custom_components.climate_hub.logic.outdoor import Direction
from custom_components.climate_hub.logic.sources import Metric
from custom_components.climate_hub.logic.window import (
    ContactKind,
    FrameConfig,
    Level,
    PassThroughConfig,
)

N, E, S, W = Direction.N, Direction.E, Direction.S, Direction.W
T, H, P = Metric.TEMPERATURE, Metric.HUMIDITY, Metric.PRESSURE
SETTINGS = Settings(
    timedelta(minutes=40), timedelta(minutes=10), 60.0, timedelta(hours=6)
)
NO_FOLLOW: dict[Metric, list[str]] = {}


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, SETTINGS),
        (
            {
                "max_age": 15,
                "burst_duration": 5,
                "humidity_threshold": 55,
                "repair_delay": 2,
                "weather": "weather.home",
                "area_sync": False,
            },
            Settings(
                timedelta(minutes=15), timedelta(minutes=5), 55.0, timedelta(hours=2)
            ),
        ),
        (
            {"max_age": 90},
            Settings(
                timedelta(minutes=90), timedelta(minutes=10), 60.0, timedelta(hours=6)
            ),
        ),
    ],
)
def test_parse_settings(options, expected):
    assert parse_settings(options) == expected


@pytest.mark.parametrize(
    ("data", "followed", "side", "sources", "max_age"),
    [
        # own lists, no follow, defaults
        (
            {
                "area": "a1",
                "side": "s",
                "temperature": ["sensor.t"],
                "humidity": ["sensor.h"],
                "pressure": ["sensor.p"],
            },
            {H: ["sensor.fh"], P: ["sensor.fp"]},
            S,
            {T: ("sensor.t",), H: ("sensor.h",), P: ("sensor.p",)},
            timedelta(minutes=40),
        ),
        # empty lists follow (R3)
        (
            {
                "area": "a1",
                "side": "n",
                "temperature": ["sensor.t"],
                "humidity": [],
                "pressure": [],
            },
            {H: ["sensor.fh"], P: ["sensor.fp1", "sensor.fp2"]},
            N,
            {T: ("sensor.t",), H: ("sensor.fh",), P: ("sensor.fp1", "sensor.fp2")},
            timedelta(minutes=40),
        ),
        # absent keys follow too; nothing to follow gives empty lists
        (
            {"area": "a1", "side": "none", "temperature": ["sensor.t"], "max_age": 20},
            NO_FOLLOW,
            None,
            {T: ("sensor.t",), H: (), P: ()},
            timedelta(minutes=20),
        ),
        # temperature keeps its rank order; no side key means no side
        (
            {"area": "a1", "temperature": ["sensor.b", "sensor.a"]},
            {H: ["sensor.fh"]},
            None,
            {T: ("sensor.b", "sensor.a"), H: ("sensor.fh",), P: ()},
            timedelta(minutes=40),
        ),
    ],
)
def test_parse_room(data, followed, side, sources, max_age):
    room = parse_room("r1", data, SETTINGS, followed)
    assert room == RoomModel(
        id="r1",
        area_id="a1",
        side=side,
        sources=sources,
        climate_devices=(),
        max_age=max_age,
        window_ids=(),
    )


def test_parse_room_climate_devices():
    data = {"area": "a1", "temperature": ["sensor.t"], "climate_devices": ["climate.x"]}
    assert parse_room("r1", data, SETTINGS, NO_FOLLOW).climate_devices == ("climate.x",)


@pytest.mark.parametrize(
    ("data", "followed", "sources", "max_age"),
    [
        (
            {"area": "a2", "direction": "w", "temperature": ["sensor.t"]},
            NO_FOLLOW,
            {T: ("sensor.t",), H: (), P: ()},
            timedelta(minutes=40),
        ),
        (
            {
                "area": "a2",
                "direction": "w",
                "temperature": ["sensor.t"],
                "humidity": [],
                "max_age": 5,
            },
            {H: ["sensor.fh"], P: ["sensor.fp"]},
            {T: ("sensor.t",), H: ("sensor.fh",), P: ("sensor.fp",)},
            timedelta(minutes=5),
        ),
    ],
)
def test_parse_region(data, followed, sources, max_age):
    assert parse_region("g1", data, SETTINGS, followed) == RegionModel(
        "g1", "a2", W, sources, max_age
    )


SINGLE = {
    "area": "a1",
    "type": "single",
    "name": "Window",
    "leaf": "binary_sensor.leaf",
}


def test_parse_window_single_defaults():
    window = parse_window("w1", SINGLE)
    assert window.name == "Window"
    assert window.config == FrameConfig(leaves=("binary_sensor.leaf",))
    assert window.kinds == {"binary_sensor.leaf": ContactKind.BINARY}
    assert window.mappings == {}
    assert (window.room_id, window.facing, window.direction) == (None, None, None)
    assert (window.cover, window.facing_degrees) == (None, None)
    assert window.min_level is Level.TILTED


def test_parse_window_double_with_refiners():
    window = parse_window(
        "w1",
        {
            "area": "a1",
            "type": "double",
            "name": "Fenster",
            "leaf_left": "binary_sensor.l",
            "leaf_right": "binary_sensor.r",
            "tilt": "sensor.tilt",
            "handle": "binary_sensor.handle",
            "cover": "cover.shutter",
            "facing": "e",
            "facing_degrees": 100.0,
            "min_level": "open",
        },
    )
    assert window.config == FrameConfig(
        leaves=("binary_sensor.l", "binary_sensor.r"),
        tilt="sensor.tilt",
        handle="binary_sensor.handle",
    )
    assert window.kinds == {
        "binary_sensor.l": ContactKind.BINARY,
        "binary_sensor.r": ContactKind.BINARY,
        "sensor.tilt": ContactKind.TEXT,
        "binary_sensor.handle": ContactKind.BINARY,
    }
    assert (window.facing, window.direction) == (E, E)
    assert window.cover == "cover.shutter"
    assert window.facing_degrees == 100.0
    assert window.min_level is Level.OPEN


def test_parse_window_pass_through():
    window = parse_window(
        "w1",
        {
            "area": "a1",
            "type": "pass_through",
            "name": "Fenster",
            "inner": "binary_sensor.door",
            "outer": "binary_sensor.window",
            "min_level": "ajar",
        },
    )
    assert window.config == PassThroughConfig(
        "binary_sensor.door", "binary_sensor.window"
    )
    assert set(window.kinds.values()) == {ContactKind.BINARY}
    assert window.min_level is Level.AJAR


def test_parse_window_text_mapping():
    window = parse_window(
        "w1",
        {
            "area": "a1",
            "type": "single",
            "name": "Fenster",
            "leaf": "sensor.sash",
            "mappings": {
                "sensor.sash": {
                    "closed": ["Zu"],
                    "ajar": [],
                    "tilted": ["Kipp", "tilt"],
                    "open": ["Auf"],
                }
            },
        },
    )
    assert window.kinds == {"sensor.sash": ContactKind.TEXT}
    assert window.mappings == {
        "sensor.sash": {
            Level.CLOSED: frozenset({"Zu"}),
            Level.AJAR: frozenset(),
            Level.TILTED: frozenset({"Kipp", "tilt"}),
            Level.OPEN: frozenset({"Auf"}),
        }
    }


def _room(room_id: str, area: str, side: Direction | None) -> RoomModel:
    return RoomModel(
        room_id,
        area,
        side,
        {T: ("sensor.t",), H: (), P: ()},
        (),
        timedelta(minutes=40),
        (),
    )


def _window(window_id: str, area: str, facing: str | None = None):
    data = {**SINGLE, "area": area}
    if facing is not None:
        data["facing"] = facing
    return parse_window(window_id, data)


def test_build_house_links_windows_and_resolves_directions():
    rooms = {"r2": _room("r2", "a2", None), "r1": _room("r1", "a1", S)}
    windows = {
        "w3": _window("w3", "a1", "n"),  # own facing wins
        "w1": _window("w1", "a1"),  # like the room
        "w2": _window("w2", "a2"),  # room without a side
        "w4": _window("w4", "a9"),  # no room for this area
        "w5": _window("w5", "a9", "w"),  # no room, own facing
    }
    house = build_house(SETTINGS, "weather.home", rooms, {}, windows)

    assert house.weather == "weather.home"
    assert house.rooms["r1"].window_ids == ("w1", "w3")
    assert house.rooms["r2"].window_ids == ("w2",)
    assert {
        k: (w.room_id, w.facing, w.direction) for k, w in house.windows.items()
    } == {
        "w1": ("r1", None, S),
        "w2": ("r2", None, None),
        "w3": ("r1", N, N),
        "w4": (None, None, None),
        "w5": (None, W, W),
    }


def test_build_house_is_independent_of_input_order():
    rooms = [_room("r1", "a1", S), _room("r2", "a2", N)]
    windows = [_window("w1", "a1"), _window("w2", "a2"), _window("w3", "a1")]
    regions = [
        RegionModel(
            "g1", "a3", N, {T: ("sensor.t",), H: (), P: ()}, timedelta(minutes=40)
        )
    ]

    def build(order: int):
        step = 1 if order == 0 else -1
        return build_house(
            SETTINGS,
            None,
            {r.id: r for r in rooms[::step]},
            {r.id: r for r in regions[::step]},
            {w.id: w for w in windows[::step]},
        )

    assert build(0) == build(1)
    assert list(build(1).rooms) == ["r1", "r2"]
