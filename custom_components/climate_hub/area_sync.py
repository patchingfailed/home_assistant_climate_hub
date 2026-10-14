"""Write the fused sensors into the Home Assistant areas (R11, I5, integration §11)."""

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, LOGGER
from .coordinator import ClimateHubConfigEntry, ClimateHubCoordinator
from .logic.model import CONF_AREA_SYNC

FIELDS = ("temperature", "humidity")
SENSOR_DOMAIN = "sensor"


def _field_name(field: str) -> str:
    return f"{field}_entity_id"


def _wanted(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    coordinator: ClimateHubCoordinator,
) -> dict[str, dict[str, str]]:
    """The area fields Climate Hub should hold, from the entity registry."""
    if not entry.options.get(CONF_AREA_SYNC, True):
        return {}
    registry = er.async_get(hass)
    model = coordinator.model
    wanted: dict[str, dict[str, str]] = {}
    for subject in (*model.rooms.values(), *model.regions.values()):
        for field in FIELDS:
            entity_id = registry.async_get_entity_id(
                SENSOR_DOMAIN, DOMAIN, f"{subject.id}_{field}"
            )
            if entity_id is not None:
                wanted.setdefault(subject.area_id, {})[field] = entity_id
    return wanted


def _set(areas: ar.AreaRegistry, area_id: str, field: str, value: str | None) -> bool:
    try:
        areas.async_update(area_id, **{_field_name(field): value})
    except ValueError as err:
        LOGGER.debug("Area %s: %s not set: %s", area_id, field, err)
        return False
    return True


def _clear(
    areas: ar.AreaRegistry,
    records: dict[str, dict[str, str]],
    keep: dict[str, dict[str, str]],
) -> None:
    """Clear recorded fields that are not in `keep`, only while they still hold ours."""
    for area_id in list(records):
        fields = records[area_id]
        for field, entity_id in list(fields.items()):
            if keep.get(area_id, {}).get(field) == entity_id:
                continue
            area = areas.async_get_area(area_id)
            if (
                area is not None
                and getattr(area, _field_name(field)) == entity_id
                and not _set(areas, area_id, field, None)
            ):
                continue
            del fields[field]
        if not fields:
            del records[area_id]


@callback
def async_sync_areas(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    coordinator: ClimateHubCoordinator,
) -> None:
    """Bring the areas in line with the wanted state and record what was written."""
    areas = ar.async_get(hass)
    records = coordinator.area_sync
    wanted = _wanted(hass, entry, coordinator)
    _clear(areas, records, wanted)
    for area_id, fields in wanted.items():
        area = areas.async_get_area(area_id)
        if area is None:
            continue
        for field, entity_id in fields.items():
            current = getattr(area, _field_name(field))
            recorded = records.get(area_id, {}).get(field)
            if current == entity_id:
                records.setdefault(area_id, {})[field] = entity_id
            elif recorded is not None and current != recorded:
                continue  # the user changed it after we wrote it
            elif _set(areas, area_id, field, entity_id):
                records.setdefault(area_id, {})[field] = entity_id
    coordinator.store.schedule_save(coordinator.store_data)


@callback
def async_sync_after_first_evaluation(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    coordinator: ClimateHubCoordinator,
) -> None:
    """Run the sync once, when the coordinator first has data."""
    remove: Any = None

    @callback
    def _listener() -> None:
        nonlocal remove
        if not coordinator.last_update_success or coordinator.data is None:
            return
        if remove is not None:
            remove()
            remove = None
        async_sync_areas(hass, entry, coordinator)

    remove = coordinator.async_add_listener(_listener)
    entry.async_on_unload(lambda: remove() if remove is not None else None)


async def async_clear_recorded(
    hass: HomeAssistant, records: dict[str, dict[str, str]]
) -> None:
    """Clear every recorded field that still holds our entity (entry removal)."""
    _clear(ar.async_get(hass), records, {})
