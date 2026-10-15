"""Entities: IDs, devices, values, attributes, conditional entities, numbers."""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.climate_hub.binary_sensor import BINARY_SENSORS
from custom_components.climate_hub.const import (
    CONTACT_RECHECK,
    DOMAIN,
    REFRESH_COOLDOWN,
    SUBENTRY_REGION,
    SUBENTRY_ROOM,
    SUBENTRY_WINDOW,
)
from custom_components.climate_hub.coordinator import ClimateHubCoordinator
from custom_components.climate_hub.entity import ClimateHubEntity
from custom_components.climate_hub.logic import model as m
from custom_components.climate_hub.logic.cover import CoverReason
from custom_components.climate_hub.sensor import SENSORS
from tests.house import House, set_value

LIVING = "r_living"
BEDROOM = "r_bedroom"
STREET = "g_street"


def _sub(kind: str, sub_id: str, data: dict[str, Any]) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=data,
        subentry_type=kind,
        title=sub_id,
        unique_id=None,
        subentry_id=sub_id,
    )


def _subentries(house: House, *, region: bool = True) -> list[ConfigSubentryData]:
    subs = [
        _sub(
            SUBENTRY_ROOM,
            LIVING,
            {
                m.CONF_AREA: house.living_room,
                m.CONF_SIDE: "s",
                m.CONF_TEMPERATURE: [house.living_temp, house.living_air_temp],
            },
        ),
        _sub(
            SUBENTRY_ROOM,
            BEDROOM,
            {m.CONF_AREA: house.bedroom, m.CONF_TEMPERATURE: [house.bedroom_temp]},
        ),
    ]
    if region:
        subs.append(
            _sub(
                SUBENTRY_REGION,
                STREET,
                {
                    m.CONF_AREA: house.street,
                    m.CONF_DIRECTION: "s",
                    m.CONF_TEMPERATURE: [house.street_temp],
                    m.CONF_HUMIDITY: [house.street_hum],
                },
            )
        )
    return subs


async def _setup(
    hass: HomeAssistant,
    house: House,
    *,
    region: bool = True,
    weather: bool = True,
    subentries: list[ConfigSubentryData] | None = None,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={m.CONF_WEATHER: house.weather} if weather else {},
        subentries_data=subentries or _subentries(house, region=region),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _reload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity_id: str) -> State:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state


def _unique_ids(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    registry = er.async_get(hass)
    return {
        e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }


def _device(hass: HomeAssistant, owner_id: str) -> dr.DeviceEntry:
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, owner_id), entry.entry_id
    )
    assert device is not None
    return device


async def test_entity_ids_and_values(hass: HomeAssistant, house: House) -> None:
    await _setup(hass, house)

    temperature = _state(hass, "sensor.wohnzimmer_klima_temperatur")
    assert float(temperature.state) == pytest.approx(21.4, abs=0.01)
    assert temperature.attributes["unit_of_measurement"] == "°C"
    assert temperature.attributes["device_class"] == "temperature"
    assert temperature.attributes["state_class"] == "measurement"
    assert temperature.attributes["friendly_name"] == "Klima Temperatur"

    assert _state(hass, "sensor.wohnzimmer_klima_empfehlung").state in {
        "open",
        "keep_open",
        "close",
        "keep_closed",
        "none",
    }
    assert _state(hass, "sensor.strasse_klima_temperatur").state == "13.0"
    assert _state(hass, "sensor.wohnzimmer_klima_luftfeuchtigkeit").state == "48.0"
    assert _state(hass, "sensor.wohnzimmer_klima_luftdruck").state == "1012.0"
    delta = _state(hass, "sensor.wohnzimmer_klima_temperaturdifferenz_aussen")
    assert delta.attributes["device_class"] == "temperature_delta"
    assert _state(hass, "sensor.wohnzimmer_klima_aussen").state in {
        "warmer",
        "colder",
        "similar",
    }
    assert _state(hass, "sensor.wohnzimmer_klima_wunschbereich").state in {
        "below",
        "within",
        "above",
    }
    assert _state(hass, "sensor.hausklima_innen_durchschnitt").state != "unknown"
    assert _state(hass, "sensor.hausklima_aussen").state == "13.0"
    assert _state(hass, "sensor.hausklima_tagesstrategie").state in {
        "prevent_heat_up",
        "prevent_cool_down",
        "neutral",
    }
    assert _state(hass, "number.hausklima_wunschtemperatur_max").state == "24.0"


