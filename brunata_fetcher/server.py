"""Brunata Fetcher add-on — main server.

Reads /data/options.json (injected by HAOS supervisor), scrapes the Brunata
Nutzerportal via Playwright, and publishes results as MQTT Discovery sensors.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

import paho.mqtt.client as mqtt

from _brunata_scraper import scrape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
_LOGGER = logging.getLogger("brunata_fetcher")

# --- Brunata portal constants ------------------------------------------------

_BRUNATA_LOGIN_URL = (
    "https://nutzerportal.brunata-muenchen.de/np_anmeldung/index.html?sap-language=DE"
)
_SELECTOR_EMAIL = "#__component0---Start--idEmailInput-inner"
_SELECTOR_PASSWORD = "#__component0---Start--idPassword-inner"
_SELECTOR_LOGIN_BUTTON = 'button:has-text("Anmelden")'
_SELECTOR_DATE = "#__xmlview1--idConsumptionDate-inner"
_SELECTOR_VALUE = "#__xmlview1--idConsumptionValue-inner"

_ENERGY_TYPES: dict[str, dict] = {
    "Heizung": {
        "unit": "kWh",
        "label": "Heizung in kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
    },
    "Kaltwasser": {
        "unit": "m³",
        "label": "Kaltwasser in m³",
        "device_class": "water",
        "state_class": "total_increasing",
    },
    "Warmwasser": {
        "unit": "kWh",
        "label": "Warmwasser in kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
    },
}

_DEVICE_INFO = {
    "identifiers": ["brunata_fetcher"],
    "name": "BRUdirekt",
    "manufacturer": "BRUNATA-METRONA",
    "model": "Nutzerportal Scraper",
}

_OPTIONS_FILE = "/data/options.json"


# --- MQTT helpers ------------------------------------------------------------


def _connect_mqtt(host: str, port: int, user: str, password: str) -> mqtt.Client:
    """Connect to MQTT broker and return a started client."""
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="brunata_fetcher"
    )
    if user:
        client.username_pw_set(user, password)
    client.connect(host, port, keepalive=60)
    client.loop_start()
    return client


def _publish_discovery(client: mqtt.Client, energy_types: list[str]) -> None:
    """Publish retained MQTT Discovery config messages for all sensors."""
    for energy_type in energy_types:
        cfg = _ENERGY_TYPES.get(energy_type)
        if cfg is None:
            _LOGGER.warning("Unknown energy type '%s' — skipping", energy_type)
            continue

        slug = energy_type.lower().replace(" ", "_")
        payload = {
            "name": energy_type,
            "unique_id": f"brunata_fetcher_{slug}",
            "state_topic": f"brunata_fetcher/sensor/{slug}/state",
            "unit_of_measurement": cfg["unit"],
            "device_class": cfg["device_class"],
            "state_class": cfg["state_class"],
            "device": _DEVICE_INFO,
        }
        client.publish(
            f"homeassistant/sensor/brunata_fetcher_{slug}/config",
            json.dumps(payload),
            retain=True,
        )
        _LOGGER.info("Published discovery config for %s", energy_type)

    # Extra sensor: date of last portal update
    client.publish(
        "homeassistant/sensor/brunata_fetcher_last_update/config",
        json.dumps({
            "name": "Letztes Update",
            "unique_id": "brunata_fetcher_last_update",
            "state_topic": "brunata_fetcher/sensor/last_update/state",
            "icon": "mdi:calendar-check",
            "device": _DEVICE_INFO,
        }),
        retain=True,
    )
    _LOGGER.info("Published discovery config for Letztes Update")


def _publish_state(
    client: mqtt.Client, data: dict, energy_types: list[str]
) -> None:
    """Publish current sensor states."""
    for energy_type in energy_types:
        value = data.get(energy_type)
        if value is None:
            continue
        slug = energy_type.lower().replace(" ", "_")
        client.publish(
            f"brunata_fetcher/sensor/{slug}/state", str(value), retain=True
        )
        _LOGGER.info("State: %s = %s", energy_type, value)

    last_update = data.get("last_update_date")
    if last_update:
        client.publish(
            "brunata_fetcher/sensor/last_update/state", last_update, retain=True
        )
        _LOGGER.info("State: last_update_date = %s", last_update)


# --- Scraper -----------------------------------------------------------------


async def _run_scrape(options: dict) -> dict | None:
    """Build scraper config from add-on options and call the scraper."""
    config = {
        "email": options["email"],
        "password": options["password"],
        "energy_types": options["energy_types"],
        "login_url": _BRUNATA_LOGIN_URL,
        "selector_email": _SELECTOR_EMAIL,
        "selector_password": _SELECTOR_PASSWORD,
        "selector_login_button": _SELECTOR_LOGIN_BUTTON,
        "selector_date": _SELECTOR_DATE,
        "selector_value": _SELECTOR_VALUE,
        "timeout_before_login": 1000,
        "timeout_after_login": 2000,
        "timeout_between_clicks": 2000,
        "playwright_timeout": 30000,
        "headless": True,
        "energy_type_labels": {k: v["label"] for k, v in _ENERGY_TYPES.items()},
    }
    try:
        return await scrape(config)
    except RuntimeError as ex:
        if "LOGIN_FAILED" in str(ex):
            _LOGGER.error("Login failed — check email and password in add-on options")
        else:
            _LOGGER.error("Scraping error: %s", ex)
    except Exception as ex:
        _LOGGER.exception("Unexpected error during scraping: %s", ex)
    return None


# --- Main loop ---------------------------------------------------------------


async def main() -> None:
    """Load options, connect MQTT and run the polling loop."""
    with open(_OPTIONS_FILE) as fh:
        options = json.load(fh)

    energy_types: list[str] = options["energy_types"]
    scan_interval: int = int(options.get("scan_interval_hours", 24)) * 3600

    _LOGGER.info(
        "Starting — energy_types=%s, interval=%dh",
        energy_types,
        options.get("scan_interval_hours", 24),
    )

    mqtt_client = _connect_mqtt(
        options["mqtt_host"],
        int(options["mqtt_port"]),
        options.get("mqtt_user", ""),
        options.get("mqtt_password", ""),
    )

    _publish_discovery(mqtt_client, energy_types)

    while True:
        _LOGGER.info("Starting scrape...")
        data = await _run_scrape(options)
        if data is not None:
            _publish_state(mqtt_client, data, energy_types)
            _LOGGER.info("Scrape complete")
        else:
            _LOGGER.warning("Scrape returned no data — will retry after interval")

        _LOGGER.info("Next scrape in %d seconds", scan_interval)
        await asyncio.sleep(scan_interval)


if __name__ == "__main__":
    asyncio.run(main())
