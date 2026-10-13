"""Rule 6: the logic imports nothing from Home Assistant and never reads the clock."""

import ast
from pathlib import Path

import pytest

LOGIC = Path(__file__).parents[2] / "custom_components" / "climate_hub" / "logic"
FORBIDDEN_MODULES = {"homeassistant", "time"}
CLOCK_CALLS = {"now", "utcnow", "today"}


@pytest.mark.parametrize("path", sorted(LOGIC.glob("*.py")), ids=lambda p: p.name)
def test_module_is_pure(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            names = []
        roots = {name.split(".")[0] for name in names}
        assert not roots & FORBIDDEN_MODULES, f"import in line {node.lineno}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in CLOCK_CALLS, f"clock in line {node.lineno}"
