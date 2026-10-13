# Status

Updated 2026-10-13. The only place for project status.

## Now

UI mockups v2 are drafted and a clickable prototype of them exists for review (private Claude artifact
„Climate Hub Prototyp", built from `docs/ui_mockups.md` v2 with example data). No integration code exists yet.

## Next

1. **Prototype review** (Felix): flow, texts, order; open points in `docs/ui_mockups.md` §8. Prototype-only choices
   to confirm or reject: S1 counts computed from the scan, S4 lists all further sources per room, a room without a
   main side defaults to „Keine", deleting a room deletes its windows.
2. **DEV spike** on a throwaway branch for `docs/ui_mockups.md` §7 (11 items, incl. the area prefix in entity IDs).
   Before the first deploy: set `HA_DEV_TOKEN` in the shell (not set yet), remove old `climate_hub` entries and the
   old `custom_components/climate_hub` folder on DEV.
3. **Minimum HA version** as an ADR after the spike (at least 2025.10 for menu option descriptions).
4. **Logic spec and pure logic modules** with table tests: psychrometrics (absolute humidity, dew point, humidity after
   ventilating), source resolution with offset learning, region fallback, window state, recommendation (A1–A6),
   shading (SH1).
5. **CI**: pytest, ruff, hassfest, HACS validation.

## Open decisions

- `docs/ui_mockups.md` §8: entity list complete (4), defaults = requirements Q5 (6), text-sensor state mapping S8d (7),
  „Hinzufügen" only in the ⋮ menu (8).
- ADR-005 naming may change if Home Assistant prefixes the area to new entity IDs (spike item 6).
- U11: native UI vs. custom panel, decided after the DEV spike and the prototype review.

## Recently done

- 2026-10-13: mockups v2. Checked the native flow capabilities against core and frontend source (§2.4, §7).
  Room and region creation now start with the area. Window contacts are filtered by type only (U6 exception), and the
  window name is optional. Main side always offers four directions. New S8d text-sensor mapping (W2). Fixed leftover
  examples in the project skill. Clickable prototype built and published for review. Verified on DEV: no.
- 2026-10-13: toolchain. Python 3.14.7, `.venv`, `requirements_test.txt` (`pytest-homeassistant-custom-component`
  0.13.372 = HA 2026.10.1, ruff 0.17.0), ruff target `py314`, local `scripts/deploy.config.ps1`. HA 2026.10 imports
  `fcntl` at test startup, so `win_compat.py` stubs it on Windows (`-p win_compat`). `python -m pytest` starts (0 tests),
  ruff green. Note: the Python installer asks for UAC even with `--scope user`.
- 2026-10-12: project scaffolding (CLAUDE.md, deploy script, test conftest, Claude settings and skill);
  `docs/requirements.md`, `docs/architecture.md` (ADR-001 to ADR-006), `docs/ui_mockups.md`, this file.
  Verified on DEV: no (nothing built yet).
