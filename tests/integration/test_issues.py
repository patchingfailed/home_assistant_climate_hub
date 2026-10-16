"""Repair issues: outages (H5), new sources (R14, I4), windows without a room (W11)."""

from collections.abc import Iterable
from datetime import timedelta
from types import MappingProxyType
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_hub.const import (
    DOMAIN,
    REGISTRY_DEBOUNCE,
    RELOAD_DELAY,
    SUBENTRY_ROOM,
    SUBENTRY_WINDOW,
)
from custom_components.climate_hub.coordinator import ClimateHubCoordinator
from custom_components.climate_hub.logic import engine
from custom_components.climate_hub.logic import model as m
from custom_components.climate_hub.store import fingerprint
from tests.house import PLATFORM, House, set_value
from tests.integration.test_coordinator import _advance, _entry

BEDROOM_ISSUE = "new_source_r_bedroom_"


def _all(hass: HomeAssistant, prefix: str = "") -> dict[str, ir.IssueEntry]:
    return {
        issue_id: issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue_id.startswith(prefix)
    }


def _add_subentry(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    kind: str,
    sub_id: str,
    data: dict[str, Any],
    title: str | None = None,
) -> None:
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type=kind,
            title=title or sub_id,
            unique_id=None,
            subentry_id=sub_id,
        ),
    )


async def _start(hass: HomeAssistant, entry: MockConfigEntry) -> ClimateHubCoordinator:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    entry.async_on_unload(coordinator.async_add_listener(lambda: None))
    return coordinator


async def _run(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hours: float,
    keep_alive: Iterable[str] = (),
) -> None:
    """Advance in half-hour steps; the kept sources report again at each step."""
    for _ in range(round(hours * 2)):
        for entity_id in keep_alive:
            state = hass.states.get(entity_id)
            assert state is not None
            set_value(hass, entity_id, state.state)
        await _advance(hass, freezer, timedelta(minutes=30))


