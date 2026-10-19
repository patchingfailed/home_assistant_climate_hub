"""Pure configuration model and parsers (docs/integration.md §3).

The adapter turns options and subentry data into these types; the engine only sees
the types. Follow resolution (R3) needs the registries and stays in the adapter: it
passes the followed entities of each metric in.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from . import const
from .outdoor import Direction
from .sources import Metric
from .window import (
    ContactKind,
    FrameConfig,
    Level,
    PassThroughConfig,
    WindowConfig,
)

# Hub options (§3.1)
CONF_WEATHER = "weather"
CONF_AREA_SYNC = "area_sync"
CONF_MAX_AGE = "max_age"
CONF_BURST_DURATION = "burst_duration"
CONF_HUMIDITY_THRESHOLD = "humidity_threshold"
CONF_REPAIR_DELAY = "repair_delay"

# Subentry data (§3.2)
CONF_AREA = "area"
CONF_SIDE = "side"
CONF_DIRECTION = "direction"
CONF_TEMPERATURE = "temperature"
CONF_HUMIDITY = "humidity"
CONF_PRESSURE = "pressure"
CONF_CLIMATE_DEVICES = "climate_devices"
CONF_SHOW_READINGS = "show_readings"
CONF_TYPE = "type"
CONF_NAME = "name"
CONF_LEAF = "leaf"
CONF_LEAF_LEFT = "leaf_left"
CONF_LEAF_RIGHT = "leaf_right"
CONF_TILT = "tilt"
CONF_HANDLE = "handle"
CONF_INNER = "inner"
CONF_OUTER = "outer"
CONF_MAPPINGS = "mappings"
CONF_COVER = "cover"
CONF_FACING = "facing"
CONF_FACING_DEGREES = "facing_degrees"
CONF_MIN_LEVEL = "min_level"

# Values
SIDE_NONE = "none"
WINDOW_SINGLE = "single"
WINDOW_DOUBLE = "double"
WINDOW_PASS_THROUGH = "pass_through"
FACING_ROOM = "room"
MIN_LEVEL_AJAR = "ajar"
MIN_LEVEL_TILTED = "tilted"
MIN_LEVEL_OPEN = "open"

_BINARY_PREFIX = "binary_sensor."


@dataclass(frozen=True, slots=True)
class Settings:
    """Hub options converted to timedelta and float."""

    max_age: timedelta
    burst_duration: timedelta
    humidity_threshold: float
    repair_delay: timedelta


@dataclass(frozen=True, slots=True)
class RoomModel:
    id: str  # subentry ID
    area_id: str
    side: Direction | None
    sources: Mapping[Metric, tuple[str, ...]]  # "follow" already expanded (R3)
    climate_devices: tuple[str, ...]
    max_age: timedelta  # own override or the hub value
    window_ids: tuple[str, ...]
    show_readings: bool = True  # R16: spread entities with per-source readings


@dataclass(frozen=True, slots=True)
class RegionModel:
    id: str
    area_id: str
    direction: Direction
    sources: Mapping[Metric, tuple[str, ...]]
    max_age: timedelta


@dataclass(frozen=True, slots=True)
class WindowModel:
    id: str
    name: str
    area_id: str
    room_id: str | None  # None: no room for this area (W11)
    config: WindowConfig
    kinds: Mapping[str, ContactKind]
    mappings: Mapping[str, Mapping[Level, frozenset[str]]]
    cover: str | None
    facing: Direction | None  # the window's own facing, None: like the room
    direction: Direction | None  # facing resolved: own, else the room's side
    facing_degrees: float | None
    min_level: Level


@dataclass(frozen=True, slots=True)
class HouseModel:
    settings: Settings
    weather: str | None
    rooms: Mapping[str, RoomModel]
    regions: Mapping[str, RegionModel]
    windows: Mapping[str, WindowModel]


def _duration(
    options: Mapping[str, Any], key: str, unit: str, default: timedelta
) -> timedelta:
    return timedelta(**{unit: options[key]}) if key in options else default


def parse_settings(options: Mapping[str, Any]) -> Settings:
    """Hub options with defaults; minutes and hours become timedelta."""
    return Settings(
        max_age=_duration(options, CONF_MAX_AGE, "minutes", const.DEFAULT_MAX_AGE),
        burst_duration=_duration(
            options, CONF_BURST_DURATION, "minutes", const.DEFAULT_BURST_DURATION
        ),
        humidity_threshold=float(
            options.get(CONF_HUMIDITY_THRESHOLD, const.DEFAULT_HUMIDITY_THRESHOLD)
        ),
        repair_delay=_duration(
            options, CONF_REPAIR_DELAY, "hours", const.DEFAULT_REPAIR_DELAY
        ),
    )


def _max_age(data: Mapping[str, Any], settings: Settings) -> timedelta:
    minutes = data.get(CONF_MAX_AGE)
    return settings.max_age if minutes is None else timedelta(minutes=minutes)


def _sources(
    data: Mapping[str, Any], followed: Mapping[Metric, Sequence[str]]
) -> dict[Metric, tuple[str, ...]]:
    """Temperature as configured; an empty humidity or pressure list follows (R3)."""
    sources = {Metric.TEMPERATURE: tuple(data[CONF_TEMPERATURE])}
    for metric, key in (
        (Metric.HUMIDITY, CONF_HUMIDITY),
        (Metric.PRESSURE, CONF_PRESSURE),
    ):
        sources[metric] = tuple(data.get(key) or followed.get(metric, ()))
    return sources


def parse_room(
    room_id: str,
    data: Mapping[str, Any],
    settings: Settings,
    followed: Mapping[Metric, Sequence[str]],
) -> RoomModel:
    """Room subentry; windows are linked by `build_house`."""
    side = data.get(CONF_SIDE, SIDE_NONE)
    return RoomModel(
        id=room_id,
        area_id=data[CONF_AREA],
        side=None if side == SIDE_NONE else Direction(side),
        sources=_sources(data, followed),
        climate_devices=tuple(data.get(CONF_CLIMATE_DEVICES, ())),
        max_age=_max_age(data, settings),
        window_ids=(),
        show_readings=bool(data.get(CONF_SHOW_READINGS, True)),
    )


def parse_region(
    region_id: str,
    data: Mapping[str, Any],
    settings: Settings,
    followed: Mapping[Metric, Sequence[str]],
) -> RegionModel:
    return RegionModel(
        id=region_id,
        area_id=data[CONF_AREA],
        direction=Direction(data[CONF_DIRECTION]),
        sources=_sources(data, followed),
        max_age=_max_age(data, settings),
    )


def _window_config(data: Mapping[str, Any]) -> WindowConfig:
    kind = data[CONF_TYPE]
    if kind == WINDOW_PASS_THROUGH:
        return PassThroughConfig(inner=data[CONF_INNER], outer=data[CONF_OUTER])
    leaves = (
        (data[CONF_LEAF_LEFT], data[CONF_LEAF_RIGHT])
        if kind == WINDOW_DOUBLE
        else (data[CONF_LEAF],)
    )
    return FrameConfig(
        leaves=leaves, tilt=data.get(CONF_TILT), handle=data.get(CONF_HANDLE)
    )


def _contacts(config: WindowConfig) -> tuple[str, ...]:
    if isinstance(config, PassThroughConfig):
        return (config.inner, config.outer)
    return (*config.leaves, *(e for e in (config.tilt, config.handle) if e))


def parse_window(window_id: str, data: Mapping[str, Any]) -> WindowModel:
    """Window subentry; the room and the resolved direction come from `build_house`."""
    config = _window_config(data)
    facing = data.get(CONF_FACING, FACING_ROOM)
    own = None if facing == FACING_ROOM else Direction(facing)
    return WindowModel(
        id=window_id,
        name=data[CONF_NAME],
        area_id=data[CONF_AREA],
        room_id=None,
        config=config,
        kinds={
            entity_id: (
                ContactKind.BINARY
                if entity_id.startswith(_BINARY_PREFIX)
                else ContactKind.TEXT
            )
            for entity_id in _contacts(config)
        },
        mappings={
            entity_id: {
                Level[name.upper()]: frozenset(texts) for name, texts in levels.items()
            }
            for entity_id, levels in data.get(CONF_MAPPINGS, {}).items()
        },
        cover=data.get(CONF_COVER),
        facing=own,
        direction=own,
        facing_degrees=data.get(CONF_FACING_DEGREES),
        min_level=Level[data.get(CONF_MIN_LEVEL, MIN_LEVEL_TILTED).upper()],
    )


def build_house(
    settings: Settings,
    weather: str | None,
    rooms: Mapping[str, RoomModel],
    regions: Mapping[str, RegionModel],
    windows: Mapping[str, WindowModel],
) -> HouseModel:
    """Link windows to rooms by area and resolve their directions (W1, SH4)."""
    room_by_area = {room.area_id: room for _, room in sorted(rooms.items())}
    linked: dict[str, WindowModel] = {}
    for window_id, window in sorted(windows.items()):
        room = room_by_area.get(window.area_id)
        linked[window_id] = replace(
            window,
            room_id=None if room is None else room.id,
            direction=window.facing
            if window.facing is not None or room is None
            else room.side,
        )
    return HouseModel(
        settings=settings,
        weather=weather,
        rooms={
            room_id: replace(
                room,
                window_ids=tuple(w.id for w in linked.values() if w.room_id == room_id),
            )
            for room_id, room in sorted(rooms.items())
        },
        regions=dict(sorted(regions.items())),
        windows=linked,
    )
