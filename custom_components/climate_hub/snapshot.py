"""Home Assistant states to the engine's `Snapshot` (docs/integration.md section 5).

The single-entity readers are public: the flows and the registry module use them too.
"""

import math
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import PressureConverter, TemperatureConverter

from .const import LOGGER
from .logic.cover import CoverPosition, cover_position
from .logic.engine import Contact, Forecast, Snapshot
from .logic.model import HouseModel
from .logic.outdoor import WeatherReadings
from .logic.recommendation import ClimateDevice
from .logic.sources import Metric, Reading, Status
from .logic.strategy import ForecastPoint

SUN = "sun.sun"
_CLIMATE_PREFIX = "climate."
_CELSIUS = "°C"
_HPA = "hPa"
_PERCENT = "%"
_NO_VALUE = {
    "unavailable": Status.UNAVAILABLE,
    "unknown": Status.UNKNOWN,
}


def _number(raw: Any) -> float | None:
    """A finite float from a state string or attribute, else None."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except TypeError, ValueError:
        return None
    return value if math.isfinite(value) else None


def _convert(value: float, metric: Metric, unit: str | None) -> float | None:
    """Value in the metric's unit (degC, %, hPa), None if the unit does not fit."""
    if metric is Metric.HUMIDITY:
        return value if unit == _PERCENT else None
    converter, target = (
        (TemperatureConverter, _CELSIUS)
        if metric is Metric.TEMPERATURE
        else (PressureConverter, _HPA)
    )
    try:
        return converter.convert(value, unit, target)
    except HomeAssistantError:
        return None


def _reading(
    entity_id: str,
    raw: Any,
    metric: Metric,
    unit: str | None,
    reported_at: datetime | None,
) -> Reading:
    """Reading from a raw value; `None` means the value is not there (unknown)."""
    if raw is None:
        return Reading(entity_id, None, Status.UNKNOWN, reported_at)
    if (value := _number(raw)) is None:
        return Reading(entity_id, None, Status.NOT_NUMERIC, reported_at)
    if (converted := _convert(value, metric, unit)) is None:
        return Reading(entity_id, None, Status.UNIT, reported_at)
    return Reading(entity_id, converted, Status.OK, reported_at)


def _without_value(entity_id: str, state: State | None) -> Reading | None:
    """Reading for a missing, unavailable or unknown state, else None."""
    if state is None:
        return Reading(entity_id, None, Status.MISSING, None)
    if (status := _NO_VALUE.get(state.state)) is not None:
        return Reading(entity_id, None, status, state.last_reported)
    return None


def read_reading(hass: HomeAssistant, entity_id: str, metric: Metric) -> Reading:
    """Read one source entity (sensor or climate) as `metric`."""
    state = hass.states.get(entity_id)
    if (empty := _without_value(entity_id, state)) is not None:
        return empty
    assert state is not None
    if entity_id.startswith(_CLIMATE_PREFIX):
        if metric is Metric.PRESSURE:
            return Reading(entity_id, None, Status.UNKNOWN, state.last_reported)
        if metric is Metric.TEMPERATURE:
            raw = state.attributes.get("current_temperature")
            unit = hass.config.units.temperature_unit
        else:
            raw = state.attributes.get("current_humidity")
            unit = _PERCENT
        return _reading(entity_id, raw, metric, unit, state.last_reported)
    return _reading(
        entity_id,
        state.state,
        metric,
        state.attributes.get("unit_of_measurement"),
        state.last_reported,
    )


def metric_value(hass: HomeAssistant, entity_id: str, metric: Metric) -> float | None:
    """The converted value when the reading is OK, else None."""
    reading = read_reading(hass, entity_id, metric)
    return reading.value if reading.status is Status.OK else None


def read_climate_device(hass: HomeAssistant, entity_id: str) -> ClimateDevice:
    state = hass.states.get(entity_id)
    if state is None:
        return ClimateDevice(hvac_action=None, hvac_mode=None)
    unit = hass.config.units.temperature_unit

    def temperature(attribute: str) -> float | None:
        value = _number(state.attributes.get(attribute))
        return None if value is None else _convert(value, Metric.TEMPERATURE, unit)

    return ClimateDevice(
        hvac_action=state.attributes.get("hvac_action"),
        hvac_mode=state.state,
        target=temperature("temperature"),
        target_low=temperature("target_temp_low"),
        target_high=temperature("target_temp_high"),
        current=temperature("current_temperature"),
    )


def read_contact(hass: HomeAssistant, entity_id: str) -> Contact:
    state = hass.states.get(entity_id)
    if state is None:
        return Contact(raw=None, last_changed=None)
    return Contact(raw=state.state, last_changed=state.last_changed)


