"""Sensors of the room, region and hub devices (integration §8.3)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfDensity,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import ClimateHubConfigEntry, ClimateHubCoordinator
from .entity import (
    COVER_KEY,
    ClimateHubDescription,
    ClimateHubEntity,
    Scope,
    Subject,
    always,
    has_windows,
    planned,
    present,
    rounded,
)
from .entity import PARALLEL_UPDATES as PARALLEL_UPDATES
from .logic.comfort import Position, Relation, Trend
from .logic.cover import CoverAdvice
from .logic.engine import RoomResult, WindowResult
from .logic.house import HouseValue
from .logic.model import HouseModel, RoomModel, WindowModel
from .logic.outdoor import HouseOutdoor, OutdoorValue
from .logic.recommendation import Recommendation
from .logic.sources import Metric, Resolution, Stage
from .logic.strategy import Strategy, StrategyResult
from .logic.window import Level

_TEMPERATURE = SensorDeviceClass.TEMPERATURE
_HUMIDITY = SensorDeviceClass.HUMIDITY


@dataclass(frozen=True, kw_only=True)
class ClimateHubSensorDescription(SensorEntityDescription, ClimateHubDescription):
    """A sensor: how to read its value and attributes from the object's result."""

    value_fn: Callable[[Any], StateType | datetime]
    attrs_fn: Callable[[Any], Mapping[str, Any]] | None = None


def _value(item: StrEnum | None) -> str | None:
    return None if item is None else item.value


def _level(level: Level | None) -> str | None:
    """Raw state of a window level: `closed` / `ajar` / `tilted` / `open`."""
    return None if level is None else level.name.lower()


_LEVELS = [level.name.lower() for level in Level]


# Attributes (E6)


def _resolution_attrs(resolution: Resolution) -> dict[str, Any]:
    """`reason` only when not primary, `offset` only on a fallback."""
    return present(
        {
            "source": resolution.source,
            "stage": resolution.stage.value,
            "reason": None
            if resolution.stage is Stage.PRIMARY
            else _value(resolution.reason),
            "offset": rounded(resolution.offset, 2)
            if resolution.stage is Stage.FALLBACK
            else None,
        }
    )


_STAGE_ORDER = (Stage.PRIMARY, Stage.FALLBACK, Stage.NONE)


def _derived_attrs(room: RoomResult) -> dict[str, Any]:
    """Derived room value: the weaker input's attributes (humidity on a tie), no offset.

    An input's offset is not the derived value's offset.
    """
    weaker = max(
        (room.humidity, room.temperature), key=lambda r: _STAGE_ORDER.index(r.stage)
    )
    return {k: v for k, v in _resolution_attrs(weaker).items() if k != "offset"}


def _outdoor_attrs(
    value: OutdoorValue, source: Resolution | None = None
) -> dict[str, Any]:
    """Outdoor value: `reason` only without a value, `offset` only on weather."""
    own = (
        source.source
        if source is not None and source.stage in (Stage.PRIMARY, Stage.FALLBACK)
        else None
    )
    return present(
        {
            "source": own,
            "stage": value.stage.value,
            "regions": [d.value for d in value.regions] or None,
            "reason": _value(value.reason),
            "offset": rounded(value.offset, 2)
            if value.stage is Stage.WEATHER
            else None,
        }
    )


# Existence predicates (I7, I12)


def _has(metric: Metric) -> Callable[[HouseModel, Subject], bool]:
    def exists(_model: HouseModel, room: Subject) -> bool:
        assert isinstance(room, RoomModel)
        return bool(room.sources[metric])

    return exists


def _outdoor_known(model: HouseModel, _subject: Subject) -> bool:
    return bool(model.regions or model.weather)


def _humidity_and_outdoor(model: HouseModel, room: Subject) -> bool:
    return _has(Metric.HUMIDITY)(model, room) and _outdoor_known(model, room)


def _weather_known(model: HouseModel, _subject: Subject) -> bool:
    return model.weather is not None


def _any_room(model: HouseModel, _subject: Subject) -> bool:
    return bool(model.rooms)


