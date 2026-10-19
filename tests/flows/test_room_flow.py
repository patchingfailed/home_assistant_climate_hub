"""Room subentry flow, screen S6 (docs/integration.md 9.3), through the flow manager."""

from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_hub.const import DOMAIN, SUBENTRY_ROOM
from custom_components.climate_hub.flows.common import sources_selector

from ..house import House
from .conftest import field, options, suggested


async def _init(
    hass: HomeAssistant, hub: MockConfigEntry, source: str = "user", **context: Any
) -> dict[str, Any]:
    return await hass.config_entries.subentries.async_init(
        (hub.entry_id, SUBENTRY_ROOM), context={"source": source, **context}
    )


async def _configure(
    hass: HomeAssistant, result: dict[str, Any], user_input: dict[str, Any]
) -> dict[str, Any]:
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )


def _form(
    area: str,
    temperature: list[str],
    side: str = "none",
    humidity: list[str] | None = None,
    pressure: list[str] | None = None,
    climate: list[str] | None = None,
    **advanced: float | bool,
) -> dict[str, Any]:
    return {
        "area": area,
        "side": side,
        "temperature": temperature,
        "humidity_pressure": {"humidity": humidity or [], "pressure": pressure or []},
        "climate": {"climate_devices": climate or []},
        "advanced": advanced,
    }


async def _add_kitchen_preview(
    hass: HomeAssistant, hub: MockConfigEntry, house: House, side: str = "n"
) -> dict[str, Any]:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.kitchen})
    assert result["step_id"] == "room_form"
    assert result["description_placeholders"]["area"] == "Küche"
    return await _configure(
        hass,
        result,
        _form(
            house.kitchen,
            [house.kitchen_temp, house.kitchen_thermostat],
            side,
            climate=[house.kitchen_thermostat],
        ),
    )


def _room(hub: MockConfigEntry, unique_id: str) -> ConfigSubentry:
    return next(s for s in hub.subentries.values() if s.unique_id == unique_id)


async def test_add_starts_with_the_area(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert [str(k) for k in result["data_schema"].schema] == ["area"]


async def test_sources_are_rankable_in_the_form(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    """Ranking in the UI (U5) needs `reorder` on every sources selector."""
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.kitchen})
    assert result["step_id"] == "room_form"
    for name in ("temperature", "humidity_pressure.humidity"):
        config = field(result, name)[1].config
        assert config["multiple"] is True, name
        assert config["reorder"] is True, name
    assert sources_selector([]).config["reorder"] is True


async def test_add_kitchen_suggests_and_previews(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.kitchen})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "room_form"
    # Scenario 1: the climate sensor first, the thermostat last
    assert suggested(result, "temperature") == [
        house.kitchen_temp,
        house.kitchen_thermostat,
    ]
    assert suggested(result, "climate.climate_devices") == [house.kitchen_thermostat]
    assert suggested(result, "side") == "none"
    assert suggested(result, "area") == house.kitchen
    assert result["description_placeholders"]["suggested"].startswith(
        "Vorgeschlagen aus Küche. Prüfe die Reihenfolge."
    )
    assert result["description_placeholders"]["sides"] == (
        "Außenseiten: Norden Straße · Osten keine (dort hilft der Wetterdienst aus) · "
        "Süden Garten · Westen keine (dort hilft der Wetterdienst aus)."
    )
    assert field(result, "climate")[1].options["collapsed"] is False
    assert field(result, "humidity_pressure")[1].options["collapsed"] is True

    result = await _add_kitchen_preview(hass, hub, house)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "room_preview"
    assert result["menu_options"] == ["room_save", "room_adjust"]
    assert result["description_placeholders"]["area"] == "Küche"
    preview = result["description_placeholders"]["preview"]
    assert "Jetzt **20,7 °C** aus Klimasensor Temperatur (Quelle 1)." in preview
    assert "Ersatz bereit:" in preview
    assert "2. Thermostat: 21,2 °C, Abweichung wird gelernt" in preview
    assert "Feuchte 57 %, aus denselben Geräten." in preview
    assert "Außen (Norden, Straße): 13,0 °C, also 7,7 °C kälter." in preview
    assert "Kühlschrank Temperatur (6,9 °C, kein Raumwert)" in preview
    assert "Drucker Temperatur (Nebenwert eines Geräts)" in preview
    assert "Fensterkontakt Temperatur (Nebenwert eines Kontakts)" in preview
    assert preview.count("Nicht übernommen:") == 1


