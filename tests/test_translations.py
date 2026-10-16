"""Translation files stay consistent (docs/integration.md section 12).

Step 12 added the hub flow's steps, errors and options; the entity keys follow.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from custom_components.climate_hub.binary_sensor import BINARY_SENSORS
from custom_components.climate_hub.flows.preview import WeatherKind
from custom_components.climate_hub.logic.cover import CoverAdvice, CoverReason
from custom_components.climate_hub.logic.recommendation import Recommendation
from custom_components.climate_hub.logic.strategy import Strategy
from custom_components.climate_hub.logic.window import Level, OpenLeaves
from custom_components.climate_hub.sensor import SENSORS

COMPONENT = Path(__file__).parent.parent / "custom_components" / "climate_hub"
LANGUAGES = ("en", "de")


def _load(language: str) -> dict[str, Any]:
    path = COMPONENT / "translations" / f"{language}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _leaves(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{path}.{key}" if path else key)
    else:
        yield path, node


def test_key_sets_are_identical() -> None:
    keys = {lang: {p for p, _ in _leaves(_load(lang))} for lang in LANGUAGES}
    assert keys["en"] - keys["de"] == set()
    assert keys["de"] - keys["en"] == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_values_have_no_surrounding_whitespace(language: str) -> None:
    """hassfest rejects them; spacing and paragraph breaks are added in code."""
    bad = [
        path
        for path, value in _leaves(_load(language))
        if isinstance(value, str) and value != value.strip()
    ]
    assert bad == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_placeholders_are_not_quoted(language: str) -> None:
    bad = [
        path
        for path, value in _leaves(_load(language))
        if isinstance(value, str) and re.search(r"'\{\w+\}'", value)
    ]
    assert bad == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_common_keys_used_in_flows_exist(language: str) -> None:
    common = _load(language)["common"]
    used: set[str] = set()
    for path in (COMPONENT / "flows").glob("*.py"):
        used |= set(re.findall(r'texts\(\s*"(\w+)"', path.read_text(encoding="utf-8")))
    # Keys composed in code
    used |= {f"direction_{d}" for d in "nesw"}
    used |= {
        f"exclusion_{name}"
        for name in (
            "diagnostic",
            "helper",
            "no_device",
            "contact",
            "motion",
            "secondary",
            "several_temperatures",
            "implausible",
        )
    }
    used |= {"preview_humidity", "preview_pressure", "outside_words"}
    used |= {"plan_no_side", "plan_no_side_no_weather"}
    used |= {"relation_colder", "relation_warmer", "chain_first_one", "chain_first_two"}
    assert sorted(used - common.keys()) == []


SIDE_SECTIONS = {side: {"outdoor", "rooms"} for side in ("n", "e", "s", "w")}
CONFIG_FORMS = {
    "user": {"weather", "area_sync"},
    "rooms": {"rooms"},
    "plan": set(),
    "reconfigure": set(),
}
WINDOW_STEPS = {
    "window_room",
    "window_type",
    "window_single",
    "window_double",
    "window_pass_through",
    "window_mapping",
    "window_preview",
}
PLACEHOLDERS = {
    ("config", "step", "user", "description"): {
        "rooms",
        "outdoor",
        "contacts",
        "weather",
    },
    ("config", "step", "preview", "description"): {"preview"},
    ("config", "step", "plan_preview", "description"): {"preview"},
    ("config", "error", "outdoor_twice"): {"area", "side"},
}


def _at(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    for key in path:
        data = data[key]
    return data


@pytest.mark.parametrize("language", LANGUAGES)
def test_config_flow_strings(language: str) -> None:
    config = _load(language)["config"]
    steps = config["step"]
    assert set(steps) == {*CONFIG_FORMS, *WINDOW_STEPS, "preview", "plan_preview"}
    for step in steps.values():
        assert step["title"]
    for step, fields in CONFIG_FORMS.items():
        assert set(steps[step].get("data", {})) == fields
    for step in ("plan", "reconfigure"):
        sections = steps[step]["sections"]
        assert {k: set(v["data"]) for k, v in sections.items()} == SIDE_SECTIONS
        assert all(v["name"] for v in sections.values())
    assert set(steps["preview"]["menu_options"]) == {
        "create",
        "add_window",
        "rooms",
        "plan",
    }
    assert set(steps["plan_preview"]["menu_options"]) == {"plan_save", "plan_adjust"}
    assert set(config["error"]) == {
        "no_rooms",
        "room_two_sides",
        "outdoor_twice",
        "no_contact",
        "same_contact",
    }
    assert config["create_entry"]["created"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_options_flow_strings(language: str) -> None:
    step = _load(language)["options"]["step"]["init"]
    assert set(step) >= {"title", "data", "sections"}
    assert set(step["data"]) == {"weather", "area_sync"}
    assert set(step["sections"]["timing"]["data"]) == {
        "max_age",
        "burst_duration",
        "humidity_threshold",
        "repair_delay",
    }
    assert step["sections"]["timing"]["name"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_flow_placeholders_are_known(language: str) -> None:
    data = _load(language)
    for path, expected in PLACEHOLDERS.items():
        used = set(re.findall(r"\{(\w+)\}", _at(data, path)))
        assert used <= expected, path


@pytest.mark.parametrize("language", LANGUAGES)
def test_step_ids_in_code_are_translated(language: str) -> None:
    data = _load(language)
    for file, root in (
        (COMPONENT / "config_flow.py", data["config"]["step"]),
        (COMPONENT / "flows" / "options.py", data["options"]["step"]),
    ):
        used = set(re.findall(r'step_id="(\w+)"', file.read_text(encoding="utf-8")))
        assert used and sorted(used - root.keys()) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_outside_words_are_a_word_list(language: str) -> None:
    words = [w.strip() for w in _load(language)["common"]["outside_words"].split(",")]
    assert len(words) > 3 and all(words)


@pytest.mark.parametrize("language", LANGUAGES)
def test_entity_descriptions_are_translated(language: str) -> None:
    """Every description has a name, every enum option a state (step 14 included)."""
    entity = _load(language)["entity"]
    for description in SENSORS:
        translation = entity["sensor"][description.key]
        assert translation["name"], description.key
        for option in description.options or []:
            assert translation["state"][option], (description.key, option)
    for description in BINARY_SENSORS:
        assert entity["binary_sensor"][description.key]["name"], description.key


@pytest.mark.parametrize("language", LANGUAGES)
def test_window_attribute_values_and_device_are_translated(language: str) -> None:
    data = _load(language)
    sensors = data["entity"]["sensor"]
    reasons = sensors["cover"]["state_attributes"]["reason"]["state"]
    assert set(reasons) == {reason.value for reason in CoverReason}
    leaves = sensors["state"]["state_attributes"]["open_leaves"]["state"]
    assert set(leaves) == {leaf.value for leaf in OpenLeaves}
    assert data["entity"]["binary_sensor"]["any_cover_to_close"]["state_attributes"]
    assert set(re.findall(r"\{(\w+)\}", data["device"]["window_area"]["name"])) == {
        "area",
        "name",
    }


def _step_ids(file: Path) -> set[str]:
    return set(re.findall(r'step_id="(\w+)"', file.read_text(encoding="utf-8")))


@pytest.mark.parametrize("language", LANGUAGES)
def test_window_steps_are_translated_in_both_flows(language: str) -> None:
    """The mixin runs in the subentry flow and in the first setup."""
    data = _load(language)
    used = _step_ids(COMPONENT / "flows" / "window.py")
    assert used and used <= WINDOW_STEPS
    for steps in (data["config"]["step"], data["config_subentries"]["window"]["step"]):
        assert sorted(WINDOW_STEPS - steps.keys()) == []
        assert steps["window_type"]["menu_option_descriptions"].keys() == {
            "window_single",
            "window_double",
            "window_pass_through",
        }
    assert set(data["options"]["step"]) == {"init", "weather_check"}
    assert set(data["options"]["step"]["weather_check"]["menu_options"]) == {
        "weather_keep",
        "weather_adjust",
    }


@pytest.mark.parametrize("language", LANGUAGES)
def test_composed_common_keys_cover_the_logic_enums(language: str) -> None:
    """Preview fragments built from enum values (`texts(f"...")`)."""
    common = _load(language)["common"]
    expected = {f"level_{level.name.lower()}" for level in Level}
    expected |= {f"leaves_{leaf}" for leaf in ("left", "right", "both")}
    expected |= {
        f"recommendation_{r.value}"
        for r in Recommendation
        if r is not Recommendation.NONE
    }
    expected |= {f"strategy_{s.value}" for s in Strategy}
    expected |= {f"cover_{a.value}" for a in CoverAdvice if a is not CoverAdvice.NONE}
    expected |= {f"cover_reason_{r.value}" for r in CoverReason}
    expected |= {f"weather_{kind.value}" for kind in WeatherKind}
    expected |= {"weather_values", "weather_values_temperature"}
    assert sorted(expected - common.keys()) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_level_words_are_word_lists(language: str) -> None:
    common = _load(language)["common"]
    for level in Level:
        words = [w.strip() for w in common[f"words_{level.name.lower()}"].split(",")]
        assert words and all(words)


@pytest.mark.parametrize("language", LANGUAGES)
def test_issue_translations_cover_the_keys_used_in_code(language: str) -> None:
    """Every key `issues.py` uses exists; each issue has a title and either a
    description or a fix flow (hassfest: they are mutually exclusive)."""
    data = _load(language)
    source = (COMPONENT / "issues.py").read_text(encoding="utf-8")
    used = set(re.findall(r'translation_key="(\w+)"', source))
    used |= set(re.findall(r'key(?:, active)? = "(\w+)"', source))
    used |= {"outage", "outage_fallback", "outage_none"}
    assert used >= {"new_source", "windows_without_room"}
    issues = data["issues"]
    assert sorted(used - issues.keys()) == []
    for key, issue in issues.items():
        assert issue["title"], key
        assert ("description" in issue) != ("fix_flow" in issue), key
    common = data["common"]
    for metric in ("temperature", "humidity", "pressure"):
        assert common[f"issue_offset_{metric}"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_repair_flow_steps_are_translated(language: str) -> None:
    issues = _load(language)["issues"]
    source = (COMPONENT / "repairs.py").read_text(encoding="utf-8")
    used = set(re.findall(r'step_id="(\w+)"', source))
    steps = {
        step
        for issue in ("new_source", "windows_without_room")
        for step in issues[issue]["fix_flow"]["step"]
    }
    assert used and used <= steps
    for issue in ("new_source", "windows_without_room"):
        assert issues[issue]["fix_flow"]["abort"]["gone"]