def read_cover(hass: HomeAssistant, entity_id: str) -> CoverPosition | None:
    """Cover position, None while the entity has no state."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return cover_position(
        state.state, _number(state.attributes.get("current_position"))
    )


def read_weather(
    hass: HomeAssistant, entity_id: str
) -> tuple[WeatherReadings | None, float | None]:
    """Weather readings and cloud coverage; (None, None) without a state."""
    state = hass.states.get(entity_id)
    if state is None:
        return None, None
    at = state.last_reported
    if (status := _NO_VALUE.get(state.state)) is not None:
        empty = Reading(entity_id, None, status, at)
        return WeatherReadings(empty, empty, empty), None
    attrs = state.attributes
    readings = WeatherReadings(
        temperature=_reading(
            entity_id,
            attrs.get("temperature"),
            Metric.TEMPERATURE,
            attrs.get("temperature_unit"),
            at,
        ),
        humidity=_reading(
            entity_id, attrs.get("humidity"), Metric.HUMIDITY, _PERCENT, at
        ),
        pressure=_reading(
            entity_id,
            attrs.get("pressure"),
            Metric.PRESSURE,
            attrs.get("pressure_unit"),
            at,
        ),
    )
    return readings, _number(attrs.get("cloud_coverage"))


def read_sun(hass: HomeAssistant) -> tuple[float | None, float | None]:
    """Sun azimuth and elevation from `sun.sun` (I10)."""
    state = hass.states.get(SUN)
    if state is None:
        return None, None
    return (
        _number(state.attributes.get("azimuth")),
        _number(state.attributes.get("elevation")),
    )


def _contact_entities(model: HouseModel) -> set[str]:
    return {e for w in model.windows.values() for e in w.kinds}


def _source_keys(model: HouseModel) -> set[tuple[str, Metric]]:
    owners: Iterable[Any] = (*model.rooms.values(), *model.regions.values())
    return {
        (entity_id, metric)
        for owner in owners
        for metric, entity_ids in owner.sources.items()
        for entity_id in entity_ids
    }


def referenced_entities(model: HouseModel) -> set[str]:
    """Every entity the model reads; the coordinator subscribes to this set."""
    entities = {entity_id for entity_id, _ in _source_keys(model)}
    entities.update(d for room in model.rooms.values() for d in room.climate_devices)
    entities.update(_contact_entities(model))
    entities.update(w.cover for w in model.windows.values() if w.cover)
    entities.add(SUN)
    if model.weather:
        entities.add(model.weather)
    return entities


def build_snapshot(
    hass: HomeAssistant, model: HouseModel, forecast: Forecast | None
) -> Snapshot:
    """Read every referenced entity once."""
    covers = {
        w.cover: position
        for w in model.windows.values()
        if w.cover and (position := read_cover(hass, w.cover)) is not None
    }
    weather, clouds = (
        read_weather(hass, model.weather) if model.weather else (None, None)
    )
    azimuth, elevation = read_sun(hass)
    return Snapshot(
        readings={
            (entity_id, metric): read_reading(hass, entity_id, metric)
            for entity_id, metric in _source_keys(model)
        },
        contacts={e: read_contact(hass, e) for e in _contact_entities(model)},
        climate={
            device: read_climate_device(hass, device)
            for room in model.rooms.values()
            for device in room.climate_devices
        },
        covers=covers,
        weather=weather,
        clouds=clouds,
        forecast=forecast,
        sun_azimuth=azimuth,
        sun_elevation=elevation,
    )


def _forecast_point(raw: dict[str, Any], unit: str | None) -> ForecastPoint | None:
    start = dt_util.parse_datetime(str(raw.get("datetime")))
    high = _number(raw.get("temperature"))
    if start is None or high is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt_util.get_default_time_zone())
    temperature = _convert(high, Metric.TEMPERATURE, unit)
    if temperature is None:
        return None
    low = _number(raw.get("templow"))
    return ForecastPoint(
        start=start,
        temperature=temperature,
        temp_low=None if low is None else _convert(low, Metric.TEMPERATURE, unit),
    )


async def async_fetch_forecast(hass: HomeAssistant, weather_id: str) -> Forecast | None:
    """Hourly forecast if supported, else daily, else None; errors give None."""
    state = hass.states.get(weather_id)
    if state is None:
        return None
    features = state.attributes.get("supported_features", 0)
    if features & WeatherEntityFeature.FORECAST_HOURLY:
        kind = "hourly"
    elif features & WeatherEntityFeature.FORECAST_DAILY:
        kind = "daily"
    else:
        return None
    try:
        response = await hass.services.async_call(
            "weather",
            "get_forecasts",
            {"entity_id": [weather_id], "type": kind},
            blocking=True,
            return_response=True,
        )
        raw_points = response[weather_id]["forecast"]
        unit = state.attributes.get("temperature_unit")
        points = tuple(
            p for raw in raw_points if (p := _forecast_point(raw, unit)) is not None
        )
    except Exception as err:  # any provider failure means no forecast
        LOGGER.debug("Forecast of %s unavailable: %s", weather_id, err)
        return None
    return Forecast(points=points, hourly=kind == "hourly") if points else None
