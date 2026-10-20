"""Guards for the documentation: completeness, banned words, links, section references.

Plain file reads, no Home Assistant fixtures.
"""

import ast
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "custom_components" / "climate_hub"
EN_JSON = PACKAGE / "translations" / "en.json"
REFERENCE = ROOT / "docs" / "reference.md"
AGENT_SKILL = ROOT / "docs" / "agent" / "climate-hub" / "SKILL.md"
LOGIC = ROOT / "docs" / "logic.md"
INTEGRATION = ROOT / "docs" / "integration.md"
SPECS = {"logic": LOGIC, "integration": INTEGRATION}

# Files the banned-word and link checks cover.
CHECKED_FILES = (ROOT / "README.md", REFERENCE, AGENT_SKILL, LOGIC, INTEGRATION)

_LINK_PATTERNS = (
    re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)"),
    re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']"""),
    re.compile(r"""\bsrcset\s*=\s*["']([^"']+)["']"""),
)
_EXTERNAL = ("http:", "https:", "mailto:")
# README images use absolute URLs into the main branch (HACS renders no relative ones);
# they must name a file that exists in the repository.
_RAW_MAIN = (
    "https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/"
)


def _backticked(text: str) -> set[str]:
    return set(re.findall(r"`([^`\n]+)`", text))


def _expected_reference_words() -> set[str]:
    """Entity keys, their states, attribute names and attribute states of en.json."""
    entities = json.loads(EN_JSON.read_text(encoding="utf-8"))["entity"]
    words: set[str] = set()
    for platform in entities.values():
        for key, entity in platform.items():
            words.add(key)
            words.update(entity.get("state", {}))
            for attribute, spec in entity.get("state_attributes", {}).items():
                words.add(attribute)
                words.update(spec.get("state", {}))
    return words


@pytest.mark.parametrize("path", (REFERENCE, AGENT_SKILL), ids=lambda p: p.name)
def test_covers_every_entity_key_state_and_attribute(path: Path) -> None:
    documented = _backticked(path.read_text(encoding="utf-8"))
    missing = sorted(_expected_reference_words() - documented)
    assert not missing, (
        f"{path.relative_to(ROOT)} lacks backticked: {', '.join(missing)}"
    )


def _banned_words() -> list[str]:
    lines = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("- Banned words"))
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.strip() or line.startswith("- "):
            break
        block.append(line)
    return re.findall(r"`([^`]+)`", " ".join(block))


def _markdown_lines(path: Path) -> list[tuple[int, str]]:
    return list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))


def test_banned_words_list_is_found() -> None:
    assert len(_banned_words()) >= 5


@pytest.mark.parametrize("path", CHECKED_FILES, ids=lambda p: p.name)
def test_no_banned_words(path: Path) -> None:
    words = _banned_words()
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")\b", re.I)
    hits = [
        f"{path.relative_to(ROOT)}:{number}: {match.group(0)}"
        for number, line in _markdown_lines(path)
        for match in pattern.finditer(line)
    ]
    assert not hits, "banned words:\n" + "\n".join(hits)


