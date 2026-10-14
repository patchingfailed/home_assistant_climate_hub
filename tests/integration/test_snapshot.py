"""Snapshot adapter: Home Assistant states to the Snapshot (integration.md 5)."""

import logging
from datetime import timedelta

import pytest
from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.climate_hub import snapshot as snap
from custom_components.climate_hub.logic import model as m
from custom_components.climate_hub.logic.cover import CoverPosition
from custom_components.climate_hub.logic.sources import Metric, Status
from tests.house import House, set_value

TEMP, HUM, PRESS = Metric.TEMPERATURE, Metric.HUMIDITY, Metric.PRESSURE


def _read(hass: HomeAssistant, entity_id: str, metric: Metric = TEMP):
    return snap.read_reading(hass, entity_id, metric)


# Sensor readings


async def test_ok_reading(hass: HomeAssistant, house: House) -> None:
    reading = _read(hass, house.living_temp)
    assert reading.entity_id == house.living_temp
    assert reading.status is Status.OK
    assert reading.value == pytest.approx(21.4)
    assert reading.reported_at == hass.states.get(house.living_temp).last_reported
    assert snap.metric_value(hass, house.living_hum, HUM) == 48


@pytest.mark.parametrize(
    ("state", "status"),
    [
        ("unavailable", Status.UNAVAILABLE),
        ("unknown", Status.UNKNOWN),
        ("zu", Status.NOT_NUMERIC),
        ("nan", Status.NOT_NUMERIC),
    ],
)
async def test_state_statuses(
    hass: HomeAssistant, house: House, state: str, status: Status
) -> None:
    set_value(hass, house.living_temp, state)
    reading = _read(hass, house.living_temp)
    assert reading.status is status
    assert reading.value is None
    assert snap.metric_value(hass, house.living_temp, TEMP) is None


async def test_missing_entity(hass: HomeAssistant, house: House) -> None:
    reading = _read(hass, "sensor.does_not_exist")
    assert reading.status is Status.MISSING
    assert reading.value is None
    assert reading.reported_at is None


async def test_unit_statuses(hass: HomeAssistant, house: House) -> None:
    set_value(hass, house.living_temp, 21, unit_of_measurement="%")
    assert _read(hass, house.living_temp).status is Status.UNIT
    set_value(hass, house.living_temp, 21, unit_of_measurement=None)
    assert _read(hass, house.living_temp).status is Status.UNIT
    set_value(hass, house.living_hum, 48, unit_of_measurement="g/m³")
    assert _read(hass, house.living_hum, HUM).status is Status.UNIT
    set_value(hass, house.living_pressure, 1000, unit_of_measurement="°C")
    assert _read(hass, house.living_pressure, PRESS).status is Status.UNIT


async def test_fahrenheit_converted(hass: HomeAssistant, house: House) -> None:
    set_value(hass, house.living_temp, 68, unit_of_measurement="°F")
    assert _read(hass, house.living_temp).value == pytest.approx(20.0)


async def test_pascal_converted(hass: HomeAssistant, house: House) -> None:
    set_value(hass, house.living_pressure, 101300, unit_of_measurement="Pa")
    assert _read(hass, house.living_pressure, PRESS).value == pytest.approx(1013.0)


async def test_last_reported_advances_on_unchanged_value(
    hass: HomeAssistant, house: House
) -> None:
    first = _read(hass, house.living_temp).reported_at
    state = hass.states.get(house.living_temp)
    hass.states.async_set(house.living_temp, state.state, state.attributes)
    second = _read(hass, house.living_temp).reported_at
    assert second > first
    assert hass.states.get(house.living_temp).last_changed == state.last_changed


# Climate


async def test_climate_reading(hass: HomeAssistant, house: House) -> None:
    temperature = _read(hass, house.living_thermostat)
    assert temperature.status is Status.OK
    assert temperature.value == pytest.approx(22.6)  # not the 21.0 setpoint
    humidity = _read(hass, house.living_thermostat, HUM)
    assert humidity.status is Status.OK
    assert humidity.value == 50