def _options_enum(
    key: str,
    scope: Scope,
    options: Sequence[str],
    value_fn: Callable[[Any], StateType],
    *,
    attrs_fn: Callable[[Any], Mapping[str, Any]] | None = None,
    exists_fn: Callable[[HouseModel, Subject], bool] = always,
) -> ClimateHubSensorDescription:
    return ClimateHubSensorDescription(
        key=key,
        scope=scope,
        device_class=SensorDeviceClass.ENUM,
        options=list(options),
        value_fn=value_fn,
        attrs_fn=attrs_fn,
        exists_fn=exists_fn,
    )


def _enum(
    key: str,
    scope: Scope,
    enum: type[StrEnum],
    value_fn: Callable[[Any], StateType],
    *,
    attrs_fn: Callable[[Any], Mapping[str, Any]] | None = None,
    exists_fn: Callable[[HouseModel, Subject], bool] = always,
) -> ClimateHubSensorDescription:
    return _options_enum(
        key,
        scope,
        [item.value for item in enum],
        value_fn,
        attrs_fn=attrs_fn,
        exists_fn=exists_fn,
    )


def _timestamp(
    key: str,
    scope: Scope,
    value_fn: Callable[[Any], datetime | None],
    exists_fn: Callable[[HouseModel, Subject], bool] = always,
) -> ClimateHubSensorDescription:
    return ClimateHubSensorDescription(
        key=key,
        scope=scope,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=value_fn,
        exists_fn=exists_fn,
    )


def _measurement(
    key: str,
    scope: Scope,
    device_class: SensorDeviceClass,
    unit: str,
    digits: int,
    precision: int,
    value_fn: Callable[[Any], float | None],
    *,
    attrs_fn: Callable[[Any], Mapping[str, Any]] | None = None,
    exists_fn: Callable[[HouseModel, Subject], bool] = always,
) -> ClimateHubSensorDescription:
    return ClimateHubSensorDescription(
        key=key,
        scope=scope,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=unit,
        suggested_display_precision=precision,
        value_fn=lambda result: rounded(value_fn(result), digits),
        attrs_fn=attrs_fn,
        exists_fn=exists_fn,
    )


_CELSIUS = UnitOfTemperature.CELSIUS
_GRAMS = UnitOfDensity.GRAMS_PER_CUBIC_METER
_ABSOLUTE = SensorDeviceClass.ABSOLUTE_HUMIDITY
_PRESSURE = SensorDeviceClass.ATMOSPHERIC_PRESSURE
_HPA = UnitOfPressure.HPA
_ROOM = Scope.ROOM
_REGION = Scope.REGION
_HUB = Scope.HUB
_WINDOW = Scope.WINDOW


def _room_outdoor(
    key: str,
    device_class: SensorDeviceClass,
    unit: str,
    digits: int,
    precision: int,
    pick: Callable[[RoomResult], OutdoorValue],
) -> ClimateHubSensorDescription:
    return _measurement(
        key,
        _ROOM,
        device_class,
        unit,
        digits,
        precision,
        lambda room: pick(room).value,
        attrs_fn=lambda room: _outdoor_attrs(pick(room)),
        exists_fn=_outdoor_known,
    )


def _room_resolved(
    key: str,
    device_class: SensorDeviceClass,
    unit: str,
    digits: int,
    precision: int,
    pick: Callable[[RoomResult], Resolution],
    exists_fn: Callable[[HouseModel, Subject], bool] = always,
) -> ClimateHubSensorDescription:
    return _measurement(
        key,
        _ROOM,
        device_class,
        unit,
        digits,
        precision,
        lambda room: pick(room).value,
        attrs_fn=lambda room: _resolution_attrs(pick(room)),
        exists_fn=exists_fn,
    )


