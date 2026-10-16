"""Home Assistant registries to the pure pre-fill inputs and the `HouseModel`.

No caching and no listeners: the coordinator owns both (integration.md 6.4).
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr

from .const import SUBENTRY_REGION, SUBENTRY_ROOM, SUBENTRY_WINDOW
from .logic import model as m
from .logic.prefill import AreaInfo, EntityInfo, follow_devices
from .logic.sources import Metric
from .snapshot import metric_value

_DEVICE_CLASS_METRICS = {
    "temperature": Metric.TEMPERATURE,
    "humidity": Metric.HUMIDITY,
    "atmospheric_pressure": Metric.PRESSURE,
    "pressure": Metric.PRESSURE,
}


def _value(
    hass: HomeAssistant, entity_id: str, domain: str, device_class: str | None
) -> float | None:
    if domain == "climate":
        return metric_value(hass, entity_id, Metric.TEMPERATURE)
    if domain == "sensor" and (metric := _DEVICE_CLASS_METRICS.get(device_class or "")):
        return metric_value(hass, entity_id, metric)
    return None


def _info(
    hass: HomeAssistant, entity_id: str, entry: er.RegistryEntry | None
) -> EntityInfo:
    state: State | None = hass.states.get(entity_id)
    attributes: Mapping[str, Any] = {} if state is None else state.attributes
    domain = entity_id.partition(".")[0]
    device_class = attributes.get("device_class") or (
        entry and (entry.device_class or entry.original_device_class)
    )
    name = (
        (entry and (entry.name or entry.original_name))
        or attributes.get("friendly_name")
        or entity_id
    )
    return EntityInfo(
        entity_id=entity_id,
        name=str(name),
        domain=domain,
        device_class=device_class or None,
        platform="" if entry is None else entry.platform,
        category=None
        if entry is None or entry.entity_category is None
        else entry.entity_category.value,
        device_id=None if entry is None else entry.device_id,
        area_id=None if entry is None else er.async_get_effective_area_id(hass, entry),
        value=_value(hass, entity_id, domain, device_class),
        has_current_humidity=domain == "climate"
        and attributes.get("current_humidity") is not None,
    )


def entity_infos(hass: HomeAssistant) -> list[EntityInfo]:
    """Enabled registry entities plus state-only entities."""
    registry = er.async_get(hass)
    infos = [
        _info(hass, entry.entity_id, entry)
        for entry in registry.entities.values()
        if entry.disabled_by is None
    ]
    infos.extend(
        _info(hass, state.entity_id, None)
        for state in hass.states.async_all()
        if state.entity_id not in registry.entities
    )
    return infos


def area_infos(hass: HomeAssistant) -> list[AreaInfo]:
    floors = fr.async_get(hass)
    result: list[AreaInfo] = []
    for area in ar.async_get(hass).async_list_areas():
        floor = floors.async_get_floor(area.floor_id) if area.floor_id else None
        result.append(
            AreaInfo(
                area_id=area.id,
                name=area.name,
                floor_name=None if floor is None else floor.name,
                floor_level=None if floor is None else floor.level,
            )
        )
    return result


def followed_sources(
    data: Mapping[str, Any], infos: Sequence[EntityInfo]
) -> dict[Metric, list[str]]:
    """Followed humidity and pressure lists, only for metrics with an empty own list."""
    temperature = data[m.CONF_TEMPERATURE]
    return {
        metric: follow_devices(temperature, infos, metric)
        for metric, key in (
            (Metric.HUMIDITY, m.CONF_HUMIDITY),
            (Metric.PRESSURE, m.CONF_PRESSURE),
        )
        if not data.get(key)
    }


def build_model_from(
    hass: HomeAssistant,
    options: Mapping[str, Any],
    subentries: Iterable[tuple[str, str, Mapping[str, Any]]],
) -> m.HouseModel:
    """The resolved house model from options and (subentry ID, type, data) triples."""
    settings = m.parse_settings(options)
    infos = entity_infos(hass)
    rooms: dict[str, m.RoomModel] = {}
    regions: dict[str, m.RegionModel] = {}
    windows: dict[str, m.WindowModel] = {}
    for subentry_id, subentry_type, data in subentries:
        if subentry_type == SUBENTRY_ROOM:
            rooms[subentry_id] = m.parse_room(
                subentry_id, data, settings, followed_sources(data, infos)
            )
        elif subentry_type == SUBENTRY_REGION:
            regions[subentry_id] = m.parse_region(
                subentry_id, data, settings, followed_sources(data, infos)
            )
        elif subentry_type == SUBENTRY_WINDOW:
            windows[subentry_id] = m.parse_window(subentry_id, data)
    return m.build_house(settings, options.get(m.CONF_WEATHER), rooms, regions, windows)


def build_model(hass: HomeAssistant, entry: ConfigEntry) -> m.HouseModel:
    """The resolved house model from the hub entry and the registries."""
    return build_model_from(
        hass,
        entry.options,
        (
            (sub.subentry_id, sub.subentry_type, sub.data)
            for sub in entry.subentries.values()
        ),
    )