async def test_climate_missing_humidity_and_pressure(
    hass: HomeAssistant, house: House
) -> None:
    assert _read(hass, house.kitchen_thermostat, HUM).status is Status.UNKNOWN
    assert _read(hass, house.living_thermostat, PRESS).status is Status.UNKNOWN


async def test_climate_never_reads_setpoint(hass: HomeAssistant, house: House) -> None:
    attrs = dict(hass.states.get(house.living_thermostat).attributes)
    del attrs["current_temperature"]
    hass.states.async_set(house.living_thermostat, "heat", attrs)
    reading = _read(hass, house.living_thermostat)
    assert reading.status is Status.UNKNOWN
    assert reading.value is None


async def test_climate_unit_from_instance(hass: HomeAssistant, house: House) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    set_value(hass, house.living_thermostat, "heat", current_temperature=68)
    assert _read(hass, house.living_thermostat).value == pytest.approx(20.0)


async def test_climate_unavailable(hass: HomeAssistant, house: House) -> None:
    set_value(hass, house.living_thermostat, "unavailable")
    assert _read(hass, house.living_thermostat).status is Status.UNAVAILABLE


async def test_climate_device(hass: HomeAssistant, house: House) -> None:
    device = snap.read_climate_device(hass, house.living_thermostat)
    assert (device.hvac_action, device.hvac_mode) == ("heating", "heat")
    gone = snap.read_climate_device(hass, "climate.gone")
    assert (gone.hvac_action, gone.hvac_mode) == (None, None)


# Contacts, covers, weather, sun


async def test_contact(hass: HomeAssistant, house: House) -> None:
    contact = snap.read_contact(hass, house.living_leaf_1)
    assert contact.raw == "off"
    assert contact.last_changed == hass.states.get(house.living_leaf_1).last_changed
    set_value(hass, house.bath_window_text, "gekippt")
    assert snap.read_contact(hass, house.bath_window_text).raw == "gekippt"
    missing = snap.read_contact(hass, "binary_sensor.gone")
    assert (missing.raw, missing.last_changed) == (None, None)


async def test_cover(hass: HomeAssistant, house: House) -> None:
    assert snap.read_cover(hass, house.living_cover) is CoverPosition.NOT_CLOSED
    set_value(hass, house.living_cover, "closed", current_position=0)
    assert snap.read_cover(hass, house.living_cover) is CoverPosition.CLOSED
    set_value(hass, house.living_cover, "unavailable")
    assert snap.read_cover(hass, house.living_cover) is CoverPosition.UNKNOWN
    assert snap.read_cover(hass, "cover.gone") is None


async def test_weather(hass: HomeAssistant, house: House) -> None:
    readings, clouds = snap.read_weather(hass, house.weather)
    assert clouds == 90
    assert readings.temperature.status is Status.OK
    assert readings.temperature.value == 12.0
    assert readings.humidity.value == 80
    assert readings.pressure.value == 1015
    assert readings.temperature.entity_id == house.weather
    assert readings.pressure.reported_at == hass.states.get(house.weather).last_reported


async def test_weather_units(hass: HomeAssistant, house: House) -> None:
    set_value(
        hass,
        house.weather,
        "cloudy",
        temperature=50,
        temperature_unit="°F",
        pressure=29.92,
        pressure_unit="inHg",
    )
    readings, _ = snap.read_weather(hass, house.weather)
    assert readings.temperature.value == pytest.approx(10.0)
    assert readings.pressure.value == pytest.approx(1013.2, abs=0.2)


async def test_weather_incomplete(hass: HomeAssistant, house: House) -> None:
    attrs = {
        k: v
        for k, v in hass.states.get(house.weather).attributes.items()
        if k not in ("humidity", "cloud_coverage")
    }
    hass.states.async_set(house.weather, "cloudy", attrs)
    readings, clouds = snap.read_weather(hass, house.weather)
    assert clouds is None
    assert readings.humidity.status is Status.UNKNOWN
    assert readings.temperature.status is Status.OK


