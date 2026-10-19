"""Room readings (R16) and setpoint deviation (R17): entities, attributes, labels."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er

from custom_components.climate_hub import labels
from custom_components.climate_hub.const import DOMAIN
from custom_components.climate_hub.logic import model as m
from tests.house import House, set_value

from .test_entities import (
    BEDROOM,
    LIVING,
    _refresh,
    _reload,
    _setup,
    _state,
    _subentries,
    _unique_ids,
)

TEMPERATURE_SPREAD = "sensor.wohnzimmer_klima_temperaturspanne"
HUMIDITY_SPREAD = "sensor.wohnzimmer_klima_feuchtespanne"
SETPOINT = "sensor.wohnzimmer_klima_abweichung_vom_soll"
SPREADS = ("temperature_spread", "humidity_spread")


def _living(subentries: list[Any], **data: Any) -> list[Any]:
    subentries[0]["data"].update(data)
    return subentries


def _thermostat_room(house: House, *devices: str) -> list[Any]:
    return _living(
        _subentries(house),
        temperature=[house.living_temp, house.living_air_temp],
        climate_devices=list(devices or [house.living_thermostat]),
    )


async def test_spread_entities_need_two_sources(
    hass: HomeAssistant, house: House
) -> None:
    entry = await _setup(hass, house)
    ids = _unique_ids(hass, entry)
    assert f"{LIVING}_temperature_spread" in ids  # two temperature sources
    assert f"{LIVING}_humidity_spread" not in ids  # no humidity source
    assert f"{LIVING}_setpoint_deviation" not in ids  # no climate device
    for key in (*SPREADS, "setpoint_deviation"):
        assert f"{BEDROOM}_{key}" not in ids  # one temperature source


async def test_humidity_spread_follows_the_humidity_source_count(
    hass: HomeAssistant, house: House
) -> None:
    two = _living(_subentries(house), humidity=[house.living_hum, house.study_hum])
    entry = await _setup(hass, house, subentries=two)
    assert f"{LIVING}_humidity_spread" in _unique_ids(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)

    one = _living(_subentries(house), humidity=[house.living_hum])
    entry = await _setup(hass, house, subentries=one)
    assert f"{LIVING}_humidity_spread" not in _unique_ids(hass, entry)


async def test_switching_readings_off_removes_the_spread_entities(
    hass: HomeAssistant, house: House
) -> None:
    subentries = _living(
        _subentries(house),
        humidity=[house.living_hum, house.study_hum],
        climate_devices=[house.living_thermostat],
    )
    entry = await _setup(hass, house, subentries=subentries)
    assert {f"{LIVING}_{key}" for key in SPREADS} <= _unique_ids(hass, entry)

    subentry = entry.subentries[LIVING]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, m.CONF_SHOW_READINGS: False}
    )
    await hass.async_block_till_done()
    await _reload(hass, entry)
    ids = _unique_ids(hass, entry)
    assert not {f"{LIVING}_{key}" for key in SPREADS} & ids
    assert f"{LIVING}_setpoint_deviation" in ids  # not part of the switch


async def test_readings_use_labels_in_rank_order(
    hass: HomeAssistant, house: House
) -> None:
    # The area name inside a friendly name is dropped from the label.
    set_value(hass, house.living_temp, 21.4, friendly_name="Wohnzimmer Bett Temp")
    set_value(hass, house.living_air_temp, 21.9)
    await _setup(hass, house)
    state = _state(hass, TEMPERATURE_SPREAD)
    assert float(state.state) == 0.5
    assert state.attributes["device_class"] == "temperature_delta"
    readings = state.attributes["readings"]
    assert list(readings) == ["Bett", "Luftmesser"]
    assert readings == {"Bett": 21.4, "Luftmesser": 21.9}


async def test_readings_are_null_for_an_unavailable_source(
    hass: HomeAssistant, house: House
) -> None:
    entry = await _setup(hass, house)
    set_value(hass, house.living_air_temp, "unavailable")
    await _refresh(hass, entry)
    state = _state(hass, TEMPERATURE_SPREAD)
    assert state.state == "unknown"
    assert state.attributes["readings"] == {
        "Klimasensor": 21.4,
        "Luftmesser": None,
    }


async def test_humidity_readings(hass: HomeAssistant, house: House) -> None:
    subentries = _living(
        _subentries(house), humidity=[house.living_hum, house.study_hum]
    )
    await _setup(hass, house, subentries=subentries)
    state = _state(hass, HUMIDITY_SPREAD)
    assert state.attributes["unit_of_measurement"] == "%"
    first, second = state.attributes["readings"].values()
    assert first == 48.0
    assert float(state.state) == abs(first - second)


async def test_setpoint_deviation_of_a_heat_device(
    hass: HomeAssistant, house: House
) -> None:
    await _setup(hass, house, subentries=_thermostat_room(house))
    state = _state(hass, SETPOINT)
    assert float(state.state) == 0.4  # room 21.4 against the fixture setpoint 21.0
    assert state.attributes["device"] == house.living_thermostat
    assert state.attributes["setpoint"] == 21.0
    assert "setpoint_low" not in state.attributes
    assert state.attributes["devices"] == {
        "Thermostat": {"mode": "heat", "setpoint": 21.0, "current": 22.6}
    }


async def test_setpoint_deviation_of_a_range(hass: HomeAssistant, house: House) -> None:
    attrs = dict(hass.states.get(house.living_thermostat).attributes)
    del attrs["temperature"]
    attrs.update(target_temp_low=20.0, target_temp_high=23.0)
    hass.states.async_set(house.living_thermostat, "heat_cool", attrs)
    await _setup(hass, house, subentries=_thermostat_room(house))
    state = _state(hass, SETPOINT)
    assert float(state.state) == 0.0  # room 21.4 inside 20.0 to 23.0
    assert state.attributes["setpoint_low"] == 20.0
    assert state.attributes["setpoint_high"] == 23.0
    assert "setpoint" not in state.attributes
    assert state.attributes["devices"]["Thermostat"]["setpoint_low"] == 20.0


async def test_setpoint_deviation_skips_a_device_that_is_off(
    hass: HomeAssistant, house: House
) -> None:
    set_value(hass, house.living_thermostat, "off")
    set_value(hass, house.kitchen_thermostat, "heat", temperature=20.0)
    subentries = _thermostat_room(
        house, house.living_thermostat, house.kitchen_thermostat
    )
    await _setup(hass, house, subentries=subentries)
    state = _state(hass, SETPOINT)
    assert state.attributes["device"] == house.kitchen_thermostat
    assert float(state.state) == 1.4
    # Both are named "Thermostat": the labels come from the entity IDs
    devices = state.attributes["devices"]
    assert devices["Thermostat"]["mode"] == "off"
    assert devices["Kueche Thermostat"]["mode"] == "heat"


async def test_setpoint_without_a_regulating_device_is_unknown(
    hass: HomeAssistant, house: House
) -> None:
    set_value(hass, house.living_thermostat, "off")
    await _setup(hass, house, subentries=_thermostat_room(house))
    state = _state(hass, SETPOINT)
    assert state.state == "unknown"
    assert "device" not in state.attributes
    assert state.attributes["devices"]["Thermostat"]["mode"] == "off"


async def test_english_entity_ids(hass: HomeAssistant, house: House) -> None:
    hass.config.language = "en"
    await _setup(hass, house, subentries=_thermostat_room(house))
    registry = er.async_get(hass)
    found = {
        key: registry.async_get_entity_id("sensor", DOMAIN, f"{LIVING}_{key}")
        for key in ("temperature_spread", "setpoint_deviation")
    }
    assert found == {
        "temperature_spread": "sensor.wohnzimmer_climate_temperature_spread",
        "setpoint_deviation": "sensor.wohnzimmer_climate_deviation_from_setpoint",
    }


async def test_area_words_include_aliases(hass: HomeAssistant, house: House) -> None:
    ar.async_get(hass).async_update(house.living_room, aliases={"Stube", "Gute Stube"})
    assert labels.area_words(hass, house.living_room) == {
        "wohnzimmer",
        "stube",
        "gute",
    }
    assert labels.area_words(hass, "no_such_area") == set()


async def test_source_labels_and_entity_name(hass: HomeAssistant, house: House) -> None:
    assert labels.entity_name(hass, house.living_temp) == "Klimasensor Temperatur"
    assert labels.entity_name(hass, "sensor.nothing") == "sensor.nothing"
    result = labels.source_labels(
        hass,
        house.living_room,
        [house.living_temp, house.living_air_temp],
        {"temperatur", "temperature"},
    )
    assert result == {
        house.living_temp: "Klimasensor",
        house.living_air_temp: "Luftmesser",
    }