async def test_attributes_per_stage(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house)
    entity_id = "sensor.wohnzimmer_klima_temperatur"

    attributes = _state(hass, entity_id).attributes
    assert attributes["source"] == house.living_temp
    assert attributes["stage"] == "primary"
    assert "reason" not in attributes
    assert "offset" not in attributes

    set_value(hass, house.living_temp, "unavailable")
    await _refresh(hass, entry)
    state = _state(hass, entity_id)
    assert float(state.state) == pytest.approx(21.7, abs=0.5)
    assert state.attributes["source"] == house.living_air_temp
    assert state.attributes["stage"] == "fallback"
    assert state.attributes["reason"] == "unavailable"
    assert "offset" in state.attributes

    recommendation = _state(hass, "sensor.wohnzimmer_klima_empfehlung")
    assert recommendation.attributes["reason"]

    street = _state(hass, "sensor.strasse_klima_temperatur")
    assert street.attributes["source"] == house.street_temp
    assert street.attributes["stage"] == "primary"
    assert street.attributes["regions"] == ["s"]

    hub = _state(hass, "sensor.hausklima_aussen")
    assert hub.attributes["stage"] == "primary"
    assert hub.attributes["per_region"] == {"s": 13.0}

    set_value(hass, house.street_temp, "unavailable")
    await _refresh(hass, entry)
    outside = _state(hass, "sensor.wohnzimmer_klima_aussentemperatur")
    assert outside.attributes["stage"] == "weather"
    assert "offset" in outside.attributes
    assert "reason" not in outside.attributes


def test_unrecorded_attributes() -> None:
    assert {"offset", "per_region"} <= ClimateHubEntity._unrecorded_attributes


async def test_missing_humidity_removes_entities(
    hass: HomeAssistant, house: House
) -> None:
    entry = await _setup(hass, house)
    for key in (
        "humidity",
        "absolute_humidity",
        "dew_point",
        "humidity_difference",
        "pressure",
    ):
        assert f"{LIVING}_{key}" in _unique_ids(hass, entry)
    # The bedroom has only a temperature source (I12).
    ids = _unique_ids(hass, entry)
    for key in (
        "humidity",
        "pressure",
        "absolute_humidity",
        "dew_point",
        "humidity_difference",
    ):
        assert f"{BEDROOM}_{key}" not in ids
    for key in ("temperature", "outside_temperature", "temperature_difference"):
        assert f"{BEDROOM}_{key}" in ids


async def test_without_regions_and_weather(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house, region=False, weather=False)
    ids = _unique_ids(hass, entry)
    for key in (
        "outside_temperature",
        "outside_humidity",
        "temperature_difference",
        "humidity_difference",
        "outside",
    ):
        assert f"{LIVING}_{key}" not in ids
    assert f"{entry.entry_id}_outdoor" not in ids
    assert f"{entry.entry_id}_strategy" not in ids
    assert f"{entry.entry_id}_indoor_average" in ids
    assert f"{LIVING}_temperature" in ids
    assert f"{LIVING}_recommendation" in ids


async def test_strategy_needs_weather(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house, weather=False)
    ids = _unique_ids(hass, entry)
    assert f"{entry.entry_id}_strategy" not in ids
    assert f"{entry.entry_id}_outdoor" in ids
    assert f"{LIVING}_outside_temperature" in ids


