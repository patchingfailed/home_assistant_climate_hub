"""Outdoor side flow, screen S7 (docs/integration.md 9.4), through the flow manager."""

from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_hub.const import SUBENTRY_REGION

from ..house import House
from .conftest import options, suggested


async def _init(
    hass: HomeAssistant, hub: MockConfigEntry, source: str = "user", **context: Any
) -> dict[str, Any]:
    return await hass.config_entries.subentries.async_init(
        (hub.entry_id, SUBENTRY_REGION), context={"source": source, **context}
    )


async def _configure(
    hass: HomeAssistant, result: dict[str, Any], user_input: dict[str, Any]
) -> dict[str, Any]:
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )


def _form(
    direction: str,
    area: str,
    temperature: list[str],
    humidity: list[str] | None = None,
    pressure: list[str] | None = None,
    **advanced: int,
) -> dict[str, Any]:
    return {
        "direction": direction,
        "area": area,
        "temperature": temperature,
        "humidity_pressure": {"humidity": humidity or [], "pressure": pressure or []},
        "advanced": advanced,
    }


def _region(hub: MockConfigEntry, unique_id: str) -> ConfigSubentry:
    return next(s for s in hub.subentries.values() if s.unique_id == unique_id)


async def _add_yard_preview(
    hass: HomeAssistant, hub: MockConfigEntry, house: House
) -> dict[str, Any]:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"direction": "e", "area": house.yard})
    assert result["step_id"] == "region_form"
    assert result["description_placeholders"]["direction"] == "Osten"
    return await _configure(hass, result, _form("e", house.yard, [house.yard_temp]))


