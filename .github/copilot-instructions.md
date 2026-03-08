# Copilot Instructions for `brunata-fetcher-ha-addon`

This repository contains a Home Assistant add-on that fetches daily consumption data from the Brunata user portal and publishes values to Home Assistant through MQTT Discovery.

## Project goal

- Run as a standalone Home Assistant add-on container
- Log in to the Brunata portal with user credentials
- Scrape meter values for configured energy types
- Publish discovery and state topics via MQTT so entities appear in Home Assistant automatically

## Why this add-on exists

The earlier Home Assistant integration project (`brunata-fetcher-ha`) hit a recurring Playwright installation/runtime limitation in the integration environment.

Important historical constraint:

- In the integration project, Playwright auto-install was not reliable enough
- A known marker exists there and must stay untouched:
  `# TODO: not working yet` in `config/custom_components/brunata_fetcher/__init__.py`
- This add-on avoids that limitation by shipping Playwright and Chromium in the container image

## Current architecture

- `brunata_fetcher/server.py`
  - Reads options from `/data/options.json`
  - Connects to MQTT
  - Publishes MQTT Discovery config topics
  - Runs periodic scrape loop (`scan_interval_hours`)
  - Publishes sensor states
- `brunata_fetcher/_brunata_scraper.py`
  - Uses `playwright.async_api`
  - Logs in and extracts date/value from Brunata UI selectors
  - Parses German number formats, for example `1.234,56`
- `brunata_fetcher/config.yaml`
  - Add-on metadata and options schema
- `brunata_fetcher/Dockerfile`
  - Installs Python dependencies
  - Installs Chromium with `playwright install chromium --with-deps`

## Data flow

1. Supervisor writes add-on options to `/data/options.json`
2. Add-on starts `server.py`
3. MQTT connection is established
4. Discovery payloads are published to `homeassistant/sensor/.../config`
5. Scraper fetches data from Brunata portal
6. State payloads are published to `brunata_fetcher/sensor/.../state`
7. Home Assistant creates and updates entities via MQTT Discovery

## Configuration contract

Required in add-on options:

- `email`
- `password`

Core options:

- `energy_types` (for example `Heizung`, `Kaltwasser`, `Warmwasser`)
- `mqtt_host`, `mqtt_port`, `mqtt_user`, `mqtt_password`
- `scan_interval_hours`

Defaults are defined in `brunata_fetcher/config.yaml`.

## Known risks and fragile points

- Brunata portal selectors can change and break scraping
- Login failure detection currently relies on text matching in page content
- Scrape loop is interval-based (not cron-based)
- Network/MQTT outages can delay updates

## Implementation rules for future changes

- Keep the add-on architecture simple: scraper logic in `_brunata_scraper.py`, orchestration in `server.py`
- Prefer explicit, observable logging for login, selector, and publish failures
- Do not move Playwright installation to runtime if avoidable; keep it container-build based
- Preserve MQTT Discovery topic stability to avoid entity churn in HA
- Keep ASCII by default in code/comments unless file already uses Unicode
- Always update `brunata_fetcher/CHANGELOG.md` for user-visible behavior changes and every version bump

## First test checklist (baseline)

Goal: verify startup stability, MQTT Discovery, and real scrape.

1. Configure add-on options with valid Brunata and MQTT credentials
2. Start the add-on from Home Assistant Supervisor
3. Verify logs show successful MQTT connection and discovery publish
4. Verify discovery topics exist:
   - `homeassistant/sensor/brunata_fetcher_*/config`
5. Verify state topics are updated after a scrape:
   - `brunata_fetcher/sensor/*/state`
6. Confirm entities appear in Home Assistant with expected units (`kWh`, `m3`) and values
7. If scrape fails, inspect and update selectors in `_brunata_scraper.py` and retest

## Recommended near-term improvements

- Add parser unit tests for German numeric formats
- Add a lightweight smoke test for MQTT payload generation
- Improve error classification in scraper logs (login vs selector vs portal availability)
