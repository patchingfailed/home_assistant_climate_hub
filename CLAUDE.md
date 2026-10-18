# CLAUDE.md: Climate Hub

Home Assistant custom integration `climate_hub`: fuses user-ranked temperature/humidity sources into one trustworthy
value per room and per outdoor side, and recommends when to open or close windows.
Architecture: one hub config entry with subentries `room`, `region`, `window` (see `docs/architecture.md`).
Requirements: `docs/requirements.md`.

**Status lives only in `docs/STATUS.md`, decisions only in `docs/architecture.md` (ADRs).**
This file holds no status.

HA development knowledge: the `ha-dev` plugin (skills `ha-integration`, `ha-instance`).
Local hosts/instance wiring: user skill `ha-local-env` (private, never referenced here).
Deploy/test/debug workflow for this project: skill `ha-integration-dev`.

## Layout

```
custom_components/climate_hub/  integration (logic/ = pure logic without HA imports)
tests/                          pytest (logic/, flows/, integration/)
docs/                           requirements.md, STATUS.md, architecture.md (ADRs), ui_mockups.md,
                                logic.md (pure logic spec), integration.md (HA layer spec + build order)
scripts/deploy.ps1              deploy to DEV (hosts/tokens only in scripts/deploy.config.ps1, gitignored)
win_compat.py                   pytest plugin: stubs Unix-only modules so HA tests start on Windows
local input/                    private, gitignored raw material (never referenced from code or docs)
```

## Commands

```powershell
.venv\Scripts\activate
pip install -r requirements_test.txt   # once, after creating .venv with py -3.14
python -m pytest                 # all tests (Windows: win_compat.py + socket fix in tests/conftest.py)
ruff check . ; ruff format .
.\scripts\deploy.ps1             # DEV, copy only
.\scripts\deploy.ps1 -Restart    # DEV + restart (new file / manifest / platform / translations)
.\scripts\deploy.ps1 -Logs       # climate_hub log lines from DEV
```

Release (PROD installs releases through HACS): set `version` in `manifest.json`, commit, push `main`, then
`git tag -a vX.Y.Z -m "<release notes>"` and `git push origin vX.Y.Z`; `.github/workflows/release.yml` checks the
tag against the manifest and creates the GitHub release from the tag message. `deploy.ps1 -Instance Prod` is only an
emergency path (HACS then shows a stale version).

## Rules

1. **Never change unique IDs or entity IDs** without an explicit decision. HA loses history otherwise.
2. Entities: `has_entity_name=True` + `translation_key`, `device_class` + `state_class` on measurement sensors.
3. **No user-facing text in Python code.** Everything goes through `translations/en.json` (+ other languages, UTF-8).
4. **No dead paths, scaffolds or empty attribute shells.**
5. Everything configured during setup stays editable via reconfigure, even when it's empty.
6. Pure logic lives in `logic/` without HA imports, takes `now` as a parameter, and has table tests.
7. Flow changes need a test that goes through the flow manager (no fake-hass stubs).
8. **New UI starts as a mockup in `docs/ui_mockups.md`**, built only after approval.
9. A task is done only when tests have verifiably run.
10. **PROD only with explicit approval.**
11. At session end: commit, update `docs/STATUS.md`, note "verified on DEV: yes/no". Push is a deliberate, separate action, not a default.
12. Language: code, comments, commits and `docs/` in English.
13. Nothing in the repo refers to earlier iterations of this project or to private installation details.
14. **Branches:** `main` holds the current, tested state. A larger task gets a short-lived branch off `main`, merged
    back once its tests are green and Felix has looked, then deleted. Spikes (`spike/*`) are reference only, never
    merged.

## Docs

Writing rules for `README.md`, everything in `docs/`, and UI strings in `translations/` when they are added or
changed anyway.

- Numbers and conditions instead of adjectives: "falls back to the next source when the current one has not updated
  for 40 min (default `max_age`)", not "robust fallback".
- State limits and what Climate Hub does not do.
- Every statement is checkable against code or behaviour. Check it instead of hedging with "should" or "probably".
- Present tense for what is built; planned or deferred items are marked as such.
- One fact in one place; other places link to it.
- One name per concept. User docs use the English UI label ("outdoor side"); technical docs use the code name
  (`region`) and give the UI label at its first mention.
- Raw states, reasons, keys and attributes in backticks (`no_side`); UI labels as the English UI shows them.
- Not used: rhetorical questions, "not just X but Y", "Whether you …", triads for rhythm, closing summaries, emoji,
  exclamation marks, bold for emphasis. Bold marks only UI labels in click steps (Home Assistant docs convention).
- Banned words (grep list): `seamless`, `powerful`, `effortless`, `robust`, `smart`, `simply`, `just`, `easily`,
  `comprehensive`, `crucial`, `leverage`.
- Prose wraps at 120 characters.
