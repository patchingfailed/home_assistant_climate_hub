"""First setup, screens S1-S4 and create (docs/integration.md 9.2)."""

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.climate_hub.const import DOMAIN, SUBENTRY_REGION, SUBENTRY_ROOM

from ..house import House
from .conftest import field, options, suggested


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})


async def _configure(
    hass: HomeAssistant, result: dict[str, Any], user_input: dict[str, Any]
) -> dict[str, Any]:
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


def _values(result: dict[str, Any], name: str) -> list[str]:
    return [o["value"] for o in options(result, name)]


def _plan(**sides: dict[str, Any]) -> dict[str, Any]:
    return {d: sides.get(d, {}) for d in "nesw"}


def _default_plan(house: House) -> dict[str, Any]:
    return _plan(
        n={"outdoor": house.street, "rooms": [house.living_room]},
        s={"outdoor": house.garden, "rooms": [house.kitchen, house.bedroom]},
        w={"outdoor": house.yard, "rooms": [house.bathroom]},
    )


def _checked_rooms(house: House) -> set[str]:
    return {
        house.living_room,
        house.kitchen,
        house.bathroom,
        house.bedroom,
        house.study,
    }


async def _to_rooms(hass: HomeAssistant, house: House) -> dict[str, Any]:
    result = await _start(hass)
    return await _configure(hass, result, {"weather": house.weather, "area_sync": True})


async def _to_plan(hass: HomeAssistant, house: House) -> dict[str, Any]:
    result = await _to_rooms(hass, house)
    return await _configure(hass, result, {"rooms": suggested(result, "rooms")})


async def _to_preview(hass: HomeAssistant, house: House) -> dict[str, Any]:
    result = await _to_plan(hass, house)
    return await _configure(hass, result, _default_plan(house))


async def test_start_shows_the_scan_and_suggests_the_weather(
    hass: HomeAssistant, house: House
) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["description_placeholders"] == {
        "rooms": "5",  # checked proposals
        "outdoor": "3",  # garden, yard, street
        "contacts": "9",  # 7 binary contacts and 2 text sensors
        "weather": "1",
    }
    assert [str(k) for k in result["data_schema"].schema] == ["weather", "area_sync"]
    assert suggested(result, "weather") == house.weather
    marker, _ = field(result, "area_sync")
    assert marker.default() is True


async def test_weather_without_a_forecast_is_not_suggested(
    hass: HomeAssistant, house: House
) -> None:
    hass.states.async_set(house.weather, "cloudy", {"supported_features": 0})
    result = await _start(hass)
    assert suggested(result, "weather") is None