async def test_weather_unavailable_and_missing(
    hass: HomeAssistant, house: House
) -> None:
    set_value(hass, house.weather, "unavailable")
    readings, clouds = snap.read_weather(hass, house.weather)
    assert clouds is None
    assert readings.temperature.status is Status.UNAVAILABLE
    assert snap.read_weather(hass, "weather.gone") == (None, None)


async def test_sun(hass: HomeAssistant, house: House) -> None:
    assert snap.read_sun(hass) == (180, 35)
    hass.states.async_set(house.sun, "below_horizon", {"azimuth": 10})
    assert snap.read_sun(hass) == (10, None)
    hass.states.async_remove(house.sun)
    assert snap.read_sun(hass) == (None, None)


# Model


def _model(house: House, weather: str | None = None) -> m.HouseModel:
    settings = m.parse_settings({})
    living = m.parse_room(
        "living",
        {
            m.CONF_AREA: house.living_room,
            m.CONF_TEMPERATURE: [house.living_temp, house.living_air_temp],
            m.CONF_HUMIDITY: [house.living_hum],
            m.CONF_CLIMATE_DEVICES: [house.living_thermostat],
        },
        settings,
        {Metric.PRESSURE: [house.living_pressure]},
    )
    garden = m.parse_region(
        "garden",
        {
            m.CONF_AREA: house.garden,
            m.CONF_DIRECTION: "s",
            m.CONF_TEMPERATURE: [house.garden_temp],
            m.CONF_HUMIDITY: [house.garden_hum],
        },
        settings,
        {},
    )
    double = m.parse_window(
        "double",
        {
            m.CONF_AREA: house.living_room,
            m.CONF_TYPE: m.WINDOW_DOUBLE,
            m.CONF_LEAF_LEFT: house.living_leaf_1,
            m.CONF_LEAF_RIGHT: house.living_leaf_2,
            m.CONF_TILT: house.living_bottom,
            m.CONF_COVER: house.living_cover,
        },
    )
    pass_through = m.parse_window(
        "through",
        {
            m.CONF_AREA: house.kitchen,
            m.CONF_TYPE: m.WINDOW_PASS_THROUGH,
            m.CONF_INNER: house.kitchen_contact,
            m.CONF_OUTER: house.conservatory_window,
        },
    )
    return m.build_house(
        settings,
        weather,
        {"living": living},
        {"garden": garden},
        {"double": double, "through": pass_through},
    )


async def test_referenced_entities(hass: HomeAssistant, house: House) -> None:
    assert snap.referenced_entities(_model(house, house.weather)) == {
        house.living_temp,
        house.living_air_temp,
        house.living_hum,
        house.living_pressure,  # followed
        house.living_thermostat,
        house.garden_temp,
        house.garden_hum,
        house.living_leaf_1,
        house.living_leaf_2,
        house.living_bottom,
        house.living_cover,
        house.kitchen_contact,
        house.conservatory_window,
        house.weather,
        "sun.sun",
    }


async def test_referenced_entities_without_weather(
    hass: HomeAssistant, house: House
) -> None:
    refs = snap.referenced_entities(_model(house))
    assert house.weather not in refs
    assert "sun.sun" in refs


