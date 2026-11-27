"""Area sync consent in the flows (R11): S4, S4a, S6, S7, through the flow manager."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from pytest_homeassistant.common import MockConfigEntry

from custom_components.climate_hub.const import SUBENTRY_REGION, SUBENTRY_ROOM
from custom_components.climate_hub.labels import entity_name
from custom_components.climate_hub.logic.area_sync import FieldRecord

from ..house import House
from .conftest import field, options, suggested
from .test_config_flow import _configure, _default_plan, _start, _to_preview

SWITCH = "advanced.replace_area_sensor"


def _set_area(hass: HomeAssistant, area_id: str, **fields: str | None) -> None:
    ar.async_get(hass).async_update(area_id, **fields)


async def _preview_without_sync(hass: HomeAssistant, house: House) -> dict[str, Any]:
    result = await _start(hass)
    result = await _configure(
        hass, result, {"weather": house.weather, "area_sync": False}
    )
    result = await _configure(hass, result, {"rooms": suggested(result, "rooms")})
    return await _configure(hass, result, _default_plan(house))


def _in_form(result: dict[str, Any]) -> bool:
    try:
        field(result, SWITCH)
    except KeyError:
        return False
    return True


# S4: the block


async def test_preview_names_the_areas_that_get_filled(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_preview(hass, house)
    preview = result["description_placeholders"]["preview"]
    assert "**Bereiche**" in preview
    assert "Climate Hub trägt sich als Temperatur- und Feuchtesensor ein." in preview
    assert "Climate Hub trägt sich als Temperatursensor ein." in preview
    assert "Hof: Climate Hub trägt sich als Temperatur- und" not in preview
    assert "zeigt schon" not in preview
    # Nothing to consent to: no menu option
    assert result["menu_options"] == ["create", "add_window", "rooms", "plan"]


async def test_foreign_sensor_shows_a_line_and_the_menu_option(
    hass: HomeAssistant, house: House
) -> None:
    _set_area(hass, house.kitchen, temperature_entity_id=house.kitchen_temp)
    _set_area(hass, house.study, temperature_entity_id=house.fridge_temp)
    result = await _to_preview(hass, house)
    preview = result["description_placeholders"]["preview"]
    assert (
        f"Küche zeigt schon {entity_name(hass, house.kitchen_temp)} "
        "(Quelle 1 dieses Raums). Bleibt, solange du nichts änderst."
    ) in preview
    assert (
        f"Arbeitszimmer zeigt schon {entity_name(hass, house.fridge_temp)}. "
        "Bleibt, solange du nichts änderst. "
        "Das leere Feuchtefeld füllt Climate Hub."
    ) in preview
    assert result["menu_options"] == [
        "create",
        "replace_area_sensors",
        "add_window",
        "rooms",
        "plan",
    ]


async def test_switch_off_says_nothing_is_entered(
    hass: HomeAssistant, house: House
) -> None:
    _set_area(hass, house.kitchen, temperature_entity_id=house.kitchen_temp)
    result = await _preview_without_sync(hass, house)
    preview = result["description_placeholders"]["preview"]
    assert "Climate Hub trägt nichts in die Bereiche ein." in preview
    assert "zeigt schon" not in preview
    assert result["menu_options"] == ["create", "add_window", "rooms", "plan"]


# S4a: the consent


async def _to_consent(hass: HomeAssistant, house: House) -> dict[str, Any]:
    _set_area(hass, house.kitchen, temperature_entity_id=house.kitchen_temp)
    _set_area(hass, house.study, temperature_entity_id=house.fridge_temp)
    result = await _to_preview(hass, house)
    return await _configure(hass, result, {"next_step_id": "replace_area_sensors"})


async def test_consent_step_offers_one_option_per_area(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_consent(hass, house)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "replace_area_sensors"
    assert options(result, "areas") == [
        {
            "value": house.kitchen,
            "label": f"Küche: {entity_name(hass, house.kitchen_temp)}",
        },
        {
            "value": house.study,
            "label": f"Arbeitszimmer: {entity_name(hass, house.fridge_temp)}",
        },
    ]
    assert suggested(result, "areas") == []  # nothing chosen the first time
    assert field(result, "areas")[1].config["multiple"] is True


async def test_consent_is_stored_for_the_chosen_area_only(
    hass: HomeAssistant, house: House
) -> None:
    result = await _to_consent(hass, house)
    result = await _configure(hass, result, {"areas": [house.kitchen]})
    assert result["step_id"] == "preview"
    preview = result["description_placeholders"]["preview"]
    assert (
        f"Küche: Climate Hub ersetzt {entity_name(hass, house.kitchen_temp)}. "
        "Er kommt zurück, wenn du das abwählst oder Climate Hub entfernst."
    ) in preview
    assert "Arbeitszimmer zeigt schon" in preview
    # Coming back shows the current choice
    again = await _configure(hass, result, {"next_step_id": "replace_area_sensors"})
    assert suggested(again, "areas") == [house.kitchen]
    result = await _configure(hass, again, {"areas": [house.kitchen]})

    result = await _configure(hass, result, {"next_step_id": "create"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    stored = {s["unique_id"]: s["data"] for s in result["subentries"]}
    assert stored[f"room_{house.kitchen}"]["replace_area_sensor"] is True
    others = [d for u, d in stored.items() if u != f"room_{house.kitchen}"]
    assert others
    assert all("replace_area_sensor" not in d for d in others)


async def test_an_outdoor_side_can_be_consented_too(
    hass: HomeAssistant, house: House
) -> None:
    _set_area(hass, house.garden, temperature_entity_id=house.yard_temp)
    result = await _to_preview(hass, house)
    preview = result["description_placeholders"]["preview"]
    assert (
        f"Garten zeigt schon {entity_name(hass, house.yard_temp)} "
        "(Quelle 1 dieser Außenseite)."
    ) not in preview  # the yard sensor is not a source of the garden side
    assert f"Garten zeigt schon {entity_name(hass, house.yard_temp)}." in preview
    result = await _configure(hass, result, {"next_step_id": "replace_area_sensors"})
    result = await _configure(hass, result, {"areas": [house.garden]})
    result = await _configure(hass, result, {"next_step_id": "create"})
    stored = {s["unique_id"]: s["data"] for s in result["subentries"]}
    assert stored["region_s"]["replace_area_sensor"] is True
    assert "replace_area_sensor" not in stored["region_n"]


async def test_an_area_that_is_no_longer_planned_loses_its_consent(
    hass: HomeAssistant, house: House
) -> None:
    _set_area(hass, house.kitchen, temperature_entity_id=house.kitchen_temp)
    result = await _to_preview(hass, house)
    result = await _configure(hass, result, {"next_step_id": "replace_area_sensors"})
    result = await _configure(hass, result, {"areas": [house.kitchen]})
    result = await _configure(hass, result, {"next_step_id": "rooms"})
    kept = [r for r in suggested(result, "rooms") if r != house.kitchen]
    result = await _configure(hass, result, {"rooms": kept})
    plan = _default_plan(house)
    plan["s"]["rooms"] = [house.bedroom]
    result = await _configure(hass, result, plan)
    assert "replace_area_sensors" not in result["menu_options"]
    result = await _configure(hass, result, {"next_step_id": "create"})
    assert all("replace_area_sensor" not in s["data"] for s in result["subentries"])


# S6 and S7: the switch


async def _reconfigure_living(
    hass: HomeAssistant, hub: MockConfigEntry
) -> dict[str, Any]:
    return await hass.config_entries.subentries.async_init(
        (hub.entry_id, SUBENTRY_ROOM),
        context={"source": "reconfigure", "subentry_id": "room_living"},
    )


async def _save_living(
    hass: HomeAssistant,
    hub: MockConfigEntry,
    result: dict[str, Any],
    advanced: dict[str, Any],
    side: str = "n",
) -> dict[str, Any]:
    data = dict(hub.subentries["room_living"].data)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "area": data["area"],
            "side": side,
            "temperature": data["temperature"],
            "humidity_pressure": {"humidity": [], "pressure": []},
            "climate": {"climate_devices": data["climate_devices"]},
            "advanced": advanced,
        },
    )
    assert result["step_id"] == "room_preview"
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "room_save"}
    )


async def test_switch_is_hidden_while_the_area_holds_only_our_sensor(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _reconfigure_living(hass, hub)
    assert not _in_form(result)
    assert result["description_placeholders"]["replace"] == ""


async def test_switch_shows_for_a_foreign_sensor_and_is_stored(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    _set_area(hass, house.living_room, temperature_entity_id=house.bedroom_temp)
    result = await _reconfigure_living(hass, hub)
    assert _in_form(result)
    assert field(result, SWITCH)[0].default() is False
    assert result["description_placeholders"]["replace"] == (
        f"\n\nWohnzimmer zeigt gerade {entity_name(hass, house.bedroom_temp)}. "
        "Eingeschaltet trägt sich Climate Hub dort ein; der bisherige Sensor kommt "
        "zurück, wenn du ausschaltest oder Climate Hub entfernst."
    )
    result = await _save_living(hass, hub, result, {"replace_area_sensor": True})
    assert result["type"] is FlowResultType.ABORT
    assert hub.subentries["room_living"].data["replace_area_sensor"] is True


async def test_switch_is_hidden_while_the_sync_is_off(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(
        hub, options={**hub.options, "area_sync": False}
    )
    await hass.async_block_till_done()
    _set_area(hass, house.living_room, temperature_entity_id=house.bedroom_temp)
    result = await _reconfigure_living(hass, hub)
    assert not _in_form(result)


async def test_switch_shows_after_a_replacement_with_the_replaced_sensor(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    hub.runtime_data.coordinator.area_sync[house.living_room] = {
        "temperature": FieldRecord(
            "sensor.wohnzimmer_klima_temperatur", previous=house.bedroom_temp
        )
    }
    result = await _reconfigure_living(hass, hub)
    assert _in_form(result)
    assert result["description_placeholders"]["replace"] == (
        f"\n\nClimate Hub hat {entity_name(hass, house.bedroom_temp)} in Wohnzimmer "
        "ersetzt. Ausgeschaltet kommt er zurück."
    )


async def test_a_hidden_switch_keeps_the_stored_value(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    sub = hub.subentries["room_living"]
    hass.config_entries.async_update_subentry(
        hub, sub, data={**sub.data, "replace_area_sensor": True}
    )
    await hass.async_block_till_done()
    result = await _reconfigure_living(hass, hub)
    assert not _in_form(result)
    result = await _save_living(hass, hub, result, {}, side="s")
    assert result["type"] is FlowResultType.ABORT
    saved = hub.subentries["room_living"].data
    assert saved["side"] == "s"
    assert saved["replace_area_sensor"] is True


async def test_switching_off_drops_the_key(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    _set_area(hass, house.living_room, temperature_entity_id=house.bedroom_temp)
    sub = hub.subentries["room_living"]
    hass.config_entries.async_update_subentry(
        hub, sub, data={**sub.data, "replace_area_sensor": True}
    )
    await hass.async_block_till_done()
    result = await _reconfigure_living(hass, hub)
    assert suggested(result, SWITCH) is True
    await _save_living(hass, hub, result, {"replace_area_sensor": False})
    assert "replace_area_sensor" not in hub.subentries["room_living"].data


async def test_new_outdoor_side_form_judges_its_area(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    _set_area(hass, house.yard, temperature_entity_id=house.garden_temp)
    result = await hass.config_entries.subentries.async_init(
        (hub.entry_id, SUBENTRY_REGION), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"direction": "w", "area": house.yard}
    )
    assert result["step_id"] == "region_form"
    assert _in_form(result)
    assert (
        f"Hof zeigt gerade {entity_name(hass, house.garden_temp)}."
        in result["description_placeholders"]["replace"]
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "direction": "w",
            "area": house.yard,
            "temperature": [house.yard_temp],
            "humidity_pressure": {"humidity": [], "pressure": []},
            "advanced": {"replace_area_sensor": True},
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "region_save"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = next(s for s in hub.subentries.values() if s.unique_id == "region_w")
    assert sub.data["replace_area_sensor"] is True


async def test_saving_the_switch_on_takes_over_a_field_the_user_changed(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    """integration.md §11 point 7: saving the switch on consents to the field."""
    ours = "sensor.wohnzimmer_klima_temperatur"
    records = hub.runtime_data.coordinator.area_sync
    records[house.living_room] = {"temperature": FieldRecord(ours)}
    _set_area(hass, house.living_room, temperature_entity_id=house.bedroom_temp)

    result = await _reconfigure_living(hass, hub)
    assert _in_form(result)
    assert "zeigt gerade" in result["description_placeholders"]["replace"]
    await _save_living(hass, hub, result, {"replace_area_sensor": True})
    assert house.living_room not in records


async def test_the_replaced_hint_needs_our_sensor_in_the_field(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    hub.runtime_data.coordinator.area_sync[house.living_room] = {
        "temperature": FieldRecord(
            "sensor.wohnzimmer_klima_temperatur", previous=house.bedroom_temp
        )
    }
    _set_area(hass, house.living_room, temperature_entity_id=house.kitchen_temp)
    result = await _reconfigure_living(hass, hub)
    assert (
        f"zeigt gerade {entity_name(hass, house.kitchen_temp)}"
        in result["description_placeholders"]["replace"]
    )