async def test_save_stores_exactly_the_documented_keys(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _add_kitchen_preview(hass, hub, house, side="e")
    result = await _configure(hass, result, {"next_step_id": "room_save"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Küche"
    sub = _room(hub, f"room_{house.kitchen}")
    assert sub.title == "Küche"
    assert dict(sub.data) == {
        "area": house.kitchen,
        "side": "e",
        "temperature": [house.kitchen_temp, house.kitchen_thermostat],
        "humidity": [],
        "pressure": [],
        "climate_devices": [house.kitchen_thermostat],
        "show_readings": True,
    }


async def test_max_age_is_stored_as_minutes(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.bedroom})
    result = await _configure(
        hass, result, _form(house.bedroom, [house.bedroom_temp], max_age=25.0)
    )
    result = await _configure(hass, result, {"next_step_id": "room_save"})
    data = _room(hub, f"room_{house.bedroom}").data
    assert data["max_age"] == 25
    assert isinstance(data["max_age"], int)


async def test_add_with_the_switch_off_stores_show_readings_false(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.bedroom})
    result = await _configure(
        hass,
        result,
        _form(house.bedroom, [house.bedroom_temp], show_readings=False),
    )
    result = await _configure(hass, result, {"next_step_id": "room_save"})
    assert _room(hub, f"room_{house.bedroom}").data["show_readings"] is False


async def test_new_room_form_has_the_switch_on(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.bedroom})
    marker, _ = field(result, "advanced.show_readings")
    assert marker.default() is True


async def test_reconfigure_shows_the_switch_and_stores_the_change(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    # The stored living room predates the switch: it opens on
    result = await _init(hass, hub, "reconfigure", subentry_id="room_living")
    assert suggested(result, "advanced.show_readings") is True
    sources = [house.living_temp, house.living_air_temp]
    result = await _configure(
        hass, result, _form(house.living_room, sources, show_readings=False)
    )
    result = await _configure(hass, result, {"next_step_id": "room_save"})
    assert hub.subentries["room_living"].data["show_readings"] is False

    result = await _init(hass, hub, "reconfigure", subentry_id="room_living")
    assert suggested(result, "advanced.show_readings") is False
    result = await _configure(
        hass, result, _form(house.living_room, sources, show_readings=True)
    )
    result = await _configure(hass, result, {"next_step_id": "room_save"})
    assert hub.subentries["room_living"].data["show_readings"] is True


async def test_area_change_reopens_with_new_suggestions(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.kitchen})
    # A source without an area stays, one with an area is replaced
    result = await _configure(
        hass,
        result,
        _form(house.bathroom, [house.kitchen_temp, house.template_temp], side="s"),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "room_form_changed"
    assert result["description_placeholders"]["area"] == "Bad"
    assert suggested(result, "area") == house.bathroom
    assert suggested(result, "side") == "s"
    assert suggested(result, "temperature") == [house.bath_temp, house.template_temp]
    assert suggested(result, "climate.climate_devices") == []
    # The area is stable now: the same step ID submits on to the preview
    result = await _configure(
        hass,
        result,
        _form(house.bathroom, [house.bath_temp, house.template_temp], side="s"),
    )
    assert result["step_id"] == "room_preview"
    assert (
        "Jetzt **19,9 °C** aus Klimasensor Temperatur (Quelle 1)."
        in (result["description_placeholders"]["preview"])
    )


async def test_choice_lists_hold_area_and_unassigned_entities(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.kitchen})
    choices = field(result, "temperature")[1].config["include_entities"]
    assert house.kitchen_temp in choices
    assert house.kitchen_thermostat in choices
    assert house.template_temp in choices  # no area
    assert house.bath_temp not in choices  # another area
    humidity = field(result, "humidity_pressure.humidity")[1].config["include_entities"]
    assert house.kitchen_hum in humidity
    assert house.bath_hum not in humidity


async def test_adjust_returns_to_the_form_with_the_entered_data(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _add_kitchen_preview(hass, hub, house, side="w")
    result = await _configure(hass, result, {"next_step_id": "room_adjust"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "room_form"
    assert suggested(result, "side") == "w"
    assert suggested(result, "temperature") == [
        house.kitchen_temp,
        house.kitchen_thermostat,
    ]


async def test_errors_on_the_area_step(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.living_room})
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "already_room"}
    assert result["description_placeholders"]["area"] == "Wohnzimmer"
    result = await _configure(hass, result, {"area": house.street})
    assert result["errors"] == {"base": "is_region"}
    assert result["description_placeholders"]["area"] == "Straße"
    result = await _configure(hass, result, {"area": house.kitchen})
    assert result["step_id"] == "room_form"


async def test_errors_on_the_form(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.kitchen})
    result = await _configure(hass, result, _form(house.kitchen, []))
    assert result["step_id"] == "room_form"
    assert result["errors"] == {"base": "no_temperature"}
    result = await _configure(
        hass, result, _form(house.living_room, [house.kitchen_temp])
    )
    assert result["step_id"] == "room_form"
    assert result["errors"] == {"base": "already_room"}
    result = await _configure(hass, result, _form(house.garden, [house.kitchen_temp]))
    assert result["errors"] == {"base": "is_region"}
    assert result["description_placeholders"]["area"] == "Garten"
    result = await _configure(hass, result, _form(house.kitchen, [house.kitchen_temp]))
    assert result["step_id"] == "room_preview"


