"""Binary sensors of the room and hub devices (integration §8.3)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import ClimateHubConfigEntry
from .entity import (
    COVER_KEY,
    ClimateHubDescription,
    ClimateHubEntity,
    Scope,
    Subject,
    always,
    conditioned_windows,
    has_windows,
    planned,
)
from .entity import PARALLEL_UPDATES as PARALLEL_UPDATES
from .logic.engine import HouseResult
from .logic.model import HouseModel


@dataclass(frozen=True, kw_only=True)
class ClimateHubBinarySensorDescription(
    BinarySensorEntityDescription, ClimateHubDescription
):
    """A binary sensor: how to read its value and attributes from the result."""

    value_fn: Callable[[Any], bool | None]
    attrs_fn: Callable[[Any, HomeAssistant], Mapping[str, Any]] | None = None


# Existence predicates (I7)


def _any_windows(model: HouseModel, _subject: Subject) -> bool:
    return bool(model.windows)


def _any_conditioned_windows(model: HouseModel, _subject: Subject) -> bool:
    return any(conditioned_windows(model, room) for room in model.rooms.values())


def _cover_windows(house: HouseResult, hass: HomeAssistant) -> dict[str, Any]:
    """The `cover` sensors of the windows to close, with the reason (SH1)."""
    registry = er.async_get(hass)
    windows = []
    for window_id, reason in house.covers_to_close:
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{window_id}_{COVER_KEY}"
        )
        if entity_id is not None:
            windows.append({"entity_id": entity_id, "reason": reason.value})
    return {"windows": windows} if windows else {}


def _flag(
    key: str,
    scope: Scope,
    value_fn: Callable[[Any], bool | None],
    exists_fn: Callable[[HouseModel, Subject], bool] = always,
    attrs_fn: Callable[[Any, HomeAssistant], Mapping[str, Any]] | None = None,
) -> ClimateHubBinarySensorDescription:
    return ClimateHubBinarySensorDescription(
        key=key,
        scope=scope,
        value_fn=value_fn,
        attrs_fn=attrs_fn,
        exists_fn=exists_fn,
    )


BINARY_SENSORS: tuple[ClimateHubBinarySensorDescription, ...] = (
    # Room
    _flag("cooling_down", Scope.ROOM, lambda r: r.cooling_down, has_windows),
    _flag("heating_up", Scope.ROOM, lambda r: r.heating_up, has_windows),
    _flag(
        "open_while_conditioning",
        Scope.ROOM,
        lambda r: r.open_while_conditioning,
        conditioned_windows,
    ),
    # Hub
    _flag("any_cooling_down", Scope.HUB, lambda h: h.any_cooling_down, _any_windows),
    _flag("any_heating_up", Scope.HUB, lambda h: h.any_heating_up, _any_windows),
    _flag(
        "any_open_while_conditioning",
        Scope.HUB,
        lambda h: h.any_open_while_conditioning,
        _any_conditioned_windows,
    ),
    _flag(
        "any_cover_to_close",
        Scope.HUB,
        lambda h: h.any_cover_to_close,
        _any_windows,
        _cover_windows,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors of every room with windows and the hub, per subentry."""
    coordinator = entry.runtime_data.coordinator
    by_subentry: dict[str | None, list[ClimateHubBinarySensor]] = {}
    for description, subject in planned(coordinator.model, BINARY_SENSORS):
        subentry_id = None if subject is None else subject.id
        by_subentry.setdefault(subentry_id, []).append(
            ClimateHubBinarySensor(coordinator, description, subject)
        )
    for subentry_id, entities in by_subentry.items():
        async_add_entities(entities, config_subentry_id=subentry_id)


class ClimateHubBinarySensor(ClimateHubEntity, BinarySensorEntity):
    """A Climate Hub binary sensor."""

    entity_description: ClimateHubBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        result = self.subject_result
        return None if result is None else self.entity_description.value_fn(result)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        result = self.subject_result
        attrs_fn = self.entity_description.attrs_fn
        if result is None or attrs_fn is None:
            return None
        return attrs_fn(result, self.hass)
