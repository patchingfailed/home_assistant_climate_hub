"""Windows and the weather line in the first setup (docs/integration.md 9.2, S4)."""

from typing import Any

from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType

from custom_components.climate_hub.const import DOMAIN, SUBENTRY_WINDOW

from ..house import House, set_value
from .conftest import options, suggested
from .test_config_flow import (
    _checked_rooms,
    _configure,
    _plan,
    _start,
    _to_preview,
)

# Weather line (S4)


def _weather_line(result: dict[str, Any]) -> str:
    lines = result["description_placeholders"]["preview"].split("\n\n")
    return next(
        line
        for line in lines
        if line.startswith(("Wetterdienst:", "Kein Wetterdienst"))
    )


async def test_weather_line_with_an_hourly_forecast_fetches_once(
    hass: HomeAssistant, house: House
) -> None:
    calls = []

    async def fetch(call: ServiceCall) -> dict[str, Any]:
        calls.append(call.data["type"])
        return {
            entity_id: {"forecast": house._forecasts[call.data["type"]]}
            for entity_id in call.data["entity_id"]
        }

    hass.services.async_register(
        "weather", "get_forecasts", fetch, supports_response=SupportsResponse.ONLY
    )
    result = await _to_preview(hass, house)
    assert (
        _weather_line(result) == "Wetterdienst: 12,0 °C · 80 %, Vorhersage stündlich."
    )
    assert calls == ["hourly"]


async def test_weather_line_with_a_daily_forecast(
    hass: HomeAssistant, house: House
) -> None:
    set_value(
        hass,
        house.weather,
        "cloudy",
        supported_features=WeatherEntityFeature.FORECAST_DAILY,
    )
    result = await _to_preview(hass, house)
    assert _weather_line(result) == "Wetterdienst: 12,0 °C · 80 %, Vorhersage täglich."


async def test_weather_line_of_a_mirrored_entity(
    hass: HomeAssistant, house: House
) -> None:
    set_value(hass, house.weather, "cloudy", supported_features=0)
    result = await _to_preview(hass, house)
    assert _weather_line(result) == (
        "Wetterdienst: 12,0 °C · 80 %, aber keine Vorhersage. "
        "Die Tagesstrategie bleibt leer."
    )


async def test_weather_line_without_humidity_shows_the_temperature_only(
    hass: HomeAssistant, house: House
) -> None:
    hass.states.async_set(
        house.weather,
        "cloudy",
        {"temperature": 12.0, "temperature_unit": "°C", "supported_features": 0},
    )
    result = await _to_preview(hass, house)
    assert _weather_line(result) == (
        "Wetterdienst: 12,0 °C, aber keine Vorhersage. Die Tagesstrategie bleibt leer."
    )


async def test_weather_line_of_an_unavailable_entity(
    hass: HomeAssistant, house: House
) -> None:
    hass.states.async_set(house.weather, "unavailable")
    result = await _to_preview(hass, house)
    assert _weather_line(result) == (
        "Wetterdienst: nicht verfügbar. Fallen alle Außensensoren aus, fehlen "
        "Außenwerte, und die Tagesstrategie bleibt leer."
    )


async def test_weather_line_without_a_weather_entity(
    hass: HomeAssistant, house: House
) -> None:
    result = await _start(hass)
    result = await _configure(hass, result, {"area_sync": True})
    result = await _configure(hass, result, {"rooms": [house.living_room]})
    result = await _configure(hass, result, _plan())
    assert _weather_line(result) == (
        "Kein Wetterdienst gewählt. Die Tagesstrategie bleibt leer."
    )


# Windows (S4, S8)


def _single(area: str, leaf: str, **extra: Any) -> dict[str, Any]:
    return {
        "area": area,
        "leaf": leaf,
        "show_all": False,
        "extra_contacts": {},
        "cover": {},
        "advanced": {},
        **extra,
    }


async def _add_window(
    hass: HomeAssistant,
    result: dict[str, Any],
    area: str,
    step: str,
    form: dict[str, Any],
) -> dict[str, Any]:
    result = await _configure(hass, result, {"next_step_id": "add_window"})
    assert result["step_id"] == "window_room"
    result = await _configure(hass, result, {"area": area})
    assert result["step_id"] == "window_type"
    result = await _configure(hass, result, {"next_step_id": step})
    assert result["step_id"] == step
    result = await _configure(hass, result, form)
    assert result["step_id"] == "window_preview"
    return result


async def _save(hass: HomeAssistant, result: dict[str, Any]) -> dict[str, Any]:
    result = await _configure(hass, result, {"next_step_id": "window_save"})
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "preview"
    return result


