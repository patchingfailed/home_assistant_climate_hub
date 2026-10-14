"""Translation files stay consistent (docs/integration.md section 12).

Step 12 added the hub flow's steps, errors and options; the entity keys follow.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

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
    assert set(steps) == {*CONFIG_FORMS, "preview", "plan_preview"}
    for step in steps.values():
        assert step["title"]
    for step, fields in CONFIG_FORMS.items():
        assert set(steps[step].get("data", {})) == fields
    for step in ("plan", "reconfigure"):
        sections = steps[step]["sections"]
        assert {k: set(v["data"]) for k, v in sections.items()} == SIDE_SECTIONS
        assert all(v["name"] for v in sections.values())
    assert set(steps["preview"]["menu_options"]) == {"create", "rooms", "plan"}
    assert set(steps["plan_preview"]["menu_options"]) == {"plan_save", "plan_adjust"}
    assert set(config["error"]) == {"no_rooms", "room_two_sides", "outdoor_twice"}
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
