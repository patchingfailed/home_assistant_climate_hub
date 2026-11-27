"""Write the fused sensors into the Home Assistant areas (R11, I5, integration §11)."""

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, LOGGER
from .coordinator import ClimateHubConfigEntry, ClimateHubCoordinator
from .logic.area_sync import FIELDS, Action, Decision, FieldRecord, decide, release
from .logic.model import CONF_AREA_SYNC

SENSOR_DOMAIN = "sensor"


def _field_name(field: str) -> str:
    return f"{field}_entity_id"


def area_fields(hass: HomeAssistant, area_id: str) -> dict[str, str | None]:
    """The sensors in the area's temperature and humidity fields; {} without it."""
    area = ar.async_get(hass).async_get_area(area_id)
    if area is None:
        return {}
    return {field: getattr(area, _field_name(field)) for field in FIELDS}


def own_entities(hass: HomeAssistant, subject_id: str) -> dict[str, str]:
    """The object's own sensors for the area fields, by unique ID."""
    registry = er.async_get(hass)
    found: dict[str, str] = {}
    for field in FIELDS:
        entity_id = registry.async_get_entity_id(
            SENSOR_DOMAIN, DOMAIN, f"{subject_id}_{field}"
        )
        if entity_id is not None:
            found[field] = entity_id
    return found


def _wanted(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    coordinator: ClimateHubCoordinator,
) -> dict[str, dict[str, tuple[str, bool]]]:
    """Per area and field the wanted entity and its subject's consent to replace.

    Rooms come first, so a region sharing an area with a room wins (§11 point 1).
    """
    if not entry.options.get(CONF_AREA_SYNC, True):
        return {}
    model = coordinator.model
    wanted: dict[str, dict[str, tuple[str, bool]]] = {}
    for subject in (*model.rooms.values(), *model.regions.values()):
        for field, entity_id in own_entities(hass, subject.id).items():
            wanted.setdefault(subject.area_id, {})[field] = (
                entity_id,
                subject.replace_area_sensor,
            )
    return wanted


def _set(areas: ar.AreaRegistry, area_id: str, field: str, value: str | None) -> bool:
    try:
        areas.async_update(area_id, **{_field_name(field): value})
    except ValueError as err:
        LOGGER.debug("Area %s: %s not set: %s", area_id, field, err)
        return False
    return True


def _restore(
    areas: ar.AreaRegistry, area_id: str, field: str, value: str | None
) -> None:
    """Put the previous sensor back; empty the field when that is rejected."""
    if not _set(areas, area_id, field, value) and value is not None:
        _set(areas, area_id, field, None)


def _release(
    areas: ar.AreaRegistry,
    records: dict[str, dict[str, FieldRecord]],
    wanted: dict[str, dict[str, tuple[str, bool]]],
) -> None:
    """Release recorded fields that are not wanted any more; drop their records."""
    for area_id in list(records):
        fields = records[area_id]
        area = areas.async_get_area(area_id)
        for field, record in list(fields.items()):
            if field in wanted.get(area_id, {}):
                continue
            if area is not None:
                decision = release(getattr(area, _field_name(field)), record)
                if decision.action is Action.RESTORE:
                    _restore(areas, area_id, field, decision.value)
            del fields[field]
        if not fields:
            del records[area_id]


def _apply(
    areas: ar.AreaRegistry,
    records: dict[str, dict[str, FieldRecord]],
    area_id: str,
    field: str,
    decision: Decision,
) -> None:
    fields = records.setdefault(area_id, {})
    match decision.action:
        case Action.WRITE:
            if _set(areas, area_id, field, decision.value):
                assert decision.record is not None
                fields[field] = decision.record
        case Action.RESTORE:
            _restore(areas, area_id, field, decision.value)
            fields.pop(field, None)
        case _:  # KEEP, LEAVE
            if decision.record is not None:
                fields[field] = decision.record
            else:
                fields.pop(field, None)
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
    _release(areas, records, wanted)
    for area_id, fields in wanted.items():
        area = areas.async_get_area(area_id)
        if area is None:
            continue
        for field, (entity_id, replace) in fields.items():
            decision = decide(
                getattr(area, _field_name(field)),
                entity_id,
                records.get(area_id, {}).get(field),
                replace,
            )
            _apply(areas, records, area_id, field, decision)
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
    hass: HomeAssistant, records: dict[str, dict[str, FieldRecord]]
) -> None:
    """Release every recorded field (entry removal)."""
    _release(ar.async_get(hass), records, {})