async def test_build_snapshot(hass: HomeAssistant, house: House) -> None:
    model = _model(house, house.weather)
    forecast = await snap.async_fetch_forecast(hass, house.weather)
    result = snap.build_snapshot(hass, model, forecast)

    assert set(result.readings) == {
        (house.living_temp, TEMP),
        (house.living_air_temp, TEMP),
        (house.living_hum, HUM),
        (house.living_pressure, PRESS),
        (house.garden_temp, TEMP),
        (house.garden_hum, HUM),
    }
    assert result.readings[(house.living_temp, TEMP)].value == pytest.approx(21.4)
    assert set(result.contacts) == {
        house.living_leaf_1,
        house.living_leaf_2,
        house.living_bottom,
        house.kitchen_contact,
        house.conservatory_window,
    }
    assert set(result.climate) == {house.living_thermostat}
    assert result.climate[house.living_thermostat].hvac_action == "heating"
    assert result.covers == {house.living_cover: CoverPosition.NOT_CLOSED}
    assert result.weather.temperature.value == 12.0
    assert result.clouds == 90
    assert result.forecast is forecast
    assert (result.sun_azimuth, result.sun_elevation) == (180, 35)


async def test_build_snapshot_missing_entities(
    hass: HomeAssistant, house: House
) -> None:
    hass.states.async_remove(house.living_cover)
    hass.states.async_remove(house.sun)
    hass.states.async_remove(house.living_temp)
    result = snap.build_snapshot(hass, _model(house, house.weather), None)
    assert house.living_cover not in result.covers
    assert result.readings[(house.living_temp, TEMP)].status is Status.MISSING
    assert result.forecast is None
    assert (result.sun_azimuth, result.sun_elevation) == (None, None)


async def test_build_snapshot_without_weather(
    hass: HomeAssistant, house: House
) -> None:
    result = snap.build_snapshot(hass, _model(house), None)
    assert result.weather is None
    assert result.clouds is None


# Forecast


async def test_forecast_hourly(hass: HomeAssistant, house: House) -> None:
    forecast = await snap.async_fetch_forecast(hass, house.weather)
    assert forecast.hourly is True
    assert len(forecast.points) == 24
    first = forecast.points[0]
    assert first.start.tzinfo is not None
    assert first.temp_low is None
    assert max(p.temperature for p in forecast.points) == 18.0


async def test_forecast_daily_only(hass: HomeAssistant, house: House) -> None:
    set_value(
        hass,
        house.weather,
        "cloudy",
        supported_features=WeatherEntityFeature.FORECAST_DAILY,
    )
    forecast = await snap.async_fetch_forecast(hass, house.weather)
    assert forecast.hourly is False
    assert len(forecast.points) == 7
    assert forecast.points[0].temperature == 18.0
    assert forecast.points[0].temp_low == 10.0


async def test_forecast_unit_converted(hass: HomeAssistant, house: House) -> None:
    set_value(hass, house.weather, "cloudy", temperature_unit="°F")
    start = dt_util.now() + timedelta(hours=1)
    house.set_forecast([{"datetime": start.isoformat(), "temperature": 68}])
    forecast = await snap.async_fetch_forecast(hass, house.weather)
    assert forecast.points[0].temperature == pytest.approx(20.0)
    assert forecast.points[0].start == start


async def test_forecast_unsupported(hass: HomeAssistant, house: House) -> None:
    set_value(hass, house.weather, "cloudy", supported_features=0)
    assert await snap.async_fetch_forecast(hass, house.weather) is None


async def test_forecast_missing_entity(hass: HomeAssistant, house: House) -> None:
    assert await snap.async_fetch_forecast(hass, "weather.gone") is None


async def test_forecast_empty(hass: HomeAssistant, house: House) -> None:
    house.set_forecast([])
    assert await snap.async_fetch_forecast(hass, house.weather) is None


async def test_forecast_failing_service(
    hass: HomeAssistant, house: House, caplog: pytest.LogCaptureFixture
) -> None:
    async def _fail(call: ServiceCall) -> dict:
        raise RuntimeError("provider down")

    hass.services.async_register(
        "weather", "get_forecasts", _fail, supports_response=SupportsResponse.ONLY
    )
    with caplog.at_level(logging.DEBUG):
        assert await snap.async_fetch_forecast(hass, house.weather) is None
    assert "provider down" in caplog.text
