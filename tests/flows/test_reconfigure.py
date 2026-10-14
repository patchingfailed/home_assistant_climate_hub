"""House plan reconfigure, screen S10 with the I17 preview (docs/integration.md 9.6)."""

from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from ..house import House
from .conftest import options, suggested
from .test_options_flow import count_reloads, settle


async def _start(hass: HomeAssistant, hub: MockConfigEntry) -> dict[str, Any]:
    return await hass.config_entries.flow.async_init(
        hub.domain, context={"source": "reconfigure", "entry_id": hub.entry_id}
    )


async def _configure(
    hass: HomeAssistant, result: dict[str, Any], user_input: dict[str, Any]
) -> dict[str, Any]:
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


def _plan(**sides: dict[str, Any]) -> dict[str, Any]:
    return {d: sides.get(d, {}) for d in "nesw"}


def _sub(hub: MockConfigEntry, unique_id: str) -> ConfigSubentry | None:
    return next((s for s in hub.subentries.values() if s.unique_id == unique_id), None)


async def test_form_shows_the_current_plan(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _start(hass, hub)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert suggested(result, "n.outdoor") == house.street
    assert suggested(result, "n.rooms") == [house.living_room]
    assert suggested(result, "s.outdoor") == house.garden
    assert suggested(result, "s.rooms") == []
    assert suggested(result, "e.outdoor") is None
    assert [o["value"] for o in options(result, "e.rooms")] == [house.living_room]
    offered = {o["value"] for o in options(result, "e.outdoor")}
    assert {house.street, house.garden, house.yard} <= offered
    assert house.living_room not in offered  # a room cannot be outdoors


async def test_moving_a_room_updates_its_side_with_one_reload(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _start(hass, hub)
    with count_reloads(hass) as setup:
        result = await _configure(
            hass,
            result,
            _plan(
                n={"outdoor": house.street},
                s={"outdoor": house.garden, "rooms": [house.living_room]},
            ),
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        await settle(hass)
        assert setup.call_count == 1
    assert hub.subentries["room_living"].data["side"] == "s"
    # Nothing else changed
    assert hub.subentries["room_living"].data["temperature"][0] == house.living_temp
    assert hub.subentries["region_north"].data["area"] == house.street
    assert hub.subentries["region_south"].data["area"] == house.garden


async def test_adding_a_side_shows_the_preview_and_creates_the_region(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _start(hass, hub)
    with count_reloads(hass) as setup:
        result = await _configure(
            hass,
            result,
            _plan(
                n={"outdoor": house.street, "rooms": [house.living_room]},
                s={"outdoor": house.garden},
                w={"outdoor": house.yard},
            ),
        )
        assert result["type"] is FlowResultType.MENU
        assert result["step_id"] == "plan_preview"
        assert result["menu_options"] == ["plan_save", "plan_adjust"]
        preview = result["description_placeholders"]["preview"]
        assert "**Westen · Hof** 14,5 °C aus Außensensor Temperatur" in preview
        assert "Fällt Westen aus" in preview
        # Only the new side is shown
        assert "Norden · Straße" not in preview
        assert _sub(hub, "region_w") is None  # nothing saved yet

        result = await _configure(hass, result, {"next_step_id": "plan_save"})
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        await settle(hass)
        assert setup.call_count == 1
    region = _sub(hub, "region_w")
    assert region is not None
    assert region.subentry_type == "region"
    assert region.title == "Westen · Hof"
    assert dict(region.data) == {
        "area": house.yard,
        "direction": "w",
        "temperature": [house.yard_temp],
        "humidity": [],
        "pressure": [],
    }


async def test_changing_a_sides_area_resuggests_its_sources(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    before = hub.subentries["region_south"]
    result = await _start(hass, hub)
    with count_reloads(hass) as setup:
        result = await _configure(
            hass,
            result,
            _plan(
                n={"outdoor": house.street, "rooms": [house.living_room]},
                s={"outdoor": house.yard},
            ),
        )
        assert result["step_id"] == "plan_preview"
        assert "**Süden · Hof**" in result["description_placeholders"]["preview"]
        result = await _configure(hass, result, {"next_step_id": "plan_save"})
        assert result["reason"] == "reconfigure_successful"
        await settle(hass)
        assert setup.call_count == 1
    region = hub.subentries["region_south"]
    assert region.subentry_id == before.subentry_id
    assert region.unique_id == "region_s"
    assert region.title == "Süden · Hof"
    assert dict(region.data) == {
        "area": house.yard,
        "direction": "s",
        "temperature": [house.yard_temp],
        "humidity": [],
        "pressure": [],
    }


async def test_clearing_a_side_removes_its_region(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _start(hass, hub)
    with count_reloads(hass) as setup:
        result = await _configure(
            hass,
            result,
            _plan(n={"rooms": [house.living_room]}, s={"outdoor": house.garden}),
        )
        # Nothing new to suggest: saved at once
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        await settle(hass)
        assert setup.call_count == 1
    assert _sub(hub, "region_n") is None
    assert "region_north" not in hub.subentries
    assert _sub(hub, "region_s") is not None


async def test_several_changes_give_one_reload(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _start(hass, hub)
    with count_reloads(hass) as setup:
        result = await _configure(
            hass,
            result,
            _plan(
                e={"outdoor": house.street, "rooms": [house.living_room]},
                w={"outdoor": house.yard},
            ),
        )
        result = await _configure(hass, result, {"next_step_id": "plan_save"})
        await settle(hass)
        assert setup.call_count == 1
    assert {
        s.unique_id for s in hub.subentries.values() if s.subentry_type == "region"
    } == {
        "region_e",
        "region_w",
    }
    assert hub.subentries["room_living"].data["side"] == "e"


async def test_adjust_returns_to_the_form_with_the_answers(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _start(hass, hub)
    result = await _configure(
        hass,
        result,
        _plan(
            n={"outdoor": house.street, "rooms": [house.living_room]},
            s={"outdoor": house.garden},
            w={"outdoor": house.yard},
        ),
    )
    result = await _configure(hass, result, {"next_step_id": "plan_adjust"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert suggested(result, "w.outdoor") == house.yard
    assert _sub(hub, "region_w") is None


async def test_unchanged_plan_saves_without_a_reload(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _start(hass, hub)
    with count_reloads(hass) as setup:
        result = await _configure(
            hass,
            result,
            _plan(
                n={"outdoor": house.street, "rooms": [house.living_room]},
                s={"outdoor": house.garden},
            ),
        )
        assert result["reason"] == "reconfigure_successful"
        await settle(hass)
        assert setup.call_count == 0


async def test_errors_are_the_same_as_in_the_first_setup(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await _start(hass, hub)
    result = await _configure(
        hass,
        result,
        _plan(n={"outdoor": house.garden}, s={"outdoor": house.garden}),
    )
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "outdoor_twice"}
    assert result["description_placeholders"]["side"] == "Norden"

    result = await _configure(
        hass,
        result,
        _plan(n={"rooms": [house.living_room]}, s={"rooms": [house.living_room]}),
    )
    assert result["errors"] == {"base": "room_two_sides"}
