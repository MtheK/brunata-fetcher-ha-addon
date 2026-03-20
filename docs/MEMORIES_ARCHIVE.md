# Memories archive

Date archived: 2026-03-08

This file mirrors important agent memory notes into the repository so context
is still available after long breaks.

## User memory (cross-repo preference)

- Keep the marker `# TODO: not working yet` in
  `config/custom_components/brunata_fetcher/__init__.py` in the old
  integration repo (`brunata-fetcher-ha`) because Playwright auto-install is
  known to be unreliable there.

## Repo memory (`brunata-fetcher-ha-addon`)

- Release merged from `next` to `main` on 2026-03-08.
- Stable add-on version is `0.2.0`.
- Startup uses `#!/usr/bin/with-contenv bashio` in `brunata_fetcher/run.sh`
  so `SUPERVISOR_TOKEN` is available at runtime.
- MQTT resolution priority is:
  manual advanced values > Supervisor service discovery (`/services/mqtt`) >
  defaults.
- MQTT startup is hardened:
  wait for CONNACK before first publish and guard publish when disconnected.
- Portal query health monitoring exists as binary sensor with
  `device_class: problem` and state topic:
  `brunata_fetcher/binary_sensor/portal_query_problem/state`.
- Portal query status icon is dynamic:
  - OK: `mdi:check-decagram-outline`
  - Failure: `mdi:alert-decagram-outline`
- Success criteria for portal queries are strict:
  at least one configured energy value plus plausible `last_update_date`
  (`DD.MM.YYYY`).
- Failed query triggers HA persistent notification via core proxy
  (`persistent_notification.create`) with anti-spam behavior per failure phase.
- `.gitignore` ignores Python cache artifacts (`__pycache__/`, `*.py[cod]`).
- Smoke test coverage lives in `brunata_fetcher/smoke_local.py`.

## Session exploration highlights (historical)

- This add-on exists because direct Playwright use inside the old HA custom
  integration had recurring runtime/install limitations.
- The add-on approach solves that by packaging Playwright + Chromium in the
  container image and publishing via MQTT Discovery.
- Important selectors and German number parsing logic were carried over from
  earlier exploration and are still central for portal scraping stability.

## Related docs

- `docs/SESSION_HANDOVER.md` for release and handover summary.
- `.github/copilot-instructions.md` for repository-specific agent guidance.
