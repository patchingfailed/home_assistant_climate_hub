"""Entities: IDs, devices, values, attributes, conditional entities, numbers."""

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_hub.const import (
    DOMAIN,
    SUBENTRY_REGION,
    SUBENTRY_ROOM,
)
from custom_components.climate_hub.coordinator import ClimateHubCoordinator
from custom_components.climate_hub.entity import ClimateHubEntity
from custom_components.climate_hub.logic import model as m
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
    sensors = json.loads(path.read_text(encoding="utf-8"))["entity"]["sensor"]
    for description in SENSORS:
        translation = sensors[description.key]
        assert translation["name"]
        for option in description.options or []:
            assert option in translation["state"], (description.key, option)
