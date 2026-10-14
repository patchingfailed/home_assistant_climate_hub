"""Translation files stay consistent (docs/integration.md section 12).

Step 12 extends this with the hub flow's steps, errors and the entity keys.
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
    used |= {"preview_humidity", "preview_pressure"}
    used |= {"relation_colder", "relation_warmer", "chain_first_one", "chain_first_two"}
    assert sorted(used - common.keys()) == []
