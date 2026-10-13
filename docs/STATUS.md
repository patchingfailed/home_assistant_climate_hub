# Status

Updated 2026-10-13. The only place for project status.

## Now

UI mockups are approved (2026-10-13). The native-UI spike ran on DEV (branch `spike/native-ui`, never merged):
results in `docs/ui_mockups.md` §7. Its code stays deployed on DEV, without a hub entry, for Felix's click review.
No product code exists yet. The logic spec `docs/logic.md` is approved (2026-10-13, D1–D16 except the replaced D13)
and folded into `docs/requirements.md` and the mockups.

## Next

1. **Rest of the click review on DEV** (Felix, optional): §7 items 3 (markdown table), 5 (success
   text), 10 (area per picker row). Item 2 (phone) is skipped by choice. DEV has a few mirrored entities assigned to
   areas as test fixtures (list and undo in the private local notes).
2. **Minimum HA version** as an ADR (at least 2025.10 for menu option descriptions; the spike ran on 2026.10.1).
3. **Pure logic modules** with table tests, per `docs/logic.md` (approved): one Sonnet implementer per module in the
   order of its §15 (`const` + `psychro` → `sources` → `outdoor` → `comfort` → `strategy` → `window` →
   `recommendation` → `cover` → `prefill` → `house`), building `custom_components/climate_hub/logic/` +
   `tests/logic/` (rule 6: no HA imports, `now` as a parameter). The table cases are the acceptance tests. Branch off
   `planning/kickoff`. The spike branch `spike/native-ui` shows working flow/subentry/repair idioms for the later UI
   build (reference only, never merge).
4. **CI**: pytest, ruff, hassfest, HACS validation.
5. After the review: remove the spike from DEV.

## Open decisions

- None. Scope guard from the review: no energy-exchange model (requirements §7); the cover recommendation is advisory
  and leaves existing cover automations untouched.

## Recently done

- 2026-10-13: logic spec approved. D15 (forecast bias A14, weather offset per side O5) and D16 (cover recommendation
  with heat and cold barrier, SH1/SH2) folded into the requirements; mockups §6 rename „Beschattung" to „Rollladen"
  (`sensor.<area>_fenster_rollladen`) and „Irgendwo beschatten" to „Irgendwo Rollladen schließen". Verified on DEV:
  no (spec only).

- 2026-10-13: first review of the logic spec. D1–D12 and D14 approved and folded into the requirements; R13 becomes an
  attribute (mockups §6). From the review: D15 (forecast bias and weather offset per side) and D16 (cover
  recommendation with heat and cold barrier) added to the spec. Verified on DEV: no (spec only).
- 2026-10-13: logic spec drafted (`docs/logic.md`): ten pure modules with interfaces and table cases, reference
  values computed (psychrometrics, offset learning, fallback means). Proposes D1–D14, among them a glide for offsets at
  the fallback switch, a binary recommendation with goals, a humidity guard against humid summer air, and a 24 h
  forecast horizon. Verified on DEV: no (spec only).
- 2026-10-13: U11 closed, native UI (ADR-001 confirmed). R3: humidity and pressure follow the temperature devices;
  without such devices the list is pre-filled from the area. Drag-sorting confirmed on DEV.
- 2026-10-13: second click review on DEV folded into the mockups. Copy rule (no first person). S8d with one field per
  position. Windows start with the room; contacts filtered with „Alle Kontakte zeigen". S2/S3 use computed lists,
  S2 pre-selects by floors and thermostats. S5 shows the real card layout. Verified on DEV: yes (spike, UI).

- 2026-10-13: ADR-007, device names without the area (accepted by Felix); E3 and the mockups follow it. First click
  review on DEV showed stale translations from the browser cache (the server serves the new ones).
- 2026-10-13: native-UI spike on DEV (HA 2026.10.1). 11 of 12 mechanisms work at API and source level; the area
  doubles in entity IDs when the device name contains it. Pitfalls added to the project skill; `deploy.ps1 -Restart`
  now waits until HA runs again. Spike tests green (7), ruff clean. Verified on DEV: yes (API level; UI look pending).
- 2026-10-13: mockups approved after the second prototype review (entity list, defaults Q5, S8d, optional windows
  step, heating/cooling, repairs). Window names default to „{Bereich} Fenster"; the double leaf's shared contact is a main
  field. Verified on DEV: no.

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