async def test_stale_entities_removed_on_reload(
    hass: HomeAssistant, house: House
) -> None:
    subentries = _subentries(house)
    subentries[1]["data"][m.CONF_HUMIDITY] = [house.study_hum]
    entry = await _setup(hass, house, subentries=subentries)
    assert f"{BEDROOM}_humidity" in _unique_ids(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{BEDROOM}_humidity")
    assert entity_id

    subentry = entry.subentries[BEDROOM]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, m.CONF_HUMIDITY: []}
    )
    await hass.async_block_till_done()
    await _reload(hass, entry)

    assert f"{BEDROOM}_humidity" not in _unique_ids(hass, entry)
    assert registry.async_get(entity_id) is None


async def test_unique_ids_and_subentries(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house)
    registry = er.async_get(hass)
    ids = _unique_ids(hass, entry)
    assert f"{LIVING}_temperature" in ids
    assert f"{STREET}_temperature" in ids
    assert f"{entry.entry_id}_comfort_max" in ids
    assert all(
        uid.startswith((f"{LIVING}_", f"{BEDROOM}_", f"{STREET}_", entry.entry_id))
        for uid in ids
    )
    room = registry.async_get("sensor.wohnzimmer_klima_temperatur")
    assert room is not None
    assert room.config_subentry_id == LIVING
    hub = registry.async_get("number.hausklima_wunschtemperatur_max")
    assert hub is not None
    assert hub.config_subentry_id is None


async def test_devices_and_areas(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house)

    hub = _device(hass, entry.entry_id)
    assert hub.name == "Hausklima"
    assert hub.entry_type is dr.DeviceEntryType.SERVICE
    assert hub.area_id is None
    assert hub.config_subentry_id is None

    living = _device(hass, LIVING)
    assert living.name == "Klima"
    assert living.area_id == house.living_room
    assert living.config_subentry_id == LIVING
    assert _device(hass, BEDROOM).area_id == house.bedroom
    assert _device(hass, STREET).area_id == house.street
    assert _device(hass, STREET).name == "Klima"


async def test_manual_move_stays_and_area_change_moves(
    hass: HomeAssistant, house: House
) -> None:
    entry = await _setup(hass, house)
    devices = dr.async_get(hass)
    device = _device(hass, LIVING)

    devices.async_update_device(device.id, area_id=house.kitchen)
    await _reload(hass, entry)
    assert _device(hass, LIVING).area_id == house.kitchen

    subentry = entry.subentries[LIVING]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, m.CONF_AREA: house.study}
    )
    await hass.async_block_till_done()
    await _reload(hass, entry)
    assert _device(hass, LIVING).area_id == house.study


async def test_entity_id_parts_without_area(hass: HomeAssistant, house: House) -> None:
    er.async_get(hass).async_update_settings(
        entity_id_parts=[er.EntityNamePart.DEVICE, er.EntityNamePart.ENTITY]
    )
    entry = await _setup(hass, house)
    assert _device(hass, LIVING).name == "Wohnzimmer Klima"
    assert _device(hass, STREET).name == "Straße Klima"
    assert _device(hass, entry.entry_id).name == "Hausklima"
    assert _state(hass, "sensor.wohnzimmer_klima_temperatur")


async def test_set_comfort_via_number(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house)
    coordinator: ClimateHubCoordinator = entry.runtime_data.coordinator

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.hausklima_wunschtemperatur_max", "value": 26},
        blocking=True,
    )
    assert coordinator.comfort.c_max == 26.0
    assert _state(hass, "number.hausklima_wunschtemperatur_max").state == "26.0"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.hausklima_wunschtemperatur_min", "value": 28},
            blocking=True,
        )
    assert coordinator.comfort.c_min == 20.0

    state = _state(hass, "number.hausklima_schwelle")
    assert state.attributes["min"] == 0.5
    assert state.attributes["max"] == 10
    assert state.attributes["step"] == 0.5
    assert state.attributes["device_class"] == "temperature_delta"


async def test_english_instance(hass: HomeAssistant, house: House) -> None:
    hass.config.language = "en"
    entry = await _setup(hass, house)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{LIVING}_temperature")
    assert entity_id
    assert _state(hass, entity_id).attributes["friendly_name"] == "Climate Temperature"
    assert _device(hass, entry.entry_id).name == "Home climate"
    recommendation = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{LIVING}_recommendation"
    )
    assert recommendation
    assert (
        _state(hass, recommendation).attributes["friendly_name"]
        == "Climate Recommendation"
    )


