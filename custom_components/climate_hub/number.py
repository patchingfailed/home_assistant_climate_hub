"""Comfort numbers of the hub device (integration §8.3, I8, I13)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ClimateHubConfigEntry
from .entity import PARALLEL_UPDATES as PARALLEL_UPDATES
from .entity import ClimateHubDescription, ClimateHubEntity, Scope, always, planned
from .logic.engine import Comfort


@dataclass(frozen=True, kw_only=True)
class ClimateHubNumberDescription(NumberEntityDescription, ClimateHubDescription):
    """A comfort number: which comfort field it reads and writes."""

    value_fn: Callable[[Comfort], float]
    field: str  # keyword of `ClimateHubCoordinator.async_set_comfort`


def _number(
    key: str,
    device_class: NumberDeviceClass,
    minimum: float,
    maximum: float,
    value_fn: Callable[[Comfort], float],
    field: str,
) -> ClimateHubNumberDescription:
    return ClimateHubNumberDescription(
        key=key,
        scope=Scope.HUB,
        exists_fn=always,
        device_class=device_class,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=minimum,
        native_max_value=maximum,
        native_step=0.5,
        value_fn=value_fn,
        field=field,
    )


NUMBERS: tuple[ClimateHubNumberDescription, ...] = (
    _number(
        "comfort_min",
        NumberDeviceClass.TEMPERATURE,
        10,
        30,
        lambda comfort: comfort.c_min,
        "c_min",
    ),
    _number(
        "comfort_max",
        NumberDeviceClass.TEMPERATURE,
        15,
        35,
        lambda comfort: comfort.c_max,
        "c_max",
    ),
    _number(
        "threshold",
        NumberDeviceClass.TEMPERATURE_DELTA,
        0.5,
        10,
        lambda comfort: comfort.threshold,
        "threshold",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the three comfort numbers to the hub device."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        ClimateHubNumber(coordinator, description, subject)
        for description, subject in planned(coordinator.model, NUMBERS)
    )


class ClimateHubNumber(ClimateHubEntity, NumberEntity):
    """A comfort value, stored in the Store and applied by the next evaluation."""

    entity_description: ClimateHubNumberDescription

    @property
    def subject_result(self) -> Comfort | None:
        """The comfort values, available once the first evaluation ran (I14)."""
        return None if self.coordinator.data is None else self.coordinator.comfort

    @property
    def native_value(self) -> float:
        return self.entity_description.value_fn(self.coordinator.comfort)

    async def async_set_native_value(self, value: float) -> None:
        """Validate and store (raises `ServiceValidationError`, I8)."""
        await self.coordinator.async_set_comfort(
            **{self.entity_description.field: value}
        )