def _region(
    key: str,
    device_class: SensorDeviceClass,
    unit: str,
    digits: int,
    precision: int,
    metric: str,
    own: str | None,
) -> ClimateHubSensorDescription:
    """A region measurement from the direction's outdoor values (shows other stages)."""
    return _measurement(
        key,
        _REGION,
        device_class,
        unit,
        digits,
        precision,
        lambda region: getattr(region.values, metric).value,
        attrs_fn=lambda region: _outdoor_attrs(
            getattr(region.values, metric),
            getattr(region.own, own) if own else None,
        ),
    )


def _room_humidity_difference_attrs(room: RoomResult) -> dict[str, Any]:
    return present(
        {"humidity_after_ventilating": rounded(room.humidity_after_ventilating, 1)}
    )


def _window_attrs(window: WindowResult) -> dict[str, Any]:
    """`open_leaves` exists only for a double leaf, the engine leaves it empty else."""
    return present({"open_leaves": _value(window.level.open_leaves)})


def _recommendation_attrs(room: RoomResult) -> dict[str, Any]:
    return {"reason": room.recommendation.reason.value}


def _strategy_attrs(strategy: StrategyResult) -> dict[str, Any]:
    return present(
        {
            "forecast_max": rounded(strategy.f_max, 2),
            "forecast_min": rounded(strategy.f_min, 2),
            "corrected_max": rounded(strategy.corrected_f_max, 2),
            "corrected_min": rounded(strategy.corrected_f_min, 2),
            "bias_max": rounded(strategy.bias_max, 2),
            "bias_min": rounded(strategy.bias_min, 2),
        }
    )


def _indoor_attrs(indoor: HouseValue) -> dict[str, Any]:
    return present(
        {"minimum": rounded(indoor.minimum, 2), "maximum": rounded(indoor.maximum, 2)}
    )


def _house_outdoor_attrs(outdoor: HouseOutdoor) -> dict[str, Any]:
    return present(
        {
            "stage": outdoor.stage.value,
            "minimum": rounded(outdoor.minimum, 2),
            "maximum": rounded(outdoor.maximum, 2),
            "per_region": {d.value: round(v, 2) for d, v in outdoor.per_region.items()}
            or None,
        }
    )


