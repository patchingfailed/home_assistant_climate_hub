"""Fix flows of the repair issues (docs/integration.md 10.2, 10.3), via the manager."""

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_hub.const import (
    DOMAIN,
    SUBENTRY_ROOM,
    SUBENTRY_WINDOW,
)
from custom_components.climate_hub.logic import model as m

from ..house import House
from ..integration.test_coordinator import _advance, _entry
from ..integration.test_issues import (
    BEDROOM_ISSUE,
    _add_sensor,
    _add_subentry,
    _all,
    _settle,
    _start,
    _window_data,
)

RELOAD = timedelta(seconds=2)


async def _init(hass: HomeAssistant, issue_id: str) -> dict[str, Any]:
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    assert manager is not None
    return await manager.async_init(DOMAIN, context={"issue_id": issue_id})


async def _configure(
    hass: HomeAssistant, result: dict[str, Any], user_input: dict[str, Any]
) -> dict[str, Any]:
    manager = repairs_flow_manager(hass)
    assert manager is not None
    return await manager.async_configure(result["flow_id"], user_input)


def _add_humidity(hass: HomeAssistant, house: House, temperature_id: str) -> str:
    """A humidity sensor on the device of an added temperature sensor."""
    device_id = er.async_get(hass).async_get(temperature_id).device_id
    entry = er.async_get(hass).async_get_or_create(
        "sensor",
        "test",
        f"{temperature_id}_hum",
        suggested_object_id=f"{temperature_id.split('.')[1]}_hum",
        config_entry=house.config_entry,
        device_id=device_id,
        original_device_class="humidity",
        original_name="hum",
    )
    hass.states.async_set(
        entry.entity_id,
        "50",
        {
            "friendly_name": "hum",
            "device_class": "humidity",
            "unit_of_measurement": "%",
            "state_class": "measurement",
        },
    )
    return entry.entity_id


def _subentry(entry: MockConfigEntry, sub_id: str) -> Any:
    return entry.subentries[sub_id]


# New source


async def test_new_source_follow_list_stays_empty_and_seen_is_kept(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    entry = _entry(house)
    await _start(hass, entry)
    first = _add_sensor(hass, house, "extra_a", house.bedroom)
    second = _add_sensor(hass, house, "extra_b", house.bedroom)
    await _settle(hass, freezer)
    assert set(_all(hass, "new_source_")) == {
        f"{BEDROOM_ISSUE}{first}",
        f"{BEDROOM_ISSUE}{second}",
    }

    result = await _init(hass, f"{BEDROOM_ISSUE}{first}")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {
        "area": "Schlafzimmer",
        "source": "extra_a",
        "title": "r_bedroom",
    }
    result = await _configure(hass, result, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _subentry(entry, "r_bedroom").data[m.CONF_TEMPERATURE] == [
        house.bedroom_temp,
        first,
    ]
    assert not _subentry(entry, "r_bedroom").data.get(m.CONF_HUMIDITY)

    await _advance(hass, freezer, RELOAD)
    assert set(_all(hass, "new_source_")) == {f"{BEDROOM_ISSUE}{second}"}


async def test_new_source_extends_an_explicit_humidity_list(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    entry = _entry(house)
    entry.add_to_hass(hass)
    living = _subentry(entry, "r_living")
    hass.config_entries.async_update_subentry(
        entry, living, data={**living.data, m.CONF_HUMIDITY: [house.living_hum]}
    )
    await _start(hass, entry)
    new = _add_sensor(hass, house, "extra_living", house.living_room)
    humidity = _add_humidity(hass, house, new)
    await _settle(hass, freezer)
    issue_id = f"new_source_r_living_{new}"
    assert issue_id in _all(hass)

    result = await _init(hass, issue_id)
    result = await _configure(hass, result, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = _subentry(entry, "r_living").data
    assert data[m.CONF_TEMPERATURE][-1] == new
    assert data[m.CONF_HUMIDITY] == [house.living_hum, humidity]

    await _advance(hass, freezer, RELOAD)
    assert issue_id not in _all(hass)


async def test_new_source_aborts_when_the_subentry_is_gone(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    entry = _entry(house)
    await _start(hass, entry)
    new = _add_sensor(hass, house, "extra_a", house.bedroom)
    await _settle(hass, freezer)
    result = await _init(hass, f"{BEDROOM_ISSUE}{new}")
    hass.config_entries.async_remove_subentry(entry, "r_bedroom")
    result = await _configure(hass, result, {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "gone"


# Windows without a room


async def _windows_entry(hass: HomeAssistant, house: House) -> MockConfigEntry:
    entry = _entry(house)
    entry.add_to_hass(hass)
    for sub_id, name, leaf in (
        ("w_b", "Zweites Fenster", house.conservatory_window),
        ("w_a", "Erstes Fenster", house.kitchen_contact),
    ):
        _add_subentry(
            hass,
            entry,
            SUBENTRY_WINDOW,
            sub_id,
            _window_data(house, house.conservatory, name, leaf),
            name,
        )
    return entry


async def test_recreate_room(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    sensor = _add_sensor(hass, house, "conservatory_temp", house.conservatory)
    entry = await _windows_entry(hass, house)
    await _start(hass, entry)
    issue_id = f"windows_without_room_{house.conservatory}"

    result = await _init(hass, issue_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["recreate_room", "delete_windows"]
    assert result["description_placeholders"] == {
        "area": "Wintergarten",
        "windows": "Erstes Fenster und Zweites Fenster",
    }
    result = await _configure(hass, result, {"next_step_id": "recreate_room"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "recreate_room"
    placeholders = result["description_placeholders"]
    assert placeholders["area"] == "Wintergarten"
    assert "conservatory_temp" in placeholders["preview"]

    result = await _configure(hass, result, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    rooms = [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_ROOM]
    room = next(s for s in rooms if s.data[m.CONF_AREA] == house.conservatory)
    assert room.data[m.CONF_TEMPERATURE] == [sensor]
    assert room.title == "Wintergarten"

    await _advance(hass, freezer, RELOAD)
    assert _all(hass, "windows_without_room_") == {}


async def test_delete_windows(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    entry = await _windows_entry(hass, house)
    await _start(hass, entry)
    issue_id = f"windows_without_room_{house.conservatory}"

    result = await _init(hass, issue_id)
    result = await _configure(hass, result, {"next_step_id": "delete_windows"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "delete_windows"
    assert result["description_placeholders"]["windows"] == (
        "Erstes Fenster und Zweites Fenster"
    )
    result = await _configure(hass, result, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert set(entry.subentries) == {"r_living", "r_bedroom", "g_garden", "w_living"}

    await _advance(hass, freezer, RELOAD)
    assert _all(hass, "windows_without_room_") == {}


async def test_windows_flow_aborts_when_the_room_exists_again(
    hass: HomeAssistant, house: House
) -> None:
    entry = await _windows_entry(hass, house)
    await _start(hass, entry)
    result = await _init(hass, f"windows_without_room_{house.conservatory}")
    _add_subentry(
        hass,
        entry,
        SUBENTRY_ROOM,
        "r_conservatory",
        {m.CONF_AREA: house.conservatory, m.CONF_TEMPERATURE: [house.kitchen_temp]},
    )
    result = await _configure(hass, result, {"next_step_id": "delete_windows"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "gone"
