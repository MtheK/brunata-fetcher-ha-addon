# Changelog

## 0.2.0

- Added Supervisor MQTT service discovery with fallback to manual/default settings
- Moved MQTT and scraper URL settings into `advanced` options
- Improved startup reliability by waiting for MQTT connection acknowledgment before publishing
- Added portal query health monitoring via `binary_sensor` (`device_class: problem`)
- Added persistent notification on failed portal queries

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
