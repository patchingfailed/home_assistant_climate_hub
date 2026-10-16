"""Registry adapter: infos, follow, room proposal, house model (integration.md 3)."""

from typing import Any

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_hub import registry
from custom_components.climate_hub.const import (
    DOMAIN,
    SUBENTRY_REGION,
    SUBENTRY_ROOM,
    SUBENTRY_WINDOW,
)
from custom_components.climate_hub.logic import model as m
from custom_components.climate_hub.logic.outdoor import Direction
from custom_components.climate_hub.logic.prefill import (
    EntityInfo,
    Exclusion,
    Scope,
    classify,
    propose_rooms,
    suggest_sources,
)
from custom_components.climate_hub.logic.sources import Metric
from tests.house import House

TEMP, HUM, PRESS = Metric.TEMPERATURE, Metric.HUMIDITY, Metric.PRESSURE
OUTSIDE_WORDS = ["Außen", "Garten", "Hof", "Terrasse"]


def _by_id(hass: HomeAssistant) -> dict[str, EntityInfo]:
    return {i.entity_id: i for i in registry.entity_infos(hass)}


# Entity infos


async def test_effective_areas(hass: HomeAssistant, house: House) -> None:
    infos = _by_id(hass)
    assert infos[house.living_temp].area_id == house.living_room  # via device
    assert infos[house.bath_window_text].area_id == house.bathroom  # own area
    assert infos[house.template_temp].area_id is None


async def test_entity_fields(hass: HomeAssistant, house: House) -> None:
    infos = _by_id(hass)
    temp = infos[house.living_temp]
    assert temp.device_class == "temperature"
    assert temp.domain == "sensor"
    assert temp.platform == "test"
    assert temp.category is None
    assert temp.value == 21.4
    assert temp.name == "Klimasensor Temperatur"
    assert infos[house.living_hum].value == 48
    assert infos[house.living_pressure].value == 1012
    assert infos[house.plug_temp].category == "diagnostic"
    thermostat = infos[house.living_thermostat]
    assert thermostat.value == 22.6
    assert thermostat.has_current_humidity
    assert not infos[house.kitchen_thermostat].has_current_humidity
    assert infos[house.living_cover].value is None


async def test_state_only_and_disabled(hass: HomeAssistant, house: House) -> None:
    hass.states.async_set(
        "sensor.state_only",
        "17.5",
        {
            "friendly_name": "Nur Zustand",
            "device_class": "temperature",
            "unit_of_measurement": "°C",
        },
    )
    hass.states.async_set("sensor.bare", "1")
    er.async_get(hass).async_update_entity(
        house.bedroom_temp, disabled_by=er.RegistryEntryDisabler.USER
    )
    infos = _by_id(hass)
    only = infos["sensor.state_only"]
    assert (only.platform, only.device_id, only.area_id, only.category) == (
        "",
        None,
        None,
        None,
    )
    assert only.name == "Nur Zustand"
    assert only.value == 17.5
    assert infos["sensor.bare"].name == "sensor.bare"
    assert house.bedroom_temp not in infos


async def test_own_platform_never_suggested(hass: HomeAssistant, house: House) -> None:
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        "mine",
        suggested_object_id="mine",
        original_device_class="temperature",
        device_id=ent_reg.async_get(house.living_temp).device_id,
    )
    hass.states.async_set(entry.entity_id, "20", {"unit_of_measurement": "°C"})
    infos = registry.entity_infos(hass)
    own = next(i for i in infos if i.entity_id == entry.entity_id)
    assert classify(own, [], TEMP, Scope.ROOM) is None
    suggestion = suggest_sources(house.living_room, infos, TEMP, Scope.ROOM)
    assert entry.entity_id not in suggestion.sources
    assert entry.entity_id not in dict(suggestion.excluded)


# Pre-fill scenarios


async def test_kitchen_suggestion(hass: HomeAssistant, house: House) -> None:
    infos = registry.entity_infos(hass)
    suggestion = suggest_sources(house.kitchen, infos, TEMP, Scope.ROOM)
    assert suggestion.sources == (house.kitchen_temp, house.kitchen_thermostat)
    assert dict(suggestion.excluded) == {
        house.fridge_temp: Exclusion.IMPLAUSIBLE,
        house.printer_temp: Exclusion.SECONDARY,
        house.kitchen_contact_temp: Exclusion.CONTACT,
    }


async def test_storage_and_template_exclusions(
    hass: HomeAssistant, house: House
) -> None:
    infos = registry.entity_infos(hass)
    storage = suggest_sources(house.storage, infos, TEMP, Scope.ROOM)
    assert storage.sources == ()
    assert dict(storage.excluded) == {house.plug_temp: Exclusion.DIAGNOSTIC}
    template = next(i for i in infos if i.entity_id == house.template_temp)
    assert classify(template, [], TEMP, Scope.ROOM) is Exclusion.HELPER


# Follow


async def test_follow(hass: HomeAssistant, house: House) -> None:
    infos = registry.entity_infos(hass)
    living = registry.followed_sources(
        {m.CONF_TEMPERATURE: [house.living_temp, house.living_thermostat]}, infos
    )
    assert living[HUM] == [house.living_hum, house.living_thermostat]
    assert living[PRESS] == [house.living_pressure]
    bedroom = registry.followed_sources(
        {m.CONF_TEMPERATURE: [house.bedroom_temp]}, infos
    )
    assert bedroom == {HUM: [], PRESS: []}
    explicit = registry.followed_sources(
        {m.CONF_TEMPERATURE: [house.living_temp], m.CONF_HUMIDITY: [house.study_hum]},
        infos,
    )
    assert set(explicit) == {PRESS}


