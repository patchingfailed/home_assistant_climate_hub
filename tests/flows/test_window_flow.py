"""Window subentry flow, S8-S8d (docs/integration.md 9.5), through the flow manager."""

from typing import Any

import pytest
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.climate_hub.const import SUBENTRY_ROOM, SUBENTRY_WINDOW

from ..house import House, set_value
from .conftest import field, suggested


async def _init(
    hass: HomeAssistant, hub: MockConfigEntry, source: str = "user", **context: Any
) -> dict[str, Any]:
    return await hass.config_entries.subentries.async_init(
        (hub.entry_id, SUBENTRY_WINDOW), context={"source": source, **context}
    )


async def _configure(
    hass: HomeAssistant, result: dict[str, Any], user_input: dict[str, Any]
) -> dict[str, Any]:
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )


async def _pick(
    hass: HomeAssistant, result: dict[str, Any], step: str
) -> dict[str, Any]:
    return await _configure(hass, result, {"next_step_id": step})


def _form(
    area: str,
    *,
    name: str | None = None,
    show_all: bool = False,
    extra: dict[str, Any] | None = None,
    cover: str | None = None,
    advanced: dict[str, Any] | None = None,
    **contacts: str,
) -> dict[str, Any]:
    return {
        "area": area,
        **contacts,
        "show_all": show_all,
        **({"name": name} if name else {}),
        # A pass-through has no extra contacts
        **({} if "inner" in contacts else {"extra_contacts": extra or {}}),
        "cover": {"cover": cover} if cover else {},
        "advanced": advanced or {},
    }


async def _to_form(
    hass: HomeAssistant, hub: MockConfigEntry, area: str, step: str
) -> dict[str, Any]:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": area})
    assert result["step_id"] == "window_type"
    result = await _pick(hass, result, step)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step
    return result


async def _add(
    hass: HomeAssistant,
    hub: MockConfigEntry,
    area: str,
    step: str,
    user_input: dict[str, Any],
) -> dict[str, Any]:
    """Add a window up to its preview (no text sensors)."""
    result = await _to_form(hass, hub, area, step)
    result = await _configure(hass, result, user_input)
    assert result["type"] is FlowResultType.MENU, result
    assert result["step_id"] == "window_preview"
    return result


def _windows(hub: MockConfigEntry) -> list[ConfigSubentry]:
    return [s for s in hub.subentries.values() if s.subentry_type == SUBENTRY_WINDOW]


def _room(hub: MockConfigEntry, area: str) -> ConfigSubentry | None:
    return next(
        (
            s
            for s in hub.subentries.values()
            if s.subentry_type == SUBENTRY_ROOM and s.data["area"] == area
        ),
        None,
    )


def _choices(result: dict[str, Any], name: str) -> list[str]:
    return list(field(result, name)[1].config["include_entities"])


async def test_add_starts_with_the_room(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "window_room"
    assert [str(k) for k in result["data_schema"].schema] == ["area"]


async def test_room_step_refuses_an_area_without_a_temperature_sensor(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hub=hub, hass=hass)
    result = await _configure(hass, result, {"area": house.storage})
    assert result["step_id"] == "window_room"
    assert result["errors"] == {"base": "no_room_temperature"}
    assert result["description_placeholders"]["area"] == "Abstellraum"
    # An area with a temperature sensor that is not a room yet becomes one
    result = await _configure(hass, result, {"area": house.kitchen})
    assert result["step_id"] == "window_type"
    assert result["description_placeholders"]["area"] == "Küche"


async def test_room_step_refuses_an_outdoor_area(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.street})
    assert result["step_id"] == "window_room"
    assert result["errors"] == {"base": "is_region"}
    assert result["description_placeholders"]["area"] == "Straße"
    result = await _configure(hass, result, {"area": house.kitchen})
    assert result["step_id"] == "window_type"


