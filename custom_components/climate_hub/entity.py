"""Shared entity code: descriptions, base entity, device sync, stale cleanup (§8)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ClimateHubConfigEntry, ClimateHubCoordinator
from .logic.model import HouseModel, RegionModel, RoomModel

PARALLEL_UPDATES = 0

DEVICE_HUB = "hub"
DEVICE_CLIMATE = "climate"
DEVICE_CLIMATE_AREA = "climate_area"

type Subject = RoomModel | RegionModel | None
type ExistsFn = Callable[[HouseModel, Subject], bool]


class Scope(StrEnum):
    """Which device an entity belongs to."""

    ROOM = "room"
    REGION = "region"
    HUB = "hub"


@dataclass(frozen=True, kw_only=True)
class ClimateHubDescription(EntityDescription):
    """Fields every Climate Hub description adds (`key` is the translation key)."""

    scope: Scope
    exists_fn: ExistsFn


def always(_model: HouseModel, _subject: Subject) -> bool:
    """Existence predicate for entities without a condition."""
    return True


def planned[D: ClimateHubDescription](
    model: HouseModel, descriptions: Iterable[D]
) -> Iterator[tuple[D, Subject]]:
    """The (description, subject) pairs the model produces; the platforms and the
    cleanup both use this, so they cannot disagree (§8.4)."""
    for description in descriptions:
        subjects: Iterable[Subject]
        if description.scope is Scope.ROOM:
            subjects = model.rooms.values()
        elif description.scope is Scope.REGION:
            subjects = model.regions.values()
        else:
            subjects = (None,)
        for subject in subjects:
            if description.exists_fn(model, subject):
                yield description, subject


def owner_id(entry: ClimateHubConfigEntry, subject: Subject) -> str:
    """Subentry ID of a room or region, the entry ID for hub entities."""
    return entry.entry_id if subject is None else subject.id


def unique_id(entry: ClimateHubConfigEntry, subject: Subject, key: str) -> str:
    """Frozen unique ID (§8.2)."""
    return f"{owner_id(entry, subject)}_{key}"


class ClimateHubEntity(CoordinatorEntity[ClimateHubCoordinator]):
    """Base of all Climate Hub entities."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"offset", "per_region"})

    entity_description: ClimateHubDescription

    def __init__(
        self,
        coordinator: ClimateHubCoordinator,
        description: ClimateHubDescription,
        subject: Subject,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._subject_id = None if subject is None else subject.id
        entry = coordinator.config_entry
        self._attr_translation_key = description.key
        self._attr_unique_id = unique_id(entry, subject, description.key)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, owner_id(entry, subject))}
        )

    @property
    def subject_result(self) -> Any | None:
        """The engine result of this entity's object, None without one."""
        data = self.coordinator.data
        if data is None:
            return None
        scope = self.entity_description.scope
        if scope is Scope.ROOM:
            return data.rooms.get(self._subject_id)
        if scope is Scope.REGION:
            return data.regions.get(self._subject_id)
        return data.house

    @property
    def available(self) -> bool:
        """Available only while the coordinator has a result for the object."""
        return super().available and self.subject_result is not None


def _area_name(hass: HomeAssistant, area_id: str) -> str:
    area = ar.async_get(hass).async_get_area(area_id)
    return area.name if area else area_id


def async_sync_devices(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    coordinator: ClimateHubCoordinator,
) -> None:
    """Create or update the hub, room and region devices (§8.1, I15)."""
    devices = dr.async_get(hass)
    devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        entry_type=DeviceEntryType.SERVICE,
        translation_key=DEVICE_HUB,
    )
    parts = er.async_get(hass).settings.entity_id_parts
    with_area = parts is not None and er.EntityNamePart.AREA not in parts
    for subject in (
        *coordinator.model.rooms.values(),
        *coordinator.model.regions.values(),
    ):
        device = devices.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=subject.id,
            identifiers={(DOMAIN, subject.id)},
            translation_key=DEVICE_CLIMATE_AREA if with_area else DEVICE_CLIMATE,
            translation_placeholders=(
                {"area": _area_name(hass, subject.area_id)} if with_area else None
            ),
        )
        if coordinator.device_areas.get(subject.id) != subject.area_id:
            if device.area_id != subject.area_id:
                devices.async_update_device(device.id, area_id=subject.area_id)
            coordinator.device_areas[subject.id] = subject.area_id


def async_remove_stale_entities(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    descriptions: Iterable[ClimateHubDescription],
) -> None:
    """Remove registry entries the current model no longer produces (I7)."""
    wanted = {
        unique_id(entry, subject, description.key)
        for description, subject in planned(
            entry.runtime_data.coordinator.model, descriptions
        )
    }
    registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registry_entry.unique_id not in wanted:
            registry.async_remove(registry_entry.entity_id)


def rounded(value: float | None, digits: int) -> float | None:
    """Round a native value, None stays None."""
    return None if value is None else round(value, digits)


def present(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Drop attributes without a value."""
    return {key: value for key, value in attributes.items() if value is not None}
