"""Sanity checks for the fixture house (tests/house.py)."""

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from tests.house import House, set_value


def _effective_area(hass: HomeAssistant, entity_id: str) -> str | None:
    entry = er.async_get(hass).async_get(entity_id)
    if entry.area_id:
        return entry.area_id
    if entry.device_id:
        return dr.async_get(hass).async_get(entry.device_id).area_id
    return None


async def test_effective_areas(hass: HomeAssistant, house: House) -> None:
    assert _effective_area(hass, house.living_temp) == house.living_room
    assert _effective_area(hass, house.living_cover) == house.living_room
    assert _effective_area(hass, house.kitchen_contact_temp) == house.kitchen
    assert _effective_area(hass, house.bath_window_text) == house.bathroom
    assert _effective_area(hass, house.garden_temp) == house.garden
    assert _effective_area(hass, house.loose_window) is None
    assert _effective_area(hass, house.loose_text) is None
    assert _effective_area(hass, house.template_temp) is None


async def test_states_and_registry(hass: HomeAssistant, house: House) -> None:
    state = hass.states.get(house.living_temp)
    assert state.state == "21.4"
    assert state.attributes["device_class"] == "temperature"
    assert state.attributes["unit_of_measurement"] == "°C"
    assert state.attributes["friendly_name"]

    thermostat = hass.states.get(house.living_thermostat).attributes
    assert thermostat["current_temperature"] == 22.6
    assert thermostat["hvac_action"] == "heating"
    kitchen = hass.states.get(house.kitchen_thermostat).attributes
    assert "current_humidity" not in kitchen

    text = hass.states.get(house.bath_window_text)
    assert text.state == "zu"
    assert "options" not in text.attributes
    assert "device_class" not in text.attributes

    registry = er.async_get(hass)
    plug = registry.async_get(house.plug_temp)
    assert plug.entity_category is EntityCategory.DIAGNOSTIC
    assert registry.async_get(house.template_temp).platform == "template"
    assert registry.async_get(house.fridge_temp).original_device_class == "temperature"

    assert hass.states.get(house.sun).attributes["elevation"] == 35
    assert hass.states.get(house.weather).state == "cloudy"
    assert hass.config.language == "de"


async def test_set_value_keeps_attributes(hass: HomeAssistant, house: House) -> None:
    set_value(hass, house.living_temp, 23.0)
    state = hass.states.get(house.living_temp)
    assert state.state == "23.0"
    assert state.attributes["unit_of_measurement"] == "°C"

    set_value(hass, house.living_thermostat, "heat", current_temperature=19.0)
    attrs = hass.states.get(house.living_thermostat).attributes
    assert attrs["current_temperature"] == 19.0
    assert attrs["hvac_action"] == "heating"


async def _forecast(hass: HomeAssistant, house: House) -> list[dict]:
    response = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": [house.weather], "type": "hourly"},
        blocking=True,
        return_response=True,
    )
    return response[house.weather]["forecast"]


async def test_forecast_service(hass: HomeAssistant, house: House) -> None:
    points = await _forecast(hass, house)
    assert len(points) == 24
    temperatures = [p["temperature"] for p in points]
    assert min(temperatures) >= 10.0
    assert max(temperatures) <= 18.0

    house.set_forecast([{"datetime": "2026-01-01T00:00:00+00:00", "temperature": 3.0}])
    assert len(await _forecast(hass, house)) == 1