@pytest.mark.parametrize("language", ["de", "en"])
def test_enum_options_are_translated(language: str) -> None:
    path = (
        Path(__file__).parents[2]
        / "custom_components"
        / "climate_hub"
        / "translations"
        / f"{language}.json"
    )
    entity = json.loads(path.read_text(encoding="utf-8"))["entity"]
    for description in SENSORS:
        translation = entity["sensor"][description.key]
        assert translation["name"]
        for option in description.options or []:
            assert option in translation["state"], (description.key, option)
    for description in BINARY_SENSORS:
        assert entity["binary_sensor"][description.key]["name"]


# Windows (step 14)

WINDOW_KITCHEN = "w_kitchen"
WINDOW_LIVING = "w_living"
WINDOW_THROUGH = "w_through"
WINDOW_BATH = "w_bath"
KITCHEN = "r_kitchen"
WINDOW_IDS = (WINDOW_KITCHEN, WINDOW_LIVING, WINDOW_THROUGH, WINDOW_BATH)
HUB_ANY = (
    "any_cooling_down",
    "any_heating_up",
    "any_open_while_conditioning",
    "any_cover_to_close",
)
ROOM_WINDOW_KEYS = (
    "window",
    "window_open_since",
    "cooling_down",
    "heating_up",
    "open_while_conditioning",
)
COVER_FLAG = "binary_sensor.hausklima_irgendwo_rollladen_schliessen"


def _window_subentries(house: House, *, cover: bool = True) -> list[ConfigSubentryData]:
    subs = _subentries(house)
    subs[0]["data"][m.CONF_CLIMATE_DEVICES] = [house.living_thermostat]
    living = {
        m.CONF_AREA: house.living_room,
        m.CONF_NAME: "Fenster",
        m.CONF_TYPE: m.WINDOW_DOUBLE,
        m.CONF_LEAF_LEFT: house.living_leaf_1,
        m.CONF_LEAF_RIGHT: house.living_leaf_2,
        m.CONF_TILT: house.living_bottom,
    }
    if cover:
        living[m.CONF_COVER] = house.living_cover
    return [
        *subs,
        _sub(
            SUBENTRY_ROOM,
            KITCHEN,
            {m.CONF_AREA: house.kitchen, m.CONF_TEMPERATURE: [house.kitchen_temp]},
        ),
        _sub(
            SUBENTRY_WINDOW,
            WINDOW_KITCHEN,
            {
                m.CONF_AREA: house.kitchen,
                m.CONF_NAME: "Fenster",
                m.CONF_TYPE: m.WINDOW_SINGLE,
                m.CONF_LEAF: house.kitchen_contact,
            },
        ),
        _sub(SUBENTRY_WINDOW, WINDOW_LIVING, living),
        _sub(
            SUBENTRY_WINDOW,
            WINDOW_THROUGH,
            {
                m.CONF_AREA: house.conservatory,
                m.CONF_NAME: "Tür",
                m.CONF_TYPE: m.WINDOW_PASS_THROUGH,
                m.CONF_INNER: house.study_door,
                m.CONF_OUTER: house.conservatory_window,
            },
        ),
        _sub(
            SUBENTRY_WINDOW,
            WINDOW_BATH,
            {
                m.CONF_AREA: house.bathroom,
                m.CONF_NAME: "Fenster",
                m.CONF_TYPE: m.WINDOW_SINGLE,
                m.CONF_LEAF: house.bath_window_text,
                m.CONF_MAPPINGS: {
                    house.bath_window_text: {
                        "closed": ["zu"],
                        "ajar": [],
                        "tilted": ["gekippt"],
                        "open": ["offen"],
                    }
                },
            },
        ),
    ]


async def _setup_windows(
    hass: HomeAssistant, house: House, *, cover: bool = True
) -> MockConfigEntry:
    return await _setup(hass, house, subentries=_window_subentries(house, cover=cover))