def _add_sensor(
    hass: HomeAssistant,
    house: House,
    key: str,
    area_id: str | None,
    value: float = 20.0,
) -> str:
    """A new temperature sensor on its own device, as a new integration would add."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=house.config_entry.entry_id,
        identifiers={(PLATFORM, key)},
        name=key,
    )
    if area_id:
        dr.async_get(hass).async_update_device(device.id, area_id=area_id)
    entry = er.async_get(hass).async_get_or_create(
        "sensor",
        PLATFORM,
        key,
        suggested_object_id=key,
        config_entry=house.config_entry,
        device_id=device.id,
        original_device_class="temperature",
        original_name=key,
    )
    hass.states.async_set(
        entry.entity_id,
        str(value),
        {
            "friendly_name": key,
            "device_class": "temperature",
            "unit_of_measurement": "°C",
            "state_class": "measurement",
        },
    )
    return entry.entity_id


async def _settle(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    await _advance(hass, freezer, REGISTRY_DEBOUNCE + timedelta(seconds=1))


# Outages (H5)


async def test_outage_after_the_delay_with_offset_text(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    keep = [house.living_air_temp]
    await _start(hass, _entry(house))
    # Both sources report for two hours: the offset is learned (> 1 h).
    await _run(hass, freezer, 2, [house.living_temp, *keep])
    set_value(hass, house.living_temp, "unavailable")
    issue_id = f"outage_r_living_{house.living_temp}"
    await _run(hass, freezer, 5, keep)
    assert issue_id not in _all(hass)
    await _run(hass, freezer, 1.5, keep)
    assert issue_id in _all(hass)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "outage"
    assert issue.is_fixable is False
    assert issue.is_persistent is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {
        "title": "r_living",
        "source": "Klimasensor Temperatur",
        "hours": "6",
        "active": "Luftmesser Temperatur",
        "offset": "+0,3 °C",
    }


async def test_outage_issue_survives_a_failed_room_evaluation(
    hass: HomeAssistant,
    house: House,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keep = [house.living_air_temp]
    await _start(hass, _entry(house))
    await _run(hass, freezer, 1, [house.living_temp, *keep])
    set_value(hass, house.living_temp, "unavailable")
    issue_id = f"outage_r_living_{house.living_temp}"
    await _run(hass, freezer, 6.5, keep)
    assert issue_id in _all(hass)

    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "_evaluate_room", _fail)
    await _run(hass, freezer, 0.5, keep)
    assert issue_id in _all(hass)
    monkeypatch.undo()
    await _run(hass, freezer, 0.5, keep)
    assert issue_id in _all(hass)


async def test_outage_recovery_deletes_the_issue(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    keep = [house.living_air_temp]
    set_value(hass, house.living_temp, "unavailable")
    await _start(hass, _entry(house))
    await _run(hass, freezer, 6.5, keep)
    issue_id = f"outage_r_living_{house.living_temp}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    # Never paired: no learned offset, the fallback is used as is.
    assert issue.translation_key == "outage_fallback"
    assert issue.translation_placeholders == {
        "title": "r_living",
        "source": "Klimasensor Temperatur",
        "hours": "6",
        "active": "Luftmesser Temperatur",
        "offset": "",
    }
    set_value(hass, house.living_temp, "21.4")
    await _run(hass, freezer, 0.5, keep)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_outage_without_replacement(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    set_value(hass, house.bedroom_temp, "unavailable")
    await _start(hass, _entry(house))
    await _run(hass, freezer, 5.5)
    assert f"outage_r_bedroom_{house.bedroom_temp}" not in _all(hass)
    await _run(hass, freezer, 1)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"outage_r_bedroom_{house.bedroom_temp}"
    )
    assert issue is not None
    assert issue.translation_key == "outage_none"
    assert issue.translation_placeholders == {
        "title": "r_bedroom",
        "source": "Luftmesser Temperatur",
        "hours": "6",
        "active": "",
        "offset": "",
    }


async def test_outage_of_a_region_source(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    set_value(hass, house.garden_temp, "unavailable")
    await _start(hass, _entry(house))
    await _run(hass, freezer, 6.5)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"outage_g_garden_{house.garden_temp}"
    )
    assert issue is not None
    assert issue.translation_key == "outage_none"
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["title"] == "g_garden"


# New sources (R14, I4)


async def test_sources_present_at_setup_raise_nothing(
    hass: HomeAssistant, house: House
) -> None:
    _add_sensor(hass, house, "extra_bedroom", house.bedroom)
    coordinator = await _start(hass, _entry(house))
    assert _all(hass, "new_source_") == {}
    # Living room: the thermostat is pre-fillable but not listed; it is just seen.
    assert house.living_thermostat in coordinator.seen["r_living"].entities
    assert set(coordinator.seen) == {"r_living", "r_bedroom", "g_garden"}


async def test_new_entity_in_the_area_raises_one_issue(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    await _start(hass, _entry(house))
    new = _add_sensor(hass, house, "extra_bedroom", house.bedroom)
    await _settle(hass, freezer)
    issues = _all(hass, "new_source_")
    assert set(issues) == {f"{BEDROOM_ISSUE}{new}"}
    issue = issues[f"{BEDROOM_ISSUE}{new}"]
    assert issue.translation_key == "new_source"
    assert issue.is_fixable is True
    assert issue.is_persistent is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {
        "area": "Schlafzimmer",
        "source": "extra_bedroom",
        "title": "r_bedroom",
    }
    assert issue.data == {
        "entry_id": hass.config_entries.async_entries(DOMAIN)[0].entry_id,
        "subentry_id": "r_bedroom",
        "entity_id": new,
    }


async def test_entity_classified_only_after_setup_is_not_new(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    """At start-up a state may come after setup; only its state names the class."""
    late = _add_sensor(hass, house, "late_bedroom", house.bedroom)
    hass.states.async_remove(late)
    er.async_get(hass).async_update_entity(late, original_device_class=None)
    coordinator = await _start(hass, _entry(house))
    assert late in coordinator.seen["r_bedroom"].entities
    hass.states.async_set(
        late,
        "20.5",
        {"device_class": "temperature", "unit_of_measurement": "°C"},
    )
    # Any registry change runs the sync; the entity now classifies as a source.
    er.async_get(hass).async_update_entity(late, name="Spät")
    await _settle(hass, freezer)
    assert _all(hass, "new_source_") == {}


async def test_entity_moved_into_the_area_raises_one_issue(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    new = _add_sensor(hass, house, "extra_loose", None)
    await _start(hass, _entry(house))
    assert _all(hass, "new_source_") == {}
    er.async_get(hass).async_update_entity(
        new, area_id=house.bedroom, name="Eigener Name"
    )
    await _settle(hass, freezer)
    assert set(_all(hass, "new_source_")) == {f"{BEDROOM_ISSUE}{new}"}


async def test_entity_moved_out_deletes_the_issue(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    await _start(hass, _entry(house))
    new = _add_sensor(hass, house, "extra_bedroom", house.bedroom)
    await _settle(hass, freezer)
    assert set(_all(hass, "new_source_")) == {f"{BEDROOM_ISSUE}{new}"}
    er.async_get(hass).async_update_entity(
        new, area_id=house.storage, name="Eigener Name"
    )
    await _settle(hass, freezer)
    assert _all(hass, "new_source_") == {}


async def test_entity_left_out_on_purpose_raises_nothing(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    """In `seen` but not listed: later registry changes do not bring it back."""
    _add_sensor(hass, house, "extra_bedroom", house.bedroom)
    await _start(hass, _entry(house))
    er.async_get(hass).async_update_entity(house.living_temp, name="Umbenannt")
    await _settle(hass, freezer)
    _add_sensor(hass, house, "other_storage", house.storage)
    await _settle(hass, freezer)
    assert _all(hass, "new_source_") == {}


async def test_ignored_issue_survives_the_next_sync(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    await _start(hass, _entry(house))
    new = _add_sensor(hass, house, "extra_bedroom", house.bedroom)
    await _settle(hass, freezer)
    issue_id = f"{BEDROOM_ISSUE}{new}"
    ir.async_ignore_issue(hass, DOMAIN, issue_id, True)
    assert _all(hass)[issue_id].dismissed_version is not None
    er.async_get(hass).async_update_entity(house.living_temp, name="Umbenannt")
    await _settle(hass, freezer)
    assert _all(hass, "new_source_")[issue_id].dismissed_version is not None


async def test_changed_subentry_data_refreshes_seen_and_clears_the_issue(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    entry = _entry(house)
    coordinator = await _start(hass, entry)
    new = _add_sensor(hass, house, "extra_bedroom", house.bedroom)
    await _settle(hass, freezer)
    assert set(_all(hass, "new_source_")) == {f"{BEDROOM_ISSUE}{new}"}
    subentry = entry.subentries["r_bedroom"]
    data = {**subentry.data, m.CONF_SIDE: "n"}
    hass.config_entries.async_update_subentry(entry, subentry, data=data)
    await _advance(hass, freezer, RELOAD_DELAY + timedelta(seconds=1))
    assert _all(hass, "new_source_") == {}
    seen = entry.runtime_data.coordinator.seen["r_bedroom"]
    assert entry.runtime_data.coordinator is not coordinator
    assert seen.fingerprint == fingerprint(entry.subentries["r_bedroom"].data)
    assert new in seen.entities


# Windows without a room (W11)


def _window_data(house: House, area_id: str, name: str, leaf: str) -> dict[str, Any]:
    return {
        m.CONF_AREA: area_id,
        m.CONF_TYPE: m.WINDOW_SINGLE,
        m.CONF_NAME: name,
        m.CONF_LEAF: leaf,
    }


async def test_windows_without_room_and_adding_the_room(
    hass: HomeAssistant, house: House, freezer: FrozenDateTimeFactory
) -> None:
    entry = _entry(house)
    entry.add_to_hass(hass)
    _add_subentry(
        hass,
        entry,
        SUBENTRY_WINDOW,
        "w_b",
        _window_data(house, house.conservatory, "B", house.conservatory_window),
        "Zweites Fenster",
    )
    _add_subentry(
        hass,
        entry,
        SUBENTRY_WINDOW,
        "w_a",
        _window_data(house, house.conservatory, "A", house.kitchen_contact),
        "Erstes Fenster",
    )
    await _start(hass, entry)
    issue_id = f"windows_without_room_{house.conservatory}"
    assert set(_all(hass, "windows_without_room_")) == {issue_id}
    issue = _all(hass)[issue_id]
    assert issue.translation_key == "windows_without_room"
    assert issue.is_fixable is True
    assert issue.is_persistent is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {
        "area": "Wintergarten",
        "windows": "Erstes Fenster und Zweites Fenster",
    }
    assert issue.data == {"entry_id": entry.entry_id, "area_id": house.conservatory}

    _add_subentry(
        hass,
        entry,
        SUBENTRY_ROOM,
        "r_conservatory",
        {m.CONF_AREA: house.conservatory, m.CONF_TEMPERATURE: [house.kitchen_temp]},
    )
    await _advance(hass, freezer, RELOAD_DELAY + timedelta(seconds=1))
    assert _all(hass, "windows_without_room_") == {}


# Cleanup


async def test_stale_subentry_issues_are_deleted_at_setup(
    hass: HomeAssistant, house: House
) -> None:
    for issue_id in (
        "outage_gone_sensor.x",
        "new_source_gone_sensor.x",
        "windows_without_room_gone",
    ):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="outage",
        )
    await _start(hass, _entry(house))
    assert "outage_gone_sensor.x" not in _all(hass)
    assert "new_source_gone_sensor.x" not in _all(hass)
    assert "windows_without_room_gone" not in _all(hass)


async def test_remove_entry_deletes_every_issue(
    hass: HomeAssistant, house: House
) -> None:
    entry = _entry(house)
    entry.add_to_hass(hass)
    _add_subentry(
        hass,
        entry,
        SUBENTRY_WINDOW,
        "w_c",
        _window_data(house, house.conservatory, "C", house.conservatory_window),
    )
    await _start(hass, entry)
    ir.async_create_issue(
        hass,
        DOMAIN,
        "outage_r_living_sensor.x",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="outage_none",
    )
    assert len(_all(hass)) == 2
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _all(hass) == {}
