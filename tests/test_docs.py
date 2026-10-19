"""Guards for the user documentation: completeness, banned words, relative links.

Plain file reads, no Home Assistant fixtures.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EN_JSON = ROOT / "custom_components" / "climate_hub" / "translations" / "en.json"
REFERENCE = ROOT / "docs" / "reference.md"
AGENT_SKILL = ROOT / "docs" / "agent" / "climate-hub" / "SKILL.md"

# Files the banned-word and link checks cover; later work adds files here.
CHECKED_FILES = (ROOT / "README.md", REFERENCE, AGENT_SKILL)

_LINK_PATTERNS = (
    re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)"),
    re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']"""),
    re.compile(r"""\bsrcset\s*=\s*["']([^"']+)["']"""),
)
_EXTERNAL = ("http:", "https:", "mailto:")


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
        if target.startswith(_EXTERNAL):
            continue
        where = f"{path.relative_to(ROOT)}:{number}: {target}"
        file_part, _, anchor = target.partition("#")
        linked = (path.parent / file_part).resolve() if file_part else path
        if not linked.exists():
            problems.append(f"{where} (file not found)")
        elif anchor and linked.suffix == ".md" and anchor not in _anchors(linked):
            problems.append(f"{where} (no such heading)")
    assert not problems, "broken links:\n" + "\n".join(problems)