def _slug(heading: str) -> str:
    text = heading.strip().lower().replace("`", "")
    text = re.sub(r"[^\w\s-]", "", text)
    return text.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    """GitHub anchors of the headings of a markdown file (duplicates get -1, -2...)."""
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else re.match(r"#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match is None:
            continue
        slug = _slug(match.group(1))
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def _targets(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    in_fence = False
    for number, line in _markdown_lines(path):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if in_fence:
            continue
        for pattern in _LINK_PATTERNS:
            for match in pattern.finditer(line):
                raw = match.group(1)
                if pattern.pattern.startswith(r"\bsrcset"):
                    # "url 1x, url 2x": each candidate's first token is a URL
                    found.extend(
                        (number, part.split()[0])
                        for part in raw.split(",")
                        if part.strip()
                    )
                else:
                    found.append((number, raw))
    return found


@pytest.mark.parametrize("path", CHECKED_FILES, ids=lambda p: p.name)
def test_relative_links_resolve(path: Path) -> None:
    problems = []
    for number, target in _targets(path):
        where = f"{path.relative_to(ROOT)}:{number}: {target}"
        if target.startswith(_RAW_MAIN):
            if not (ROOT / target.removeprefix(_RAW_MAIN)).exists():
                problems.append(f"{where} (file not in the repository)")
            continue
        if target.startswith(_EXTERNAL):
            continue
        file_part, _, anchor = target.partition("#")
        linked = (path.parent / file_part).resolve() if file_part else path
        if not linked.exists():
            problems.append(f"{where} (file not found)")
        elif anchor and linked.suffix == ".md" and anchor not in _anchors(linked):
            problems.append(f"{where} (no such heading)")
    assert not problems, "broken links:\n" + "\n".join(problems)


# Section references such as "logic.md §5 rule 8", "integration §8.3" or
# "§4 rules 4 and 7", chained with commas, "and", "or" or an en dash (a range).
_SEP = r"\s*(?:,|and|or|\u2013)\s*"
_REF = rf"§\s?(\d+(?:\.\d+)?)(?:\s+(?:rules?|steps?)\s+(\d+(?:{_SEP}\d+)*))?"
_REF_ITEM = re.compile(_REF)
_REF_CHAIN = re.compile(rf"{_REF}(?:{_SEP}{_REF})*")
# The document named right before a chain; names other than the two specs are skipped.
_DOC_BEFORE = re.compile(
    r"\b(logic|integration|mockups|ui_mockups|requirements|reference|architecture)"
    r"(?:\.md)?`?\s*$"
)
_AMBIGUOUS = "ambiguous"


def _citing_files() -> list[Path]:
    """Files whose section references are checked; STATUS.md is a dated log."""
    files = [ROOT / "README.md", ROOT / "CLAUDE.md"]
    files += sorted(p for p in (ROOT / "docs").rglob("*.md") if p.name != "STATUS.md")
    files += sorted((ROOT / ".claude" / "skills").rglob("*.md"))
    files += sorted(PACKAGE.rglob("*.py")) + sorted((ROOT / "tests").rglob("*.py"))
    # this file's own patterns and messages are examples, not references
    return [f for f in files if f != Path(__file__).resolve()]


def _references(path: Path) -> Iterator[tuple[int, str, str, list[int]]]:
    """(line, spec, section, rule or step numbers) of every reference to a spec.

    A bare `§N` belongs to the spec it appears in; in Python it belongs to the one spec
    the file names, and is ambiguous when the file names none or both. Other Markdown
    files number their own sections, so their bare references are skipped.
    """
    text = path.read_text(encoding="utf-8")
    chains = []
    for chain in _REF_CHAIN.finditer(text):
        named = _DOC_BEFORE.search(text[max(0, chain.start() - 40) : chain.start()])
        chains.append((chain, named.group(1) if named else None))
    named_specs = {doc for _, doc in chains if doc in SPECS}
    own = next((name for name, spec in SPECS.items() if spec == path), None)
    if own is None and path.suffix == ".py":
        own = next(iter(named_specs)) if len(named_specs) == 1 else _AMBIGUOUS
    for chain, doc in chains:
        spec = doc if doc is not None else own
        if spec is None or (spec not in SPECS and spec != _AMBIGUOUS):
            continue
        line = text.count("\n", 0, chain.start()) + 1
        for item in _REF_ITEM.finditer(chain.group(0)):
            numbers = [int(n) for n in re.findall(r"\d+", item.group(2) or "")]
            yield line, spec, item.group(1), numbers


def _sections(path: Path) -> dict[str, list[str]]:
    """Lines outside code fences per numbered heading; `##` includes its `###`."""
    sections: dict[str, list[str]] = {}
    keys: list[str] = []
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = re.match(r"(#{2,3})\s+(\d+(?:\.\d+)?)\.?\s", line)
        if heading:
            level, number = heading.groups()
            keys = [number] if len(level) == 2 else [*keys[:1], number]
            sections[number] = []
            continue
        if line.startswith("## "):
            keys = []
        for key in keys:
            sections[key].append(line)
    return sections


def _numbered_items(lines: list[str]) -> set[int]:
    return {int(m.group(1)) for line in lines if (m := re.match(r"(\d+)\.\s", line))}


def test_section_references_are_found() -> None:
    found = {
        (spec, path) for path in _citing_files() for _, spec, _, _ in _references(path)
    }
    assert {spec for spec, _ in found} >= set(SPECS)
    assert len(found) >= 40


def test_section_references_resolve() -> None:
    sections = {name: _sections(path) for name, path in SPECS.items()}
    problems = []
    for path in _citing_files():
        for line, spec, section, numbers in _references(path):
            where = f"{path.relative_to(ROOT)}:{line}: §{section}"
            if spec == _AMBIGUOUS:
                problems.append(f"{where} (bare §: name logic.md or integration.md)")
            elif section not in sections[spec]:
                problems.append(f"{where} (no such section in {spec}.md)")
            elif missing := set(numbers) - _numbered_items(sections[spec][section]):
                items = ", ".join(map(str, sorted(missing)))
                problems.append(f"{where} (no rule or step {items} in {spec}.md)")
    assert not problems, "dead section references:\n" + "\n".join(problems)


def _module_constants(path: Path) -> list[str]:
    """Upper-case names assigned at module level."""
    names = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        names += [t.id for t in targets if isinstance(t, ast.Name) and t.id.isupper()]
    return names


def test_logic_constants_are_listed() -> None:
    listed = _backticked("\n".join(_sections(LOGIC)["13"]))
    names = _module_constants(PACKAGE / "logic" / "const.py")
    missing = [n for n in names if n not in listed]
    assert not missing, f"docs/logic.md §13 lacks: {', '.join(missing)}"


# Identifiers, not tunable values
_ADAPTER_NAMES_NOT_DOCUMENTED = {
    "DOMAIN",
    "LOGGER",
    "SUBENTRY_ROOM",
    "SUBENTRY_REGION",
    "SUBENTRY_WINDOW",
}


def test_adapter_constants_are_documented() -> None:
    documented = _backticked(INTEGRATION.read_text(encoding="utf-8"))
    names = _module_constants(PACKAGE / "const.py")
    missing = [n for n in names if n not in documented | _ADAPTER_NAMES_NOT_DOCUMENTED]
    assert not missing, f"docs/integration.md lacks: {', '.join(missing)}"
