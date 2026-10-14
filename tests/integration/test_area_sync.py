"""Area sync: written after the first evaluation, cleaned up only where still ours."""

from typing import Any

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_hub.const import (
    DOMAIN,
    SUBENTRY_REGION,
    SUBENTRY_ROOM,
)
from custom_components.climate_hub.logic import model as m
from tests.house import House

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


async def _setup(hass: HomeAssistant, house: House) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={m.CONF_WEATHER: house.weather},
        subentries_data=[
            _sub(
                SUBENTRY_ROOM,
                LIVING,
                {
                    m.CONF_AREA: house.living_room,
                    m.CONF_TEMPERATURE: [house.living_temp],
                    m.CONF_HUMIDITY: [house.living_hum],
                },
            ),
            _sub(
                SUBENTRY_ROOM,
                BEDROOM,
                {m.CONF_AREA: house.bedroom, m.CONF_TEMPERATURE: [house.bedroom_temp]},
            ),
            _sub(
                SUBENTRY_REGION,
                STREET,
                {
                    m.CONF_AREA: house.street,
                    m.CONF_DIRECTION: "s",
                    m.CONF_TEMPERATURE: [house.street_temp],
                    m.CONF_HUMIDITY: [house.street_hum],
                },
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _reload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


def _fields(hass: HomeAssistant, area_id: str) -> tuple[str | None, str | None]:
    area = ar.async_get(hass).async_get_area(area_id)
    assert area is not None
    return area.temperature_entity_id, area.humidity_entity_id


async def test_written_after_setup(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house)

    assert _fields(hass, house.living_room) == (
        "sensor.wohnzimmer_klima_temperatur",
        "sensor.wohnzimmer_klima_luftfeuchtigkeit",
    )
    temperature, humidity = _fields(hass, house.bedroom)
    assert temperature == "sensor.schlafzimmer_klima_temperatur"
    assert humidity is None
    temperature, humidity = _fields(hass, house.street)
    assert temperature is not None
    assert humidity is not None
    assert entry.runtime_data.coordinator.area_sync == {
        house.living_room: {
            "temperature": "sensor.wohnzimmer_klima_temperatur",
            "humidity": "sensor.wohnzimmer_klima_luftfeuchtigkeit",
        },
        house.bedroom: {"temperature": "sensor.schlafzimmer_klima_temperatur"},
        house.street: {"temperature": temperature, "humidity": humidity},
    }


async def test_option_off_clears(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house)

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, m.CONF_AREA_SYNC: False}
    )
    await _reload(hass, entry)

    for area_id in (house.living_room, house.bedroom, house.street):
        assert _fields(hass, area_id) == (None, None)
    assert entry.runtime_data.coordinator.area_sync == {}


async def test_deleted_room_clears_its_area(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house)

    hass.config_entries.async_remove_subentry(entry, BEDROOM)
    await hass.async_block_till_done()
    await _reload(hass, entry)

    assert _fields(hass, house.bedroom) == (None, None)
    assert _fields(hass, house.living_room)[0] is not None
    assert house.bedroom not in entry.runtime_data.coordinator.area_sync


async def test_user_changed_field_is_left_alone(
    hass: HomeAssistant, house: House
) -> None:
    entry = await _setup(hass, house)
    ours = _fields(hass, house.living_room)[0]
    assert ours is not None
    ar.async_get(hass).async_update(
        house.living_room, temperature_entity_id=house.bedroom_temp
    )

    await _reload(hass, entry)
    assert _fields(hass, house.living_room)[0] == house.bedroom_temp

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, m.CONF_AREA_SYNC: False}
    )
    await _reload(hass, entry)
    assert _fields(hass, house.living_room) == (house.bedroom_temp, None)

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _fields(hass, house.living_room)[0] == house.bedroom_temp


async def test_removing_the_entry_clears_everything(
    hass: HomeAssistant, house: House
) -> None:
    entry = await _setup(hass, house)

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    for area_id in (house.living_room, house.bedroom, house.street):
        assert _fields(hass, area_id) == (None, None)
