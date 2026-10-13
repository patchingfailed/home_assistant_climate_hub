# Status

Updated 2026-10-13. The only place for project status.

## Now

UI mockups v2 are drafted and updated after the first prototype review. The clickable prototype (private Claude
artifact „Climate Hub Prototyp", example data) shows that state, including repairs and a contact tool for the W12
table. No integration code exists yet.

## Next

1. **Second prototype review** (Felix): open points in `docs/ui_mockups.md` §8 (4, 6, 7, 8, 9, 10). Prototype-only
   choices to confirm or reject: S1 counts computed from the scan, S4 lists all further sources per room, a room
   without a main side defaults to „Keine".
2. **DEV spike** on a throwaway branch for `docs/ui_mockups.md` §7 (12 items, incl. the area prefix in entity IDs).
   DEV is clean (no old `climate_hub` entries, entities, devices or folder; checked 2026-10-13). `deploy.ps1 -Restart`
   and `-Logs` need `HA_DEV_TOKEN` in the shell (not set yet).
3. **Minimum HA version** as an ADR after the spike (at least 2025.10 for menu option descriptions).
4. **Logic spec and pure logic modules** with table tests: psychrometrics (absolute humidity, dew point, humidity after
   ventilating), source resolution with offset learning, region fallback, window state, recommendation (A1–A6),
   shading (SH1).
5. **CI**: pytest, ruff, hassfest, HACS validation.

## Open decisions

- `docs/ui_mockups.md` §8: entity list complete (4), defaults = requirements Q5 (6), text-sensor state mapping S8d (7),
  optional windows step in the first setup (8), heating/cooling role and warning (9), repairs (10).
- ADR-005 naming may change if Home Assistant prefixes the area to new entity IDs (spike item 6).
- U11: native UI vs. custom panel, decided after the DEV spike and the prototype review.

## Recently done

- 2026-10-13: first prototype review folded in. Requirements R5, R6, R14, R15, A12, W0, W11, W12 (truth table) and U1;
  mockups S4, S5, S6, S8, S11 and §6–§8. Prototype republished. Verified on DEV: no.
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