SENSORS: tuple[ClimateHubSensorDescription, ...] = (
    # Room
    _room_resolved(
        "temperature", _TEMPERATURE, _CELSIUS, 2, 1, lambda r: r.temperature
    ),
    _room_resolved(
        "humidity",
        _HUMIDITY,
        PERCENTAGE,
        1,
        0,
        lambda r: r.humidity,
        _has(Metric.HUMIDITY),
    ),
    _room_resolved(
        "pressure",
        _PRESSURE,
        _HPA,
        1,
        0,
        lambda r: r.pressure,
        _has(Metric.PRESSURE),
    ),
    _measurement(
        "absolute_humidity",
        _ROOM,
        _ABSOLUTE,
        _GRAMS,
        2,
        1,
        lambda r: r.absolute_humidity,
        attrs_fn=_derived_attrs,
        exists_fn=_has(Metric.HUMIDITY),
    ),
    _measurement(
        "dew_point",
        _ROOM,
        _TEMPERATURE,
        _CELSIUS,
        2,
        1,
        lambda r: r.dew_point,
        attrs_fn=_derived_attrs,
        exists_fn=_has(Metric.HUMIDITY),
    ),
    _room_outdoor(
        "outside_temperature",
        _TEMPERATURE,
        _CELSIUS,
        2,
        1,
        lambda r: r.outdoor.temperature,
    ),
    _room_outdoor(
        "outside_humidity", _HUMIDITY, PERCENTAGE, 1, 0, lambda r: r.outdoor.humidity
    ),
    _measurement(
        "temperature_difference",
        _ROOM,
        SensorDeviceClass.TEMPERATURE_DELTA,
        _CELSIUS,
        2,
        1,
        lambda r: r.temperature_difference,
        exists_fn=_outdoor_known,
    ),
    _measurement(
        "humidity_difference",
        _ROOM,
        _ABSOLUTE,
        _GRAMS,
        2,
        1,
        lambda r: r.humidity_difference,
        attrs_fn=_room_humidity_difference_attrs,
        exists_fn=_humidity_and_outdoor,
    ),
    _enum(
        "outside",
        _ROOM,
        Relation,
        lambda r: _value(r.relation),
        exists_fn=_outdoor_known,
    ),
    _enum("comfort", _ROOM, Position, lambda r: _value(r.position)),
    _enum("trend", _ROOM, Trend, lambda r: _value(r.trend)),
    _enum(
        "recommendation",
        _ROOM,
        Recommendation,
        lambda r: r.recommendation.recommendation.value,
        attrs_fn=_recommendation_attrs,
    ),
    _options_enum(
        "window",
        _ROOM,
        _LEVELS,
        lambda r: _level(r.windows.level),
        exists_fn=has_windows,
    ),
    _timestamp(
        "window_open_since",
        _ROOM,
        lambda r: r.windows.open_since,
        exists_fn=has_windows,
    ),
    # Window
    _options_enum(
        "state",
        _WINDOW,
        _LEVELS,
        lambda w: _level(w.state.level),
        attrs_fn=_window_attrs,
    ),
    _timestamp("open_since", _WINDOW, lambda w: w.state.open_since),
    _enum(
        COVER_KEY,
        _WINDOW,
        CoverAdvice,
        lambda w: w.cover.advice.value,
        attrs_fn=lambda w: {"reason": w.cover.reason.value},
    ),
    # Region
    _region("temperature", _TEMPERATURE, _CELSIUS, 2, 1, "temperature", "temperature"),
    _region("humidity", _HUMIDITY, PERCENTAGE, 1, 0, "humidity", "humidity"),
    _region("pressure", _PRESSURE, _HPA, 1, 0, "pressure", "pressure"),
    _region("absolute_humidity", _ABSOLUTE, _GRAMS, 2, 1, "absolute_humidity", None),
    _region("dew_point", _TEMPERATURE, _CELSIUS, 2, 1, "dew_point", None),
    # Hub
    _enum(
        "strategy",
        _HUB,
        Strategy,
        lambda house: _value(house.strategy.strategy),
        attrs_fn=lambda house: _strategy_attrs(house.strategy),
        exists_fn=_weather_known,
    ),
    _measurement(
        "indoor_average",
        _HUB,
        _TEMPERATURE,
        _CELSIUS,
        2,
        1,
        lambda house: house.indoor.value,
        attrs_fn=lambda house: _indoor_attrs(house.indoor),
        exists_fn=_any_room,
    ),
    _measurement(
        "outdoor",
        _HUB,
        _TEMPERATURE,
        _CELSIUS,
        2,
        1,
        lambda house: house.outdoor.value,
        attrs_fn=lambda house: _house_outdoor_attrs(house.outdoor),
        exists_fn=_outdoor_known,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors of every room, region, window and the hub, per subentry."""
    coordinator = entry.runtime_data.coordinator
    by_subentry: dict[str | None, list[ClimateHubSensor]] = {}
    for description, subject in planned(coordinator.model, SENSORS):
        subentry_id = None if subject is None else subject.id
        by_subentry.setdefault(subentry_id, []).append(
            ClimateHubSensor(coordinator, description, subject)
        )
    for subentry_id, entities in by_subentry.items():
        async_add_entities(entities, config_subentry_id=subentry_id)


class ClimateHubSensor(ClimateHubEntity, SensorEntity):
    """A Climate Hub sensor."""

    entity_description: ClimateHubSensorDescription

    def __init__(
        self,
        coordinator: ClimateHubCoordinator,
        description: ClimateHubSensorDescription,
        subject: Subject,
    ) -> None:
        super().__init__(coordinator, description, subject)
        if description.key == COVER_KEY and isinstance(subject, WindowModel):
            # Per entity: only a window with a cover shows its advice at once (I6).
            self._attr_entity_registry_enabled_default = subject.cover is not None

    @property
    def native_value(self) -> StateType | datetime:
        result = self.subject_result
        return None if result is None else self.entity_description.value_fn(result)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        result = self.subject_result
        attrs_fn = self.entity_description.attrs_fn
        return None if result is None or attrs_fn is None else attrs_fn(result)