async def test_rooms_are_prechecked_and_labelled(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_rooms(hass, house)
    assert result["step_id"] == "rooms"
    offered = {o["value"]: o["label"] for o in options(result, "rooms")}
    assert house.storage not in offered
    assert house.conservatory not in offered
    assert offered[house.living_room] == "Erdgeschoss · Wohnzimmer"
    assert offered[house.garden] == "Außen · Garten"
    assert offered[house.street] == "ohne Stockwerk · Straße"
    checked = suggested(result, "rooms")
    assert set(checked) == _checked_rooms(house)
    assert not {house.garden, house.yard, house.street} & set(checked)


async def test_no_rooms_is_an_error(hass: HomeAssistant, house: House) -> None:
    result = await _to_rooms(hass, house)
    result = await _configure(hass, result, {"rooms": []})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "rooms"
    assert result["errors"] == {"base": "no_rooms"}


async def test_plan_offers_unchosen_areas_outside_and_chosen_rooms_inside(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_plan(hass, house)
    assert result["step_id"] == "plan"
    for side in "nesw":
        assert set(_values(result, f"{side}.outdoor")) == {
            house.garden,
            house.yard,
            house.street,
        }
        assert set(_values(result, f"{side}.rooms")) == _checked_rooms(house)


async def test_room_on_two_sides_is_an_error(hass: HomeAssistant, house: House) -> None:
    result = await _to_plan(hass, house)
    result = await _configure(
        hass,
        result,
        _plan(
            n={"rooms": [house.living_room]},
            s={"rooms": [house.living_room, house.kitchen]},
        ),
    )
    assert result["step_id"] == "plan"
    assert result["errors"] == {"base": "room_two_sides"}
    # The answers stay in the form
    assert suggested(result, "s.rooms") == [house.living_room, house.kitchen]


async def test_outdoor_area_twice_is_an_error(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_plan(hass, house)
    result = await _configure(
        hass,
        result,
        _plan(n={"outdoor": house.garden}, w={"outdoor": house.garden}),
    )
    assert result["errors"] == {"base": "outdoor_twice"}
    assert result["description_placeholders"]["area"] == "Garten"
    assert result["description_placeholders"]["side"] == "Norden"


async def test_preview_lists_rooms_sides_and_what_was_not_taken(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_preview(hass, house)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "preview"
    assert result["menu_options"] == ["create", "add_window", "rooms", "plan"]
    preview = result["description_placeholders"]["preview"]
    assert "**Räume**" in preview
    assert "**Wohnzimmer** 21,4 °C · 48 % aus Klimasensor Temperatur" in preview
    assert "Seite: Norden." in preview
    assert "Nicht übernommen: " in preview
    assert "Kühlschrank Temperatur (6,9 °C, kein Raumwert)" in preview
    assert "**Außenseiten**" in preview
    assert "**Norden · Straße** 13,0 °C · 71 %" in preview
    assert (
        "Fällt Westen aus, springen Norden (Straße) und Süden (Garten) ein, "
        "dann der Wetterdienst."
    ) in preview
    # East has no side: its neighbours, then the opposite side, then the weather
    assert (
        "Osten: keine Außenseite, dafür springen Norden (Straße) und "
        "Süden (Garten) ein, "
        "dann Westen (Hof), dann der Wetterdienst."
    ) in preview
    assert "Quellen und Reihenfolge änderst du später pro Raum." in preview


async def test_preview_without_any_side_names_the_weather_only(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_plan(hass, house)
    result = await _configure(hass, result, _plan())
    preview = result["description_placeholders"]["preview"]
    assert "Norden: keine Außenseite, dafür springt der Wetterdienst ein." in preview
    assert "Westen: keine Außenseite, dafür springt der Wetterdienst ein." in preview


async def test_create_makes_the_documented_entry_and_it_loads(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_preview(hass, house)
    result = await _configure(hass, result, {"next_step_id": "create"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Climate Hub"
    assert result["description"] == "created"
    assert result["data"] == {}
    assert result["options"] == {
        "weather": house.weather,
        "area_sync": True,
        "max_age": 40,
        "burst_duration": 10,
        "humidity_threshold": 60.0,
        "repair_delay": 6,
    }
    stored = {s["unique_id"]: s for s in result["subentries"]}
    assert set(stored) == {f"room_{a}" for a in _checked_rooms(house)} | {
        "region_n",
        "region_s",
        "region_w",
    }
    living = stored[f"room_{house.living_room}"]
    assert living["subentry_type"] == SUBENTRY_ROOM
    assert living["title"] == "Wohnzimmer"
    assert living["data"] == {
        "area": house.living_room,
        "side": "n",
        "temperature": [
            house.living_temp,
            house.living_air_temp,
            house.living_thermostat,
        ],
        "humidity": [],
        "pressure": [],
        "climate_devices": [house.living_thermostat],
    }
    assert stored[f"room_{house.study}"]["data"]["side"] == "none"
    north = stored["region_n"]
    assert north["subentry_type"] == SUBENTRY_REGION
    assert north["title"] == "Norden · Straße"
    assert north["data"] == {
        "area": house.street,
        "direction": "n",
        "temperature": [house.street_temp],
        "humidity": [],
        "pressure": [],
    }

    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    assert len(entry.subentries) == 8
    registry = er.async_get(hass)
    assert er.async_entries_for_config_entry(registry, entry.entry_id)


async def test_without_a_weather_entity_the_option_is_absent(
    hass: HomeAssistant, house: House
) -> None:
    result = await _start(hass)
    result = await _configure(hass, result, {"area_sync": False})
    result = await _configure(hass, result, {"rooms": [house.living_room]})
    result = await _configure(hass, result, _plan())
    result = await _configure(hass, result, {"next_step_id": "create"})
    assert result["options"] == {
        "area_sync": False,
        "max_age": 40,
        "burst_duration": 10,
        "humidity_threshold": 60.0,
        "repair_delay": 6,
    }
    assert [s["unique_id"] for s in result["subentries"]] == [
        f"room_{house.living_room}"
    ]


async def test_a_second_flow_aborts(hass: HomeAssistant, house: House) -> None:
    result = await _to_preview(hass, house)
    await _configure(hass, result, {"next_step_id": "create"})
    await hass.async_block_till_done()
    again = await _start(hass)
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "single_instance_allowed"


async def test_changing_rooms_keeps_the_answers_and_drops_stale_ones(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_preview(hass, house)
    result = await _configure(hass, result, {"next_step_id": "rooms"})
    assert result["step_id"] == "rooms"
    kept = set(suggested(result, "rooms"))
    assert kept == _checked_rooms(house)

    # Drop the bathroom, make the street a room
    chosen = [*(kept - {house.bathroom}), house.street]
    result = await _configure(hass, result, {"rooms": chosen})
    assert result["step_id"] == "plan"
    assert suggested(result, "n.outdoor") is None  # the street is a room now
    assert suggested(result, "s.outdoor") == house.garden
    assert suggested(result, "w.outdoor") == house.yard
    assert suggested(result, "n.rooms") == [house.living_room]
    assert suggested(result, "w.rooms") == []  # the bathroom left
    assert house.street not in _values(result, "n.outdoor")


async def test_changing_the_plan_keeps_the_answers(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_preview(hass, house)
    result = await _configure(hass, result, {"next_step_id": "plan"})
    assert result["step_id"] == "plan"
    assert suggested(result, "n.outdoor") == house.street
    assert suggested(result, "s.rooms") == [house.kitchen, house.bedroom]

    result = await _configure(hass, result, _plan(e={"outdoor": house.yard}))
    assert result["step_id"] == "preview"
    preview = result["description_placeholders"]["preview"]
    assert "**Osten · Hof**" in preview
    # North has no side, but its neighbour east is configured now
    assert "Norden: keine Außenseite, dafür springt Osten (Hof) ein" in preview