async def test_type_menu(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _init(hass, hub)
    result = await _configure(hass, result, {"area": house.kitchen})
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "window_type"
    assert result["menu_options"] == [
        "window_single",
        "window_double",
        "window_pass_through",
    ]
    assert result["description_placeholders"]["area"] == "Küche"


async def test_single_form_lists_the_rooms_contacts(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _to_form(hass, hub, house.kitchen, "window_single")
    assert suggested(result, "area") == house.kitchen
    # The kitchen's contact and the ones without an area (scenario 8), no text
    # sensor of another room
    leaf = _choices(result, "leaf")
    assert house.kitchen_contact in leaf
    assert house.loose_window in leaf
    assert house.loose_text in leaf
    assert house.living_leaf_1 not in leaf
    assert house.bath_window_text not in leaf
    assert house.kitchen_contact_temp not in leaf
    # The same list in the extra contacts
    assert _choices(result, "extra_contacts.tilt") == leaf
    assert _choices(result, "extra_contacts.handle") == leaf
    assert result["description_placeholders"]["shown"] == (
        "Gezeigt: Bereich Küche und Kontakte ohne Bereich."
    )
    assert field(result, "extra_contacts")[1].options["collapsed"] is True
    assert field(result, "cover")[1].options["collapsed"] is True
    assert field(result, "advanced")[1].options["collapsed"] is True
    assert field(result, "cover.cover")[1].config["domain"] == ["cover"]
    assert list(field(result, "advanced.facing")[1].config["options"]) == [
        "room",
        "n",
        "e",
        "s",
        "w",
    ]
    assert list(field(result, "advanced.min_level")[1].config["options"]) == [
        "ajar",
        "tilted",
        "open",
    ]


async def test_show_all_reopens_the_form_with_all_contacts(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _to_form(hass, hub, house.kitchen, "window_single")
    result = await _configure(
        hass,
        result,
        _form(house.kitchen, show_all=True, leaf=house.kitchen_contact, name="Erker"),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "window_single"
    assert result["errors"] == {}
    assert house.living_leaf_1 in _choices(result, "leaf")
    assert house.bath_window_text in _choices(result, "leaf")
    assert suggested(result, "leaf") == house.kitchen_contact
    assert suggested(result, "name") == "Erker"
    assert suggested(result, "show_all") is True
    assert result["description_placeholders"]["shown"] == "Gezeigt: alle Kontakte."
    # Submitting again with the box still checked goes on
    result = await _configure(
        hass,
        result,
        _form(house.kitchen, show_all=True, leaf=house.living_leaf_1),
    )
    assert result["step_id"] == "window_preview"


async def test_text_sensors_need_a_window_word_unless_show_all(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    hass.states.async_set("sensor.wlan_ssid", "Heimnetz")
    hass.states.async_set("sensor.kontakt_mit_optionen", "x", {"options": ["Offen"]})
    result = await _to_form(hass, hub, house.kitchen, "window_single")
    near = _choices(result, "leaf")
    assert "sensor.wlan_ssid" not in near
    assert "sensor.kontakt_mit_optionen" in near
    result = await _configure(
        hass, result, _form(house.kitchen, show_all=True, leaf=house.kitchen_contact)
    )
    assert "sensor.wlan_ssid" in _choices(result, "leaf")


async def test_room_change_reopens_the_form_with_that_rooms_contacts(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _to_form(hass, hub, house.kitchen, "window_single")
    result = await _configure(
        hass, result, _form(house.study, leaf=house.kitchen_contact)
    )
    assert result["step_id"] == "window_single"
    assert result["errors"] == {}
    leaf = _choices(result, "leaf")
    assert house.study_door in leaf
    assert house.kitchen_contact in leaf  # chosen contacts stay visible
    assert house.living_leaf_1 not in leaf
    assert suggested(result, "area") == house.study
    assert result["description_placeholders"]["shown"] == (
        "Gezeigt: Bereich Arbeitszimmer und Kontakte ohne Bereich."
    )
    result = await _configure(hass, result, _form(house.study, leaf=house.study_door))
    assert result["step_id"] == "window_preview"


async def test_form_refuses_an_outdoor_area(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _to_form(hass, hub, house.kitchen, "window_single")
    result = await _configure(
        hass, result, _form(house.garden, leaf=house.kitchen_contact)
    )
    assert result["step_id"] == "window_single"
    assert result["errors"] == {"base": "is_region"}
    assert result["description_placeholders"]["area"] == "Garten"


@pytest.mark.parametrize(
    ("step", "contacts"),
    [
        ("window_single", {}),
        ("window_double", {"leaf_left": "kitchen_contact"}),
        ("window_pass_through", {"inner": "kitchen_contact"}),
    ],
)
async def test_missing_contact(
    hass: HomeAssistant,
    house: House,
    hub: MockConfigEntry,
    step: str,
    contacts: dict[str, str],
) -> None:
    result = await _to_form(hass, hub, house.kitchen, step)
    result = await _configure(
        hass,
        result,
        _form(house.kitchen, **{k: getattr(house, v) for k, v in contacts.items()}),
    )
    assert result["step_id"] == step
    assert result["errors"] == {"base": "no_contact"}


async def test_same_contact_in_two_roles(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _to_form(hass, hub, house.kitchen, "window_single")
    result = await _configure(
        hass,
        result,
        _form(
            house.kitchen,
            leaf=house.kitchen_contact,
            extra={"handle": house.kitchen_contact},
        ),
    )
    assert result["errors"] == {"base": "same_contact"}
    # The section stays open with the value
    assert field(result, "extra_contacts")[1].options["collapsed"] is False
    assert suggested(result, "extra_contacts.handle") == house.kitchen_contact


async def test_single_window_in_a_room_without_room_creates_the_room(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _add(
        hass,
        hub,
        house.kitchen,
        "window_single",
        _form(house.kitchen, leaf=house.kitchen_contact),
    )
    assert result["menu_options"] == ["window_save", "window_adjust", "window_retype"]
    text = result["description_placeholders"]["preview"]
    assert result["description_placeholders"]["title"] == "Küche Fenster"
    assert "Name: Küche Fenster, nach dem Raum benannt." in text
    assert "Ausrichtung: keine, der Raum hat keine Hauptseite." in text
    assert "Gerade **zu**." in text
    assert "Raum Küche: " in text
    assert "Raum Küche wird mit angelegt, Quellen: " in text
    assert "Klimasensor Temperatur" in text
    assert "Rollladen" not in text
    assert _room(hub, house.kitchen) is None

    result = await _pick(hass, result, "window_save")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Küche Fenster"
    (window,) = _windows(hub)
    assert dict(window.data) == {
        "area": house.kitchen,
        "type": "single",
        "name": "Fenster",
        "leaf": house.kitchen_contact,
        "facing": "room",
        "min_level": "tilted",
    }
    assert window.title == "Küche Fenster"
    assert window.unique_id is None
    room = _room(hub, house.kitchen)
    assert room is not None
    assert room.title == "Küche"
    assert room.unique_id == f"room_{house.kitchen}"
    assert room.data["side"] == "none"
    assert room.data["temperature"] == [house.kitchen_temp, house.kitchen_thermostat]


async def test_second_window_in_a_room_is_numbered(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    for contact in (house.living_leaf_1, house.living_leaf_2, house.living_bottom):
        result = await _add(
            hass,
            hub,
            house.living_room,
            "window_single",
            _form(house.living_room, leaf=contact),
        )
        result = await _pick(hass, result, "window_save")
        assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [w.data["name"] for w in _windows(hub)] == [
        "Fenster",
        "Fenster 2",
        "Fenster 3",
    ]
    assert [w.title for w in _windows(hub)] == [
        "Wohnzimmer Fenster",
        "Wohnzimmer Fenster 2",
        "Wohnzimmer Fenster 3",
    ]


async def test_named_window_has_no_name_line(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _add(
        hass,
        hub,
        house.living_room,
        "window_single",
        _form(house.living_room, leaf=house.living_leaf_1, name="Terrassentür"),
    )
    assert "Name:" not in result["description_placeholders"]["preview"]
    assert (
        "Raum Wohnzimmer wird mit angelegt"
        not in (result["description_placeholders"]["preview"])
    )
    assert result["description_placeholders"]["title"] == "Wohnzimmer Terrassentür"
    result = await _pick(hass, result, "window_save")
    assert _windows(hub)[0].data["name"] == "Terrassentür"
    assert _windows(hub)[0].title == "Wohnzimmer Terrassentür"


async def test_scenario_5_double_leaf_with_tilt_discriminator(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _to_form(hass, hub, house.living_room, "window_double")
    assert suggested(result, "area") == house.living_room
    # The tilt discriminator is a main field, the extra section has the handle only
    for name in ("leaf_left", "leaf_right", "tilt"):
        assert house.living_bottom in _choices(result, name)
    assert [str(k) for k in field(result, "extra_contacts")[1].schema.schema] == [
        "handle"
    ]
    # Left leaf turned open at the top, bottom contact closed: tilted, left leaf
    set_value(hass, house.living_leaf_1, "on")
    result = await _configure(
        hass,
        result,
        _form(
            house.living_room,
            leaf_left=house.living_leaf_1,
            leaf_right=house.living_leaf_2,
            tilt=house.living_bottom,
        ),
    )
    assert result["step_id"] == "window_preview"
    text = result["description_placeholders"]["preview"]
    assert "Ausrichtung: Norden, wie der Raum." in text
    assert "Gerade **gekippt** (linker Flügel), seit weniger als 1 min." in text
    assert "Raum Wohnzimmer: **" in text
    assert "Draußen ist es" in text
    assert "Tagesstrategie: " in text
    # Bottom contact open as well: turned open
    set_value(hass, house.living_bottom, "on")
    result = await _pick(hass, result, "window_adjust")
    result = await _configure(
        hass,
        result,
        _form(
            house.living_room,
            leaf_left=house.living_leaf_1,
            leaf_right=house.living_leaf_2,
            tilt=house.living_bottom,
        ),
    )
    assert (
        "Gerade **offen** (linker Flügel)"
        in (result["description_placeholders"]["preview"])
    )
    result = await _pick(hass, result, "window_save")
    assert dict(_windows(hub)[0].data) == {
        "area": house.living_room,
        "type": "double",
        "name": "Fenster",
        "leaf_left": house.living_leaf_1,
        "leaf_right": house.living_leaf_2,
        "tilt": house.living_bottom,
        "facing": "room",
        "min_level": "tilted",
    }


async def test_scenario_6_handle_contact_gives_ajar(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    set_value(hass, house.living_bottom, "on")  # the handle contact
    result = await _add(
        hass,
        hub,
        house.living_room,
        "window_single",
        _form(
            house.living_room,
            leaf=house.living_leaf_1,
            extra={"handle": house.living_bottom},
        ),
    )
    assert "Gerade **angelehnt**." in result["description_placeholders"]["preview"]
    result = await _pick(hass, result, "window_save")
    assert dict(_windows(hub)[0].data) == {
        "area": house.living_room,
        "type": "single",
        "name": "Fenster",
        "leaf": house.living_leaf_1,
        "handle": house.living_bottom,
        "facing": "room",
        "min_level": "tilted",
    }


async def test_scenario_7_pass_through_and_the_room_created_along(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _to_form(hass, hub, house.study, "window_pass_through")
    inner, outer = _choices(result, "inner"), _choices(result, "outer")
    assert house.study_door in inner
    assert house.conservatory_window not in inner
    # The outer opening always lists all contacts
    assert {house.study_door, house.conservatory_window, house.kitchen_contact} <= set(
        outer
    )
    assert "extra_contacts" not in [str(k) for k in result["data_schema"].schema]
    assert [str(k) for k in result["data_schema"].schema][:4] == [
        "area",
        "inner",
        "show_all",
        "outer",
    ]
    set_value(hass, house.study_door, "on")
    result = await _configure(
        hass,
        result,
        _form(
            house.study,
            inner=house.study_door,
            outer=house.conservatory_window,
            name="Durchgang Wintergarten",
        ),
    )
    # Only the door is open: no air path through the conservatory
    text = result["description_placeholders"]["preview"]
    assert "Gerade **zu**." in text
    assert "Raum Arbeitszimmer wird mit angelegt, Quellen: " in text
    result = await _pick(hass, result, "window_adjust")
    set_value(hass, house.conservatory_window, "on")
    result = await _configure(
        hass,
        result,
        _form(
            house.study,
            inner=house.study_door,
            outer=house.conservatory_window,
            name="Durchgang Wintergarten",
        ),
    )
    assert "Gerade **offen**" in result["description_placeholders"]["preview"]
    result = await _pick(hass, result, "window_save")
    assert dict(_windows(hub)[0].data) == {
        "area": house.study,
        "type": "pass_through",
        "name": "Durchgang Wintergarten",
        "inner": house.study_door,
        "outer": house.conservatory_window,
        "facing": "room",
        "min_level": "tilted",
    }
    assert _windows(hub)[0].title == "Arbeitszimmer Durchgang Wintergarten"
    assert _room(hub, house.study) is not None


async def test_pass_through_default_name(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _add(
        hass,
        hub,
        house.study,
        "window_pass_through",
        _form(house.study, inner=house.study_door, outer=house.conservatory_window),
    )
    assert result["description_placeholders"]["title"] == "Arbeitszimmer Durchgang"
    result = await _pick(hass, result, "window_save")
    assert _windows(hub)[0].data["name"] == "Durchgang"


async def test_scenario_8_contact_without_an_area(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _to_form(hass, hub, house.bedroom, "window_single")
    # No contact in the bedroom: the contacts without an area are offered anyway
    assert house.loose_window in _choices(result, "leaf")
    result = await _configure(
        hass, result, _form(house.bedroom, leaf=house.loose_window)
    )
    assert result["step_id"] == "window_preview"
    result = await _pick(hass, result, "window_save")
    assert _windows(hub)[0].data["leaf"] == house.loose_window
    assert _windows(hub)[0].data["area"] == house.bedroom


async def test_cover_and_advanced_fields(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _add(
        hass,
        hub,
        house.living_room,
        "window_single",
        _form(
            house.living_room,
            leaf=house.living_leaf_1,
            cover=house.living_cover,
            advanced={"facing": "w", "facing_degrees": 250, "min_level": "ajar"},
        ),
    )
    text = result["description_placeholders"]["preview"]
    assert "Ausrichtung: Westen. Genau 250°." in text
    assert "Rollladen: **" in text
    result = await _pick(hass, result, "window_save")
    assert dict(_windows(hub)[0].data) == {
        "area": house.living_room,
        "type": "single",
        "name": "Fenster",
        "leaf": house.living_leaf_1,
        "cover": house.living_cover,
        "facing": "w",
        "facing_degrees": 250.0,
        "min_level": "ajar",
    }


async def test_preview_adjust_keeps_the_values_and_retype_changes_the_form(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _add(
        hass,
        hub,
        house.living_room,
        "window_single",
        _form(
            house.living_room,
            leaf=house.living_leaf_1,
            name="Balkon",
            cover=house.living_cover,
        ),
    )
    result = await _pick(hass, result, "window_adjust")
    assert result["step_id"] == "window_single"
    assert suggested(result, "leaf") == house.living_leaf_1
    assert suggested(result, "name") == "Balkon"
    assert suggested(result, "cover.cover") == house.living_cover
    assert field(result, "cover")[1].options["collapsed"] is False
    result = await _configure(
        hass,
        result,
        _form(house.living_room, leaf=house.living_leaf_2, name="Balkon"),
    )
    assert result["step_id"] == "window_preview"

    result = await _pick(hass, result, "window_retype")
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "window_type"
    result = await _pick(hass, result, "window_double")
    assert result["step_id"] == "window_double"
    assert suggested(result, "name") == "Balkon"
    assert suggested(result, "area") == house.living_room
    result = await _configure(
        hass,
        result,
        _form(
            house.living_room,
            name="Balkon",
            leaf_left=house.living_leaf_1,
            leaf_right=house.living_leaf_2,
        ),
    )
    result = await _pick(hass, result, "window_save")
    # Nothing of the single form is left
    assert dict(_windows(hub)[0].data) == {
        "area": house.living_room,
        "type": "double",
        "name": "Balkon",
        "leaf_left": house.living_leaf_1,
        "leaf_right": house.living_leaf_2,
        "facing": "room",
        "min_level": "tilted",
    }


# S8d


async def _to_mapping(
    hass: HomeAssistant, hub: MockConfigEntry, area: str, **contacts: str
) -> dict[str, Any]:
    result = await _to_form(hass, hub, area, "window_single")
    result = await _configure(hass, result, _form(area, **contacts))
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "window_mapping"
    return result


async def test_mapping_is_prefilled_from_the_options_and_common_words(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    set_value(
        hass,
        house.bath_window_text,
        "zu",
        options=["zu", "angelehnt", "gekippt", "offen", "closed", "Mist"],
    )
    result = await _to_mapping(hass, hub, house.bathroom, leaf=house.bath_window_text)
    assert result["description_placeholders"] == {"sensor": "Bad Fenster"}
    assert [str(k) for k in result["data_schema"].schema] == [
        "closed",
        "ajar",
        "tilted",
        "open",
    ]
    selector = field(result, "closed")[1]
    assert selector.config["multiple"] is True
    assert selector.config["custom_value"] is True
    assert list(selector.config["options"]) == [
        "zu",
        "angelehnt",
        "gekippt",
        "offen",
        "closed",
        "Mist",
    ]
    assert suggested(result, "closed") == ["zu", "closed"]
    assert suggested(result, "ajar") == ["angelehnt"]
    assert suggested(result, "tilted") == ["gekippt"]
    assert suggested(result, "open") == ["offen"]

    # Custom values can be typed; the saved mapping holds only what was given
    result = await _configure(
        hass,
        result,
        {
            "closed": ["zu", "closed"],
            "ajar": [],
            "tilted": ["gekippt", "Kipp"],
            "open": ["offen"],
        },
    )
    assert result["step_id"] == "window_preview"
    assert "Gerade **zu**." in result["description_placeholders"]["preview"]
    result = await _pick(hass, result, "window_save")
    assert dict(_windows(hub)[0].data) == {
        "area": house.bathroom,
        "type": "single",
        "name": "Fenster",
        "leaf": house.bath_window_text,
        "mappings": {
            house.bath_window_text: {
                "closed": ["zu", "closed"],
                "tilted": ["gekippt", "Kipp"],
                "open": ["offen"],
            }
        },
        "facing": "room",
        "min_level": "tilted",
    }


@pytest.fixture
def recorder_db_url() -> str:
    """In-memory database; the plugin's fixture insists on running before `hass`."""
    return "sqlite://"


async def test_mapping_options_come_from_the_recorder_history(
    recorder_mock: Any, hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    for state in ("geschlossen", "gekippt", "Fenster auf", "zu"):
        set_value(hass, house.bath_window_text, state)
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    result = await _to_mapping(hass, hub, house.bathroom, leaf=house.bath_window_text)
    options = list(field(result, "closed")[1].config["options"])
    assert set(options) == {"geschlossen", "gekippt", "Fenster auf", "zu"}
    assert suggested(result, "closed") == ["zu", "geschlossen"]
    assert suggested(result, "tilted") == ["gekippt"]
    assert suggested(result, "ajar") is None
    assert suggested(result, "open") is None


async def test_mapping_comes_once_per_text_sensor(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    set_value(hass, house.loose_text, "closed")
    result = await _to_form(hass, hub, house.bathroom, "window_double")
    result = await _configure(
        hass,
        result,
        _form(
            house.bathroom,
            leaf_left=house.bath_window_text,
            leaf_right=house.loose_window,
            tilt=house.loose_text,
        ),
    )
    assert result["step_id"] == "window_mapping"
    assert result["description_placeholders"]["sensor"] == "Bad Fenster"
    result = await _configure(hass, result, {"closed": ["zu"]})
    assert result["step_id"] == "window_mapping"
    assert result["description_placeholders"]["sensor"] == "Fenster Text"
    assert suggested(result, "closed") == ["closed"]
    result = await _configure(hass, result, {"closed": ["closed"]})
    assert result["step_id"] == "window_preview"
    result = await _pick(hass, result, "window_save")
    assert dict(_windows(hub)[0].data["mappings"]) == {
        house.bath_window_text: {"closed": ["zu"]},
        house.loose_text: {"closed": ["closed"]},
    }


async def test_binary_contacts_need_no_mapping(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _add(
        hass,
        hub,
        house.living_room,
        "window_single",
        _form(house.living_room, leaf=house.living_leaf_1),
    )
    result = await _pick(hass, result, "window_save")
    assert "mappings" not in _windows(hub)[0].data


# Reconfigure


async def _window(
    hass: HomeAssistant, hub: MockConfigEntry, house: House, data: dict[str, Any]
) -> str:
    sub = ConfigSubentry(
        data=data,  # type: ignore[arg-type]
        subentry_type=SUBENTRY_WINDOW,
        title="Altes Fenster",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(hub, sub)
    await hass.async_block_till_done()
    return sub.subentry_id


async def test_reconfigure_single_with_a_text_sensor_keeps_its_mapping(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    mapping = {"closed": ["zu"], "open": ["offen", "auf"]}
    subentry_id = await _window(
        hass,
        hub,
        house,
        {
            "area": house.bathroom,
            "type": "single",
            "name": "Fenster",
            "leaf": house.bath_window_text,
            "mappings": {house.bath_window_text: mapping},
            "cover": house.living_cover,
            "facing": "s",
            "min_level": "open",
        },
    )
    result = await _init(hass, hub, "reconfigure", subentry_id=subentry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "window_single"
    assert suggested(result, "area") == house.bathroom
    assert suggested(result, "leaf") == house.bath_window_text
    assert suggested(result, "name") == "Fenster"
    assert suggested(result, "cover.cover") == house.living_cover
    assert suggested(result, "advanced.facing") == "s"
    assert suggested(result, "advanced.min_level") == "open"
    assert field(result, "advanced")[1].options["collapsed"] is False
    assert house.bath_window_text in _choices(result, "leaf")

    result = await _configure(
        hass,
        result,
        _form(
            house.bathroom,
            leaf=house.bath_window_text,
            name="Badfenster",
            cover=house.living_cover,
            advanced={"facing": "s", "min_level": "open"},
        ),
    )
    assert result["step_id"] == "window_mapping"
    assert suggested(result, "open") == ["offen", "auf"]
    result = await _configure(hass, result, mapping)
    assert result["step_id"] == "window_preview"
    assert "Name:" not in result["description_placeholders"]["preview"]
    result = await _pick(hass, result, "window_save")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    sub = hub.subentries[subentry_id]
    assert dict(sub.data) == {
        "area": house.bathroom,
        "type": "single",
        "name": "Badfenster",
        "leaf": house.bath_window_text,
        "mappings": {house.bath_window_text: mapping},
        "cover": house.living_cover,
        "facing": "s",
        "min_level": "open",
    }
    assert sub.title == "Bad Badfenster"
    # The bathroom had no room: it is created along
    assert _room(hub, house.bathroom) is not None


async def test_reconfigure_drops_the_mapping_of_a_contact_no_longer_chosen(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    subentry_id = await _window(
        hass,
        hub,
        house,
        {
            "area": house.living_room,
            "type": "single",
            "name": "Fenster",
            "leaf": house.bath_window_text,
            "mappings": {house.bath_window_text: {"closed": ["zu"]}},
            "facing": "room",
            "min_level": "tilted",
        },
    )
    result = await _init(hass, hub, "reconfigure", subentry_id=subentry_id)
    result = await _configure(
        hass, result, _form(house.living_room, leaf=house.living_leaf_1)
    )
    assert result["step_id"] == "window_preview"
    result = await _pick(hass, result, "window_save")
    assert dict(hub.subentries[subentry_id].data) == {
        "area": house.living_room,
        "type": "single",
        "name": "Fenster",
        "leaf": house.living_leaf_1,
        "facing": "room",
        "min_level": "tilted",
    }
    assert _room(hub, house.living_room) is not None
    assert len([s for s in hub.subentries.values() if s.subentry_type == "room"]) == 1


async def test_reconfigure_double(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    subentry_id = await _window(
        hass,
        hub,
        house,
        {
            "area": house.living_room,
            "type": "double",
            "name": "Fenster",
            "leaf_left": house.living_leaf_1,
            "leaf_right": house.living_leaf_2,
            "tilt": house.living_bottom,
            "facing": "room",
            "min_level": "tilted",
        },
    )
    result = await _init(hass, hub, "reconfigure", subentry_id=subentry_id)
    assert result["step_id"] == "window_double"
    assert suggested(result, "leaf_left") == house.living_leaf_1
    assert suggested(result, "leaf_right") == house.living_leaf_2
    assert suggested(result, "tilt") == house.living_bottom
    result = await _configure(
        hass,
        result,
        _form(
            house.living_room,
            leaf_left=house.living_leaf_1,
            leaf_right=house.living_leaf_2,
            extra={"handle": house.living_bottom},
        ),
    )
    assert result["step_id"] == "window_preview"
    # Its own name does not count when numbering
    assert result["description_placeholders"]["title"] == "Wohnzimmer Fenster"
    result = await _pick(hass, result, "window_save")
    assert dict(hub.subentries[subentry_id].data) == {
        "area": house.living_room,
        "type": "double",
        "name": "Fenster",
        "leaf_left": house.living_leaf_1,
        "leaf_right": house.living_leaf_2,
        "handle": house.living_bottom,
        "facing": "room",
        "min_level": "tilted",
    }


async def test_reconfigure_pass_through_and_retype(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    subentry_id = await _window(
        hass,
        hub,
        house,
        {
            "area": house.study,
            "type": "pass_through",
            "name": "Durchgang",
            "inner": house.study_door,
            "outer": house.conservatory_window,
            "facing": "room",
            "min_level": "tilted",
        },
    )
    result = await _init(hass, hub, "reconfigure", subentry_id=subentry_id)
    assert result["step_id"] == "window_pass_through"
    assert suggested(result, "inner") == house.study_door
    assert suggested(result, "outer") == house.conservatory_window
    result = await _configure(
        hass,
        result,
        _form(
            house.study,
            inner=house.study_door,
            outer=house.conservatory_window,
            name="Durchgang",
        ),
    )
    result = await _pick(hass, result, "window_retype")
    result = await _pick(hass, result, "window_single")
    assert result["step_id"] == "window_single"
    result = await _configure(
        hass, result, _form(house.study, leaf=house.study_door, name="Tür")
    )
    result = await _pick(hass, result, "window_save")
    assert result["reason"] == "reconfigure_successful"
    assert dict(hub.subentries[subentry_id].data) == {
        "area": house.study,
        "type": "single",
        "name": "Tür",
        "leaf": house.study_door,
        "facing": "room",
        "min_level": "tilted",
    }


async def test_reconfigure_with_a_new_room_reopens_with_its_contacts(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    subentry_id = await _window(
        hass,
        hub,
        house,
        {
            "area": house.living_room,
            "type": "single",
            "name": "Fenster",
            "leaf": house.living_leaf_1,
            "facing": "room",
            "min_level": "tilted",
        },
    )
    result = await _init(hass, hub, "reconfigure", subentry_id=subentry_id)
    result = await _configure(
        hass, result, _form(house.kitchen, leaf=house.living_leaf_1)
    )
    assert result["step_id"] == "window_single"
    assert house.kitchen_contact in _choices(result, "leaf")
    assert suggested(result, "area") == house.kitchen
    result = await _configure(
        hass, result, _form(house.kitchen, leaf=house.kitchen_contact)
    )
    result = await _pick(hass, result, "window_save")
    assert hub.subentries[subentry_id].data["area"] == house.kitchen
    assert hub.subentries[subentry_id].title == "Küche Fenster"