async def _publish(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, entry: MockConfigEntry
) -> None:
    """Let the refresh cooldown and then the contact debounce pass."""
    for delta in (REFRESH_COOLDOWN, CONTACT_RECHECK):
        freezer.tick(delta + timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, unique_id
    return entity_id


async def test_window_entities_and_states(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    entry = await _setup_windows(hass, house)

    for entity_id in (
        "sensor.kuche_fenster_zustand",
        "sensor.wohnzimmer_fenster_zustand",
        "sensor.wohnzimmer_klima_fenster",
        "sensor.kuche_klima_fenster",
    ):
        assert _state(hass, entity_id).state == "closed", entity_id
    assert _state(hass, "sensor.wohnzimmer_fenster_rollladen")
    assert _state(hass, "sensor.kuche_fenster_offen_seit").state == "unknown"
    assert _state(hass, "binary_sensor.wohnzimmer_klima_auskuhlen")
    assert _state(hass, "binary_sensor.wohnzimmer_klima_aufheizen")

    set_value(hass, house.kitchen_contact, "on")
    set_value(hass, house.living_leaf_2, "on")
    set_value(hass, house.bath_window_text, "gekippt")
    await hass.async_block_till_done()
    await _publish(hass, freezer, entry)

    assert _state(hass, "sensor.kuche_fenster_zustand").state == "open"
    assert _state(hass, "sensor.kuche_klima_fenster").state == "open"
    assert _state(hass, "sensor.kuche_fenster_offen_seit").state != "unknown"
    assert _state(hass, "sensor.kuche_klima_fenster_offen_seit").state != "unknown"
    living = _state(hass, "sensor.wohnzimmer_fenster_zustand")
    # A moved leaf with the bottom (tilt) contact closed is tilted.
    assert living.state == "tilted"
    assert living.attributes["open_leaves"] == "right"
    assert _state(hass, "sensor.wohnzimmer_klima_fenster").state == "tilted"
    bath = _state(hass, _entity_id(hass, "sensor", f"{WINDOW_BATH}_state"))
    assert bath.state == "tilted"
    assert "open_leaves" not in bath.attributes
    assert "open_leaves" not in _state(hass, "sensor.kuche_fenster_zustand").attributes

    set_value(hass, house.kitchen_contact, "off")
    set_value(hass, house.living_leaf_2, "off")
    await hass.async_block_till_done()
    await _publish(hass, freezer, entry)
    assert _state(hass, "sensor.kuche_fenster_zustand").state == "closed"
    assert _state(hass, "sensor.wohnzimmer_fenster_zustand").state == "closed"


async def test_pass_through_window(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    entry = await _setup_windows(hass, house)
    state_id = _entity_id(hass, "sensor", f"{WINDOW_THROUGH}_state")
    assert state_id == "sensor.wintergarten_tur_zustand"
    assert _state(hass, state_id).state == "closed"
    set_value(hass, house.study_door, "on")
    set_value(hass, house.conservatory_window, "on")
    await hass.async_block_till_done()
    await _publish(hass, freezer, entry)
    assert _state(hass, state_id).state == "open"
    assert "open_leaves" not in _state(hass, state_id).attributes


async def test_window_unique_ids_and_subentries(
    hass: HomeAssistant, house: House
) -> None:
    entry = await _setup_windows(hass, house)
    ids = _unique_ids(hass, entry)
    for window in WINDOW_IDS:
        for key in ("state", "open_since", "cover"):
            assert f"{window}_{key}" in ids
    registry = er.async_get(hass)
    zustand = registry.async_get("sensor.kuche_fenster_zustand")
    assert zustand is not None
    assert zustand.unique_id == f"{WINDOW_KITCHEN}_state"
    assert zustand.config_subentry_id == WINDOW_KITCHEN
    flag = registry.async_get("binary_sensor.wohnzimmer_klima_auskuhlen")
    assert flag is not None
    assert flag.unique_id == f"{LIVING}_cooling_down"
    assert flag.config_subentry_id == LIVING


async def test_room_entities_follow_windows_and_climate_devices(
    hass: HomeAssistant, house: House
) -> None:
    entry = await _setup_windows(hass, house)
    ids = _unique_ids(hass, entry)
    for room in (LIVING, KITCHEN):
        for key in ("window", "window_open_since", "cooling_down", "heating_up"):
            assert f"{room}_{key}" in ids
    assert f"{LIVING}_open_while_conditioning" in ids
    assert f"{KITCHEN}_open_while_conditioning" not in ids  # no climate devices
    for key in ROOM_WINDOW_KEYS:
        assert f"{BEDROOM}_{key}" not in ids  # no windows
    for key in HUB_ANY:
        assert f"{entry.entry_id}_{key}" in ids


async def test_hub_open_while_conditioning_needs_climate_devices(
    hass: HomeAssistant, house: House
) -> None:
    subs = _window_subentries(house)
    del subs[0]["data"][m.CONF_CLIMATE_DEVICES]
    entry = await _setup(hass, house, subentries=subs)
    ids = _unique_ids(hass, entry)
    assert f"{entry.entry_id}_any_cooling_down" in ids
    assert f"{entry.entry_id}_any_cover_to_close" in ids
    assert f"{entry.entry_id}_any_open_while_conditioning" not in ids
    assert f"{LIVING}_open_while_conditioning" not in ids


async def test_no_windows_no_window_entities(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house)
    ids = _unique_ids(hass, entry)
    assert not {uid for uid in ids if uid.endswith(ROOM_WINDOW_KEYS)}
    for key in HUB_ANY:
        assert f"{entry.entry_id}_{key}" not in ids


async def test_removing_windows_removes_entities(
    hass: HomeAssistant, house: House
) -> None:
    entry = await _setup_windows(hass, house)
    registry = er.async_get(hass)
    assert registry.async_get("sensor.wohnzimmer_klima_fenster")
    for window in WINDOW_IDS:
        hass.config_entries.async_remove_subentry(entry, window)
    await hass.async_block_till_done()
    await _reload(hass, entry)

    ids = _unique_ids(hass, entry)
    assert not {uid for uid in ids if uid.startswith("w_")}
    for room in (LIVING, KITCHEN):
        for key in ROOM_WINDOW_KEYS:
            assert f"{room}_{key}" not in ids
    for key in HUB_ANY:
        assert f"{entry.entry_id}_{key}" not in ids
    assert registry.async_get("sensor.wohnzimmer_klima_fenster") is None
    assert f"{LIVING}_temperature" in ids


async def test_cover_sensor_enable_rule(hass: HomeAssistant, house: House) -> None:
    await _setup_windows(hass, house)
    registry = er.async_get(hass)
    with_cover = registry.async_get("sensor.wohnzimmer_fenster_rollladen")
    assert with_cover is not None
    assert with_cover.disabled_by is None
    cover = _state(hass, "sensor.wohnzimmer_fenster_rollladen")
    assert cover.state in {"close", "keep_closed", "open", "keep_open", "none"}
    assert cover.attributes["reason"]

    without = registry.async_get(_entity_id(hass, "sensor", f"{WINDOW_KITCHEN}_cover"))
    assert without is not None
    assert without.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(without.entity_id) is None


async def test_cover_added_later_enables_the_sensor(
    hass: HomeAssistant, house: House
) -> None:
    """I6: a disabled cover entity is enabled when the window gets a cover."""
    entry = await _setup_windows(hass, house, cover=False)
    registry = er.async_get(hass)
    entity_id = _entity_id(hass, "sensor", f"{WINDOW_LIVING}_cover")
    disabled = registry.async_get(entity_id)
    assert disabled is not None
    assert disabled.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entity_id) is None

    subentry = entry.subentries[WINDOW_LIVING]
    with_cover = {**subentry.data, m.CONF_COVER: house.living_cover}
    hass.config_entries.async_update_subentry(entry, subentry, data=with_cover)
    await hass.async_block_till_done()
    await _reload(hass, entry)
    enabled = registry.async_get(entity_id)
    assert enabled is not None
    assert enabled.disabled_by is None
    assert hass.states.get(entity_id) is not None

    # Removing the cover again changes nothing.
    without_cover = {k: v for k, v in with_cover.items() if k != m.CONF_COVER}
    hass.config_entries.async_update_subentry(
        entry, entry.subentries[WINDOW_LIVING], data=without_cover
    )
    await hass.async_block_till_done()
    await _reload(hass, entry)
    still = registry.async_get(entity_id)
    assert still is not None
    assert still.disabled_by is None


async def test_any_cover_to_close_attribute(hass: HomeAssistant, house: House) -> None:
    entry = await _setup_windows(hass, house)
    coordinator: ClimateHubCoordinator = entry.runtime_data.coordinator
    assert _state(hass, COVER_FLAG).state in {"on", "off"}

    data = coordinator.data
    assert data.house is not None
    forced = replace(
        data.house,
        any_cover_to_close=True,
        covers_to_close=(
            (WINDOW_LIVING, CoverReason.SUN_HEAT),
            (WINDOW_KITCHEN, CoverReason.INSULATE),
            ("w_unknown", CoverReason.NIGHT),  # no registered cover sensor
        ),
    )
    coordinator.async_set_updated_data(replace(data, house=forced))
    await hass.async_block_till_done()

    state = _state(hass, COVER_FLAG)
    assert state.state == "on"
    assert state.attributes["windows"] == [
        {"entity_id": "sensor.wohnzimmer_fenster_rollladen", "reason": "sun_heat"},
        {
            "entity_id": _entity_id(hass, "sensor", f"{WINDOW_KITCHEN}_cover"),
            "reason": "insulate",
        },
    ]


async def test_window_device(hass: HomeAssistant, house: House) -> None:
    await _setup_windows(hass, house)
    kitchen = _device(hass, WINDOW_KITCHEN)
    assert kitchen.name == "Fenster"
    assert kitchen.area_id == house.kitchen
    assert kitchen.config_subentry_id == WINDOW_KITCHEN
    through = _device(hass, WINDOW_THROUGH)
    assert through.name == "Tür"
    assert through.area_id == house.conservatory


async def test_window_rename_and_area_change(hass: HomeAssistant, house: House) -> None:
    entry = await _setup_windows(hass, house)
    subentry = entry.subentries[WINDOW_KITCHEN]
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data={**subentry.data, m.CONF_NAME: "Balkontür", m.CONF_AREA: house.study},
    )
    await hass.async_block_till_done()
    await _reload(hass, entry)
    device = _device(hass, WINDOW_KITCHEN)
    assert device.name == "Balkontür"
    assert device.area_id == house.study
    # Entity IDs never change (rule 1).
    assert _state(hass, "sensor.kuche_fenster_zustand")


async def test_window_device_name_without_area_in_entity_ids(
    hass: HomeAssistant, house: House
) -> None:
    er.async_get(hass).async_update_settings(
        entity_id_parts=[er.EntityNamePart.DEVICE, er.EntityNamePart.ENTITY]
    )
    await _setup_windows(hass, house)
    assert _device(hass, WINDOW_KITCHEN).name == "Küche Fenster"
    assert _device(hass, WINDOW_THROUGH).name == "Wintergarten Tür"
    assert _state(hass, "sensor.kuche_fenster_zustand")


async def test_english_window_entities(hass: HomeAssistant, house: House) -> None:
    hass.config.language = "en"
    await _setup_windows(hass, house)
    names = {
        _entity_id(hass, "sensor", f"{WINDOW_LIVING}_state"): "Fenster State",
        _entity_id(hass, "sensor", f"{LIVING}_window_open_since"): (
            "Climate Window open since"
        ),
        _entity_id(hass, "binary_sensor", f"{LIVING}_open_while_conditioning"): (
            "Climate Open while heating/cooling"
        ),
    }
    for entity_id, name in names.items():
        assert _state(hass, entity_id).attributes["friendly_name"] == name
