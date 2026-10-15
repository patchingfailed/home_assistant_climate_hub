"""Weather check in the options flow, screen S9 (docs/integration.md 9.6)."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from ..house import House, set_value
from .conftest import suggested
from .test_options_flow import TIMING


def _input(weather: str | None = None) -> dict[str, Any]:
    return {
        **({"weather": weather} if weather else {}),
        "area_sync": False,
        "timing": {k: float(v) for k, v in TIMING.items()},
    }


async def _submit(
    hass: HomeAssistant, hub: MockConfigEntry, user_input: dict[str, Any]
) -> dict[str, Any]:
    result = await hass.config_entries.options.async_init(hub.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )


async def test_mirrored_weather_asks_before_saving_and_keep_saves(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    set_value(hass, house.weather, "cloudy", supported_features=0)
    result = await _submit(hass, hub, _input(house.weather))
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "weather_check"
    assert result["menu_options"] == ["weather_keep", "weather_adjust"]
    assert result["description_placeholders"]["status"] == (
        "Wetterdienst: 12,0 °C · 80 %, aber keine Vorhersage. "
        "Die Tagesstrategie bleibt leer."
    )
    assert "area_sync" not in hub.options  # nothing saved yet
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "weather_keep"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hub.options["weather"] == house.weather
    assert hub.options["area_sync"] is False
    assert hub.options["max_age"] == 30


async def test_unavailable_weather_asks_and_adjust_reopens_the_form(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    hass.states.async_set(house.weather, "unavailable")
    result = await _submit(hass, hub, _input(house.weather))
    assert result["step_id"] == "weather_check"
    assert result["description_placeholders"]["status"].startswith(
        "Wetterdienst: nicht verfügbar."
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "weather_adjust"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert suggested(result, "weather") == house.weather
    assert suggested(result, "area_sync") is False
    assert suggested(result, "timing.max_age") == 30
    assert "area_sync" not in hub.options

    # Corrected: no weather service, saved directly
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _input()
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "weather" not in hub.options


async def test_a_working_weather_service_saves_directly(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _submit(hass, hub, _input(house.weather))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert hub.options["weather"] == house.weather