async def test_reconfigure_opens_the_form_and_updates(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub, "reconfigure", subentry_id="room_living")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "room_form"
    assert suggested(result, "area") == house.living_room
    assert suggested(result, "side") == "n"
    assert suggested(result, "climate.climate_devices") == [house.living_thermostat]
    assert result["description_placeholders"]["suggested"] == ""
    assert result["description_placeholders"]["area"] == "Wohnzimmer"
    assert field(result, "climate")[1].options["collapsed"] is True

    result = await _configure(
        hass,
        result,
        _form(
            house.living_room,
            [house.living_temp, house.living_air_temp, house.living_thermostat],
            side="s",
            climate=[],
            max_age=30,
        ),
    )
    assert result["step_id"] == "room_preview"
    preview = result["description_placeholders"]["preview"]
    assert "Jetzt **21,4 °C** aus Klimasensor Temperatur (Quelle 1)." in preview
    assert "2. Luftmesser Temperatur: 21,7 °C, Abweichung wird gelernt" in preview
    assert "3. Thermostat: 22,6 °C, Abweichung wird gelernt" in preview
    assert "Feuchte 48 % · Luftdruck 1012 hPa, aus denselben Geräten." in preview
    assert "Außen (Süden, Garten): 12,5 °C, also 8,9 °C kälter." in preview
    assert "Nicht übernommen" not in preview

    result = await _configure(hass, result, {"next_step_id": "room_save"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    sub = hub.subentries["room_living"]
    assert dict(sub.data) == {
        "area": house.living_room,
        "side": "s",
        "temperature": [
            house.living_temp,
            house.living_air_temp,
            house.living_thermostat,
        ],
        "humidity": [],
        "pressure": [],
        "climate_devices": [],
        "show_readings": True,
        "max_age": 30,
    }
    assert sub.title == "Wohnzimmer"
    assert sub.unique_id == f"room_{house.living_room}"


async def test_reconfigure_with_another_area_updates_title_and_unique_id(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub, "reconfigure", subentry_id="room_living")
    result = await _configure(
        hass, result, _form(house.bedroom, [house.living_temp], side="n")
    )
    assert result["step_id"] == "room_form_changed"
    assert suggested(result, "temperature") == [house.bedroom_temp]
    result = await _configure(
        hass, result, _form(house.bedroom, [house.bedroom_temp], side="n")
    )
    assert result["step_id"] == "room_preview"
    assert "Nicht übernommen" not in result["description_placeholders"]["preview"]
    result = await _configure(hass, result, {"next_step_id": "room_save"})
    assert result["type"] is FlowResultType.ABORT
    sub = hub.subentries["room_living"]
    assert sub.title == "Schlafzimmer"
    assert sub.unique_id == f"room_{house.bedroom}"
    assert sub.data["area"] == house.bedroom


async def test_reconfigure_may_keep_its_own_area(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub, "reconfigure", subentry_id="room_living")
    result = await _configure(
        hass, result, _form(house.living_room, [house.living_temp], side="n")
    )
    assert result["step_id"] == "room_preview"


async def test_side_options_cover_all_directions_and_none(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.kitchen})
    assert options(result, "side") == ["n", "e", "s", "w", "none"]


async def test_preview_without_a_loaded_hub_uses_defaults(
    hass: HomeAssistant, house: House
) -> None:
    """The first-setup situation: empty state, fetched forecast, no coordinator."""
    entry = MockConfigEntry(domain=DOMAIN, options={"weather": house.weather})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ROOM), context={"source": "user"}
    )
    result = await _configure(hass, result, {"area": house.kitchen})
    result = await _configure(
        hass, result, _form(house.kitchen, [house.kitchen_temp], side="n")
    )
    preview = result["description_placeholders"]["preview"]
    assert "Jetzt **20,7 °C** aus Klimasensor Temperatur (Quelle 1)." in preview
    assert "Außen (Wetterdienst): 12,0 °C, also 8,7 °C kälter." in preview
