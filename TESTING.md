# Testing guide

This document defines the first practical test path for the add-on.

## Scope

- Startup stability in Home Assistant Supervisor
- MQTT Discovery publication
- Real Brunata scrape and state updates
- Optional local smoke check without external services

## 1. Local smoke check (quick)

Run from `brunata_fetcher/`:

```bash
python3 smoke_local.py
```

Expected output:

```text
Smoke test passed: parser and MQTT payload generation look good
```

What this validates:

- Discovery topics and payload shape are generated
- State topics are generated
- German number parser handles typical values like `1.234,56` and `13,25 m3`

## 2. Supervisor test (real end-to-end)

Configure add-on options in Home Assistant:

- `email`: Brunata portal email
- `password`: Brunata portal password
- `energy_types`: select with checkboxes (`Heizung`, `Kaltwasser`, `Warmwasser`)
- `mqtt_host`: usually `core-mosquitto`
- `mqtt_port`: usually `1883`
- `mqtt_user`, `mqtt_password`: your broker credentials
- `scan_interval_hours`: use `1` for initial testing, then restore to `24`

Start the add-on and check logs for:

- MQTT connection success
- Discovery publish logs for configured energy types
- Scrape start and completion logs

## 3. MQTT topic verification

Verify discovery topics exist:

- `homeassistant/sensor/brunata_fetcher/*/config`

Verify state topics are updated:

- `brunata_fetcher/sensor/*/state`

Expected sensor units:

- `Heizung`: `kWh`
- `Kaltwasser`: `m3`
- `Warmwasser`: `kWh`

## 4. Home Assistant entity verification

In Home Assistant, confirm:

- `Letzte Portal-Abfrage` is updated each run as timestamp
- `Naechste Portal-Abfrage` shows the planned next run timestamp

Display precision expectations:

- `Heizung`: no decimal places
- `Warmwasser`: no decimal places
- `Kaltwasser`: one decimal place

## 5. Failure triage

If login fails:

- Re-check add-on `email` and `password`
- Look for `LOGIN_FAILED` indicators in logs

If scraping fails:

- Re-check selectors in `brunata_fetcher/_brunata_scraper.py`
- Portal UI changes are the most likely breakage source

If MQTT fails:

- Re-check broker host/port/user/password
- Confirm broker availability and HA MQTT integration setup
