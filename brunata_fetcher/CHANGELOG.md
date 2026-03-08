# Changelog

## Unreleased

- Test prerelease version on `next`: `0.1.6b8`
- Change `energy_types` configuration to checkbox-style booleans
- Enable all three energy types by default (`Heizung`, `Kaltwasser`, `Warmwasser`)
- Keep backward compatibility for older list/string `energy_types` values
- Move MQTT settings to nested `advanced` options section
- Add configurable `scraper_url` in `advanced` options section
- Add fallback handling for legacy flat MQTT options
- Add Supervisor MQTT service discovery for automatic credentials/host fallback
- Fix auto-discovery precedence by keeping default advanced MQTT host/port empty
- Fix add-on options validation: keep `advanced.mqtt_port` as a valid port value
- Wait for MQTT CONNACK before first publish to avoid startup race crashes
- Guard publish path when MQTT client is disconnected
- Start via `/usr/bin/with-contenv bashio` so `SUPERVISOR_TOKEN` is available at runtime
- Fix MQTT `on_connect` callback success check for Paho `ReasonCode` objects
- Add binary sensor for last portal-query success status
- Send Home Assistant persistent notification when a portal query fails
- Switch status sensor to `device_class: problem` (`ON` on failed query, `OFF` on success)
- Treat portal query as successful only when at least one configured energy value
	exists and `last_update_date` is plausible (`DD.MM.YYYY`)

## 0.1.4

- Set all known `energy_types` as default (`Heizung`, `Kaltwasser`, `Warmwasser`)
- Restrict `energy_types` option values to known types in add-on schema
- Add cleanup for disabled energy types by removing retained discovery/state topics

## 0.1.3

- Group Home Assistant discovery topics under `homeassistant/sensor/brunata_fetcher/*/config`
- Add per-type `suggested_display_precision` metadata
- Add timestamp entities for last and next planned portal query
- Improve publish reliability with retained MQTT publish helper and broker acknowledgement

## 0.1.2

- Add detailed runtime logging for startup, MQTT, scraping, and publish flow
- Harden add-on option schema (`email`, `password`, `port`, optional MQTT credentials)

## 0.1.1

- Switch to Home Assistant Debian base images for stable Playwright runtime
- Fix build configuration to use valid Home Assistant `build_from` image references

## 0.1.0

- Initial add-on implementation
- Brunata portal scraper via Playwright
- MQTT discovery and state publishing for Brunata sensors