async def test_add_offers_only_free_directions(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert [str(k) for k in result["data_schema"].schema] == ["direction", "area"]
    assert options(result, "direction") == ["e", "w"]


async def test_add_suggests_previews_with_the_chain_and_saves(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"direction": "e", "area": house.yard})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "region_form"
    assert suggested(result, "direction") == "e"
    assert suggested(result, "area") == house.yard
    assert suggested(result, "temperature") == [house.yard_temp]
    assert options(result, "direction") == ["e", "w"]
    assert "climate" not in [str(k) for k in result["data_schema"].schema]

    result = await _configure(hass, result, _form("e", house.yard, [house.yard_temp]))
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "region_preview"
    assert result["menu_options"] == ["region_save", "region_adjust"]
    assert result["description_placeholders"]["area"] == "Hof"
    preview = result["description_placeholders"]["preview"]
    assert "Jetzt **14,5 °C** aus Außensensor Temperatur (Quelle 1)." in preview
    assert "Keine Feuchte- und Luftdruckquelle." in preview
    assert (
        "Fällt Osten aus, springen Norden (Straße) und Süden (Garten) ein, "
        "dann der Wetterdienst."
    ) in preview

    result = await _configure(hass, result, {"next_step_id": "region_save"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Osten · Hof"
    sub = _region(hub, "region_e")
    assert sub.title == "Osten · Hof"
    assert dict(sub.data) == {
        "area": house.yard,
        "direction": "e",
        "temperature": [house.yard_temp],
        "humidity": [],
        "pressure": [],
    }


async def test_chain_names_the_opposite_side_and_the_weather(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"direction": "w", "area": house.yard})
    result = await _configure(hass, result, _form("w", house.yard, [house.yard_temp]))
    preview = result["description_placeholders"]["preview"]
    assert (
        "Fällt Westen aus, springen Norden (Straße) und Süden (Garten) ein, "
        "dann der Wetterdienst."
    ) in preview


async def test_preview_names_humidity_and_pressure_sources(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub, "reconfigure", subentry_id="region_south")
    result = await _configure(
        hass,
        result,
        _form(
            "s",
            house.garden,
            [house.garden_temp],
            humidity=[house.garden_hum],
            pressure=[house.garden_pressure],
        ),
    )
    preview = result["description_placeholders"]["preview"]
    assert "Jetzt **12,5 °C** aus Außensensor Temperatur (Quelle 1)." in preview
    assert (
        "Feuchte 76 % aus Außensensor Luftfeuchtigkeit · "
        "Luftdruck 1013 hPa aus Außensensor Druck."
    ) in preview
    assert "Fällt Süden aus, springt Norden (Straße) ein, dann der Wetterdienst." in (
        preview
    )


async def test_adjust_returns_to_the_form(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _add_yard_preview(hass, hub, house)
    result = await _configure(hass, result, {"next_step_id": "region_adjust"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "region_form"
    assert suggested(result, "temperature") == [house.yard_temp]


async def test_area_change_reopens_with_new_suggestions(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"direction": "e", "area": house.yard})
    result = await _configure(
        hass, result, _form("e", house.bathroom, [house.yard_temp])
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "region_form_changed"
    assert result["description_placeholders"]["area"] == "Bad"
    assert result["description_placeholders"]["direction"] == "Osten"
    assert suggested(result, "area") == house.bathroom
    assert suggested(result, "temperature") == [house.bath_temp]
    result = await _configure(
        hass, result, _form("e", house.bathroom, [house.bath_temp])
    )
    assert result["step_id"] == "region_preview"


async def test_errors_on_the_first_step(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"direction": "e", "area": house.street})
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "already_region"}
    assert result["description_placeholders"] == {
        "area": "Straße",
        "direction": "Norden",
    }
    result = await _configure(
        hass, result, {"direction": "e", "area": house.living_room}
    )
    assert result["errors"] == {"base": "is_room"}
    assert result["description_placeholders"]["area"] == "Wohnzimmer"
    result = await _configure(hass, result, {"direction": "e", "area": house.yard})
    assert result["step_id"] == "region_form"


async def test_errors_on_the_form(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"direction": "e", "area": house.yard})
    result = await _configure(hass, result, _form("e", house.yard, []))
    assert result["step_id"] == "region_form"
    assert result["errors"] == {"base": "no_temperature"}
    result = await _configure(hass, result, _form("e", house.street, [house.yard_temp]))
    assert result["errors"] == {"base": "already_region"}
    result = await _configure(
        hass, result, _form("e", house.living_room, [house.yard_temp])
    )
    assert result["errors"] == {"base": "is_room"}
    # The direction becomes taken while the flow is open (the safeguard)
    flow_id = result["flow_id"]
    hass.config_entries.async_add_subentry(
        hub,
        ConfigSubentry(
            subentry_type=SUBENTRY_REGION,
            title="Osten · Terrasse",
            unique_id="region_e",
            data={
                "area": house.conservatory,
                "direction": "e",
                "temperature": [house.yard_temp],
                "humidity": [],
                "pressure": [],
            },
        ),
    )
    result = await hass.config_entries.subentries.async_configure(
        flow_id, _form("e", house.yard, [house.yard_temp])
    )
    assert result["errors"] == {"base": "direction_taken"}
    placeholders = result["description_placeholders"]
    assert placeholders["direction"] == "Osten"
    assert placeholders["area"] == "Wintergarten"


async def test_reconfigure_updates_data_title_and_unique_id(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub, "reconfigure", subentry_id="region_north")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "region_form"
    assert result["description_placeholders"]["direction"] == "Norden"
    assert suggested(result, "direction") == "n"
    assert suggested(result, "area") == house.street
    assert suggested(result, "temperature") == [house.street_temp]
    assert suggested(result, "humidity_pressure.humidity") == [house.street_hum]
    assert options(result, "direction") == ["n", "e", "w"]

    result = await _configure(
        hass,
        result,
        _form(
            "w",
            house.street,
            [house.street_temp],
            humidity=[house.street_hum],
            max_age=20,
        ),
    )
    assert result["step_id"] == "region_preview"
    result = await _configure(hass, result, {"next_step_id": "region_save"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    sub = hub.subentries["region_north"]
    assert sub.title == "Westen · Straße"
    assert sub.unique_id == "region_w"
    assert dict(sub.data) == {
        "area": house.street,
        "direction": "w",
        "temperature": [house.street_temp],
        "humidity": [house.street_hum],
        "pressure": [],
        "max_age": 20,
    }


async def test_reconfigure_may_keep_its_own_direction_and_area(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub, "reconfigure", subentry_id="region_north")
    result = await _configure(
        hass, result, _form("n", house.street, [house.street_temp])
    )
    assert result["step_id"] == "region_preview"
