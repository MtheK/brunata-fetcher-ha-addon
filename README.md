# Brunata Fetcher Home Assistant Add-on

Home Assistant add-on that logs in to the Brunata user portal, fetches
consumption data, and publishes entities via MQTT Discovery.

Keywords: Brunata München Nutzerportal, BRUdirekt, BRUNATA-METRONA

## Features

- Scrapes Brunata portal data with Playwright inside the add-on container
- Publishes Home Assistant MQTT Discovery topics automatically
- Supports the energy types `Heizung`, `Kaltwasser`, and `Warmwasser`
- Uses Supervisor MQTT service discovery when manual MQTT settings are empty
- Provides portal query health as a binary sensor (`device_class: problem`)
- Sends a Home Assistant persistent notification when portal queries fail

## Requirements

- Home Assistant OS / Supervised with Add-on Store
- MQTT broker available (for example `core-mosquitto`)
- Brunata portal credentials (`email`, `password`)

## Installation

1. Add this repository in Home Assistant Add-on Store.
2. Install `Brunata Fetcher`.
3. Configure required options (`email`, `password`).
4. Start the add-on.
5. Verify entities appear in Home Assistant.

## Configuration

Main options:

- `email` (required)
- `password` (required)
- `energy_types` (checkboxes)
- `scan_interval_hours` (1..168)

Advanced options:

- `mqtt_host`
- `mqtt_port`
- `mqtt_user`
- `mqtt_password`
- `scraper_url`

Notes:

- If advanced MQTT host/user/password are left empty, the add-on attempts to
  use Supervisor service discovery (`/services/mqtt`).
- `mqtt_port` remains configurable and defaults to `1883`.

## Published entities

Core sensors:

- Energy sensors for selected energy types
- `Letztes Update` (portal update date)
- `Letzte Portal-Abfrage` (timestamp)
- `Naechste Portal-Abfrage` (timestamp)

Health sensor:

- `Portal-Abfrage Problem` (binary sensor)
  - `ON` means latest portal query failed
  - `OFF` means latest portal query succeeded
  - Icon switches dynamically:
    - healthy: `mdi:check-decagram-outline`
    - problem: `mdi:alert-decagram-outline`

## How query success is evaluated

A query is considered successful only if:

- at least one configured energy value is present, and
- `last_update_date` is present and plausible in format `DD.MM.YYYY`

If validation fails, the query is treated as failed.

## Troubleshooting

- Check add-on logs first.
- Verify `SUPERVISOR_TOKEN present: true` is logged at startup.
- Verify MQTT connection logs (`MQTT broker connection acknowledged`).
- If no entities appear, confirm MQTT integration is enabled in Home Assistant.
- If portal fails repeatedly, check credentials and whether Brunata selectors
  still match the current portal UI.

## Development notes

- Runtime behavior is implemented in `brunata_fetcher/server.py`.
- Scraping logic is in `brunata_fetcher/_brunata_scraper.py`.
- Local smoke checks: `python3 brunata_fetcher/smoke_local.py`
- Release history: `brunata_fetcher/CHANGELOG.md`
- Session handover and archived context:
  - `docs/SESSION_HANDOVER.md`
  - `docs/MEMORIES_ARCHIVE.md`
