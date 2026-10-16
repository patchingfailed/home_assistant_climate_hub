---
name: ha-integration-dev
description: Development workflow for the Climate Hub Home Assistant custom integration. Covers the deploy-test-debug cycle against the DEV HA instance, reload vs restart rules, log analysis, entity/attribute inspection, config/subentry/options flow testing in the UI, and known HA pitfalls.
---

# HA Integration Dev - Climate Hub

## Environment

- Hosts, shares and tokens live **only** in `scripts/deploy.config.ps1`
  (gitignored, template `deploy.config.example.ps1`). Never write IPs into any other file.
- DEV is the target of every test. **Prod only after explicit user approval.**
- DEV UI: `http://<DevHost>:8123`.

## Cycle

1. `python -m pytest` + `ruff check .` must be green before deploying.
2. `.\scripts\deploy.ps1` (copy only) or `.\scripts\deploy.ps1 -Restart`.
3. Reload or restart:

   | Change | Action |
   |---|---|
   | Logic in existing files, flow steps, coordinator | Reload (UI: Settings -> Devices & Services -> Climate Hub -> (...) -> Reload) |
   | New file / new module | Restart |
   | `manifest.json` | Restart |
   | New platform in `PLATFORMS` | Restart |
   | Translations | Restart + browser reload (frontend cache) |

4. `.\scripts\deploy.ps1 -Logs` prints the `climate_hub` lines from the error log.
5. Smoke test (below), then note the result in `docs/STATUS.md`.

Debug logging on DEV (`configuration.yaml`):
```yaml
logger:
  default: warning
  logs:
    custom_components.climate_hub: debug
```

## Smoke test in the DEV UI

- [ ] Add the integration (hub flow) and check the entry.
- [ ] Per subentry type (room, outdoor region, window): create, reconfigure, delete.
- [ ] Change options, verify the effect without a restart.
- [ ] Entities: values, units, `device_class`, attributes (source, stage, reason, offset).
- [ ] Enum/attribute translations in the dashboard and the more-info dialog (de **and** en).
- [ ] Download diagnostics and check the decision chain (sources, stages, learned offsets).
- [ ] Log has no ERROR/WARNING from `climate_hub`.

## Entity state via REST (token from the config)

```powershell
. .\scripts\deploy.config.ps1
$h = @{ Authorization = "Bearer $DevToken" }
Invoke-RestMethod "http://${DevHost}:8123/api/states/sensor.arbeitszimmer_klima_temperatur" -Headers $h
(Invoke-RestMethod "http://${DevHost}:8123/api/states" -Headers $h) | Where-Object entity_id -like "*_klima_*"
```

## Known pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Options flow 500, `can't set attribute 'config_entry'` | `self.config_entry = ...` in a custom `__init__` | No custom `__init__`, use `self.config_entry` |
| `SocketBlockedError` in every test (Windows) | HA test plugin blocks sockets, Windows event loop needs AF_INET | Fix in `tests/conftest.py`, don't remove it |
| Room sensors not found | `er.async_entries_for_area` ignores device-inherited areas | `entity.area_id or device.area_id` |
| Sensor treated as stale despite reporting | `last_updated` instead of `last_reported` | Use `last_reported` |
| Min/max jumps to the setpoint | `climate.*` attribute `temperature` instead of `current_temperature` | Only `current_temperature` |
| Dropdown field can't be cleared | `vol.Optional(default=...)` | Use `suggested_value` |
| Raw state (`keep_open`) in the dashboard | No enum sensor | `SensorDeviceClass.ENUM` + `translation_key` |
| New platform doesn't show up after reload | Platforms are only registered on start | Restart |
| Entity history lost | `unique_id` changed | Never change it; the schema lives in `docs/architecture.md` |
| `ModuleNotFoundError: voluptuous` on DEV | HA 2026.10 validates with `probatio` (pinned 0.13.0); voluptuous is gone from HA OS | `import probatio` (same `Schema`/`Required`/`Optional` API) |
| Menu step gives HTTP 500 `UnknownStep` | `async_show_menu(step_id=x)` without an `async_step_x` | Every menu step id needs a real step method; a second translation variant gets its own alias step |
| Dialog shows the raw key `reconfigure_successful` | Custom integrations get no common abort strings; the frontend falls back to the reason | `config.abort` and `config_subentries.<type>.abort` in every language (`tests/test_translations.py` guards it) |
| "Cannot update and reload entry with update listeners" | `async_update_reload_and_abort` while an update listener is registered | `async_update_and_abort`; the listener reloads |
| Entity ID `sensor.kuche_kuche_klima_…` | HA puts the area in front of new entity IDs (default `entity_id_parts`) and does not strip it from the device name | Device names without the area |
| Device stays in the old area after a room's area changed | `suggested_area` only places a new device | `device_registry.async_update_device(device_id, area_id=…)` on area change |
| `deploy.ps1 -Restart` prints a connection error | HA closes the connection while restarting | Expected; the script waits for `/api/config` afterwards |

## Workflow decision tree

```
Change made
├─ Tests/ruff green? ── no → fix first
├─ New file / manifest / platform / translations? → deploy -Restart
├─ Otherwise → deploy → Reload in the UI
├─ Value wrong?        → attributes (source/stage/reason) → diagnostics → write a logic/ test that reproduces it
├─ Flow crashes?        → deploy -Logs → traceback → flow-manager test that reproduces it
└─ Done                 → smoke test → STATUS.md
```