# Room proposal


async def test_propose_rooms(hass: HomeAssistant, house: House) -> None:
    proposal = propose_rooms(
        registry.area_infos(hass), registry.entity_infos(hass), OUTSIDE_WORDS
    )
    checked = dict(proposal)
    assert house.storage not in checked
    assert checked[house.garden] is False
    assert checked[house.yard] is False
    assert checked[house.street] is False
    indoor = [a for a, on in proposal if on]
    assert indoor == [
        house.kitchen,
        house.living_room,
        house.study,
        house.bathroom,
        house.bedroom,
    ]


async def test_area_infos(hass: HomeAssistant, house: House) -> None:
    areas = {a.area_id: a for a in registry.area_infos(hass)}
    kitchen = areas[house.kitchen]
    assert (kitchen.floor_name, kitchen.floor_level) == ("Erdgeschoss", 0)
    assert areas[house.garden].floor_level is None
    assert areas[house.street].floor_name is None


# build_model


def _sub(kind: str, sub_id: str, data: dict[str, Any]) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=data,
        subentry_type=kind,
        title=sub_id,
        unique_id=None,
        subentry_id=sub_id,
    )


def _subentries(house: House) -> list[ConfigSubentryData]:
    return [
        _sub(
            SUBENTRY_ROOM,
            "r_living",
            {
                m.CONF_AREA: house.living_room,
                m.CONF_SIDE: "s",
                m.CONF_TEMPERATURE: [house.living_temp, house.living_thermostat],
                m.CONF_CLIMATE_DEVICES: [house.living_thermostat],
            },
        ),
        _sub(
            SUBENTRY_ROOM,
            "r_bedroom",
            {m.CONF_AREA: house.bedroom, m.CONF_TEMPERATURE: [house.bedroom_temp]},
        ),
        _sub(
            SUBENTRY_REGION,
            "g_garden",
            {
                m.CONF_AREA: house.garden,
                m.CONF_DIRECTION: "n",
                m.CONF_TEMPERATURE: [house.garden_temp],
            },
        ),
        _sub(
            SUBENTRY_WINDOW,
            "w_living",
            {
                m.CONF_AREA: house.living_room,
                m.CONF_TYPE: m.WINDOW_SINGLE,
                m.CONF_NAME: "Fenster",
                m.CONF_LEAF: house.living_leaf_1,
            },
        ),
        _sub(
            SUBENTRY_WINDOW,
            "w_conservatory",
            {
                m.CONF_AREA: house.conservatory,
                m.CONF_TYPE: m.WINDOW_SINGLE,
                m.CONF_NAME: "Fenster",
                m.CONF_LEAF: house.conservatory_window,
                m.CONF_FACING: "e",
            },
        ),
    ]


def _entry(house: House, subentries: list[ConfigSubentryData]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={m.CONF_WEATHER: house.weather, m.CONF_MAX_AGE: 45},
        subentries_data=subentries,
    )


async def test_build_model(hass: HomeAssistant, house: House) -> None:
    model = registry.build_model(hass, _entry(house, _subentries(house)))
    assert model.weather == house.weather
    assert model.settings.max_age.total_seconds() == 45 * 60
    living = model.rooms["r_living"]
    assert living.area_id == house.living_room
    assert living.side is Direction.S
    assert living.window_ids == ("w_living",)
    assert living.sources[TEMP] == (house.living_temp, house.living_thermostat)
    assert living.sources[HUM] == (house.living_hum, house.living_thermostat)
    assert living.sources[PRESS] == (house.living_pressure,)
    assert model.rooms["r_bedroom"].sources[HUM] == ()
    assert model.regions["g_garden"].direction is Direction.N
    assert model.windows["w_living"].room_id == "r_living"
    assert model.windows["w_living"].direction is Direction.S
    assert model.windows["w_conservatory"].room_id is None
    assert model.windows["w_conservatory"].direction is Direction.E


async def test_model_ignores_subentry_order(hass: HomeAssistant, house: House) -> None:
    subs = _subentries(house)
    first = registry.build_model(hass, _entry(house, subs))
    second = registry.build_model(hass, _entry(house, list(reversed(subs))))
    assert first == second


async def test_model_follows_registry_changes(
    hass: HomeAssistant, house: House
) -> None:
    entry = _entry(house, _subentries(house))
    before = registry.build_model(hass, entry)

    ent_reg = er.async_get(hass)
    ent_reg.async_update_entity(house.study_hum, name="Anders benannt")
    assert registry.build_model(hass, entry) == before

    device_id = ent_reg.async_get(house.bedroom_temp).device_id
    new = ent_reg.async_get_or_create(
        "sensor",
        "test",
        "bedroom_hum",
        suggested_object_id="bedroom_hum",
        device_id=device_id,
        original_device_class="humidity",
    )
    hass.states.async_set(
        new.entity_id, "55", {"device_class": "humidity", "unit_of_measurement": "%"}
    )
    after = registry.build_model(hass, entry)
    assert after != before
    assert after.rooms["r_bedroom"].sources[HUM] == (new.entity_id,)
