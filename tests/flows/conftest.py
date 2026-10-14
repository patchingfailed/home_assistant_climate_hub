"""Fixtures for the flow tests."""

from typing import Any

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_hub.const import (
    DOMAIN,
    SUBENTRY_REGION,
    SUBENTRY_ROOM,
)

from ..house import House


@pytest.fixture
async def hub(hass: HomeAssistant, house: House) -> MockConfigEntry:
    """A loaded hub with the living room and the outdoor sides north and south."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Climate Hub",
        options={"weather": house.weather},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_ROOM,
                subentry_id="room_living",
                unique_id=f"room_{house.living_room}",
                title="Wohnzimmer",
                data={
                    "area": house.living_room,
                    "side": "n",
                    "temperature": [
                        house.living_temp,
                        house.living_air_temp,
                        house.living_thermostat,
                    ],
                    "humidity": [],
                    "pressure": [],
                    "climate_devices": [house.living_thermostat],
                },
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_REGION,
                subentry_id="region_north",
                unique_id="region_n",
                title="Norden · Straße",
                data={
                    "area": house.street,
                    "direction": "n",
                    "temperature": [house.street_temp],
                    "humidity": [house.street_hum],
                    "pressure": [],
                },
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_REGION,
                subentry_id="region_south",
                unique_id="region_s",
                title="Süden · Garten",
                data={
                    "area": house.garden,
                    "direction": "s",
                    "temperature": [house.garden_temp],
                    "humidity": [],
                    "pressure": [],
                },
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _schema_items(schema: Any) -> dict[str, Any]:
    """Field name to (marker, validator), sections flattened as `section.field`."""
    items: dict[str, Any] = {}
    for marker, validator in schema.schema.items():
        name = str(marker)
        if hasattr(validator, "schema") and isinstance(validator.schema, type(schema)):
            for key, value in _schema_items(validator.schema).items():
                items[f"{name}.{key}"] = value
            items[name] = (marker, validator)
        else:
            items[name] = (marker, validator)
    return items


def field(result: dict[str, Any], name: str) -> tuple[Any, Any]:
    """(marker, validator) of a form field; sections as `section.field`."""
    return _schema_items(result["data_schema"])[name]


def suggested(result: dict[str, Any], name: str) -> Any:
    marker, _ = field(result, name)
    return (marker.description or {}).get("suggested_value")


def options(result: dict[str, Any], name: str) -> list[str]:
    return list(field(result, name)[1].config["options"])