async def test_preview_without_windows_says_why_they_help(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_preview(hass, house)
    preview = result["description_placeholders"]["preview"]
    assert "**Fenster**" in preview
    assert (
        "Noch keine. Mit Fenstern siehst du, was gerade offen ist, und bekommst "
        "Warnungen."
    ) in preview


async def test_window_loop_numbers_and_creates_the_subentries(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_preview(hass, house)
    result = await _configure(hass, result, {"next_step_id": "add_window"})
    assert result["step_id"] == "window_room"
    offered = {o["value"]: o["label"] for o in options(result, "area")}
    assert set(offered) == _checked_rooms(house)  # the rooms of this setup
    assert offered[house.kitchen] == "Küche"

    result = await _configure(hass, result, {"area": house.kitchen})
    assert result["menu_options"] == [
        "window_single",
        "window_double",
        "window_pass_through",
    ]
    result = await _configure(hass, result, {"next_step_id": "window_single"})
    result = await _configure(
        hass, result, _single(house.kitchen, house.kitchen_contact)
    )
    preview = result["description_placeholders"]["preview"]
    assert "Name: Küche Fenster, nach dem Raum benannt." in preview
    assert "wird mit angelegt" not in preview
    assert "Gerade **zu**." in preview
    result = await _save(hass, result)
    preview = result["description_placeholders"]["preview"]
    assert "- Küche Fenster: zu" in preview
    assert "Noch keine." not in preview

    # The second window of the room is numbered; it is open
    set_value(hass, house.loose_window, "on")
    result = await _add_window(
        hass,
        result,
        house.kitchen,
        "window_single",
        _single(house.kitchen, house.loose_window),
    )
    assert result["description_placeholders"]["title"] == "Küche Fenster 2"
    result = await _save(hass, result)
    preview = result["description_placeholders"]["preview"]
    assert "- Küche Fenster: zu" in preview
    assert "- Küche Fenster 2: offen" in preview

    result = await _configure(hass, result, {"next_step_id": "create"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    windows = [s for s in result["subentries"] if s["subentry_type"] == SUBENTRY_WINDOW]
    assert [(w["title"], w["unique_id"], w["data"]) for w in windows] == [
        (
            "Küche Fenster",
            None,
            {
                "area": house.kitchen,
                "type": "single",
                "name": "Fenster",
                "leaf": house.kitchen_contact,
                "facing": "room",
                "min_level": "tilted",
            },
        ),
        (
            "Küche Fenster 2",
            None,
            {
                "area": house.kitchen,
                "type": "single",
                "name": "Fenster 2",
                "leaf": house.loose_window,
                "facing": "room",
                "min_level": "tilted",
            },
        ),
    ]
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    assert len(entry.subentries) == 10  # 5 rooms, 3 sides, 2 windows


async def test_window_preview_adjust_returns_to_the_form(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_preview(hass, house)
    result = await _add_window(
        hass,
        result,
        house.study,
        "window_pass_through",
        {
            "area": house.study,
            "inner": house.study_door,
            "show_all": False,
            "outer": house.conservatory_window,
            "cover": {},
            "advanced": {},
        },
    )
    result = await _configure(hass, result, {"next_step_id": "window_adjust"})
    assert result["step_id"] == "window_pass_through"
    assert suggested(result, "outer") == house.conservatory_window


async def test_removing_a_room_drops_its_windows(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_preview(hass, house)
    result = await _add_window(
        hass,
        result,
        house.kitchen,
        "window_single",
        _single(house.kitchen, house.kitchen_contact),
    )
    result = await _save(hass, result)
    result = await _add_window(
        hass,
        result,
        house.living_room,
        "window_single",
        _single(house.living_room, house.living_leaf_1),
    )
    result = await _save(hass, result)
    assert "Küche Fenster: zu" in result["description_placeholders"]["preview"]

    result = await _configure(hass, result, {"next_step_id": "rooms"})
    kept = set(suggested(result, "rooms")) - {house.kitchen}
    result = await _configure(hass, result, {"rooms": list(kept)})
    assert result["step_id"] == "plan"
    result = await _configure(hass, result, _plan(n={"outdoor": house.street}))
    preview = result["description_placeholders"]["preview"]
    assert "Küche Fenster" not in preview
    assert "- Wohnzimmer Fenster: zu" in preview
    result = await _configure(hass, result, {"next_step_id": "create"})
    windows = [s for s in result["subentries"] if s["subentry_type"] == SUBENTRY_WINDOW]
    assert [w["title"] for w in windows] == ["Wohnzimmer Fenster"]
