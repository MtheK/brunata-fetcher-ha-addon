"""Brunata Fetcher add-on — main server.

Reads /data/options.json (injected by HAOS supervisor), scrapes the Brunata
Nutzerportal via Playwright, and publishes results as MQTT Discovery sensors.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import logging
import sys
import time

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
        "suggested_display_precision": 0,
    },
    "Kaltwasser": {
        "unit": "m³",
        "label": "Kaltwasser in m³",
        "device_class": "water",
        "state_class": "total_increasing",
        "suggested_display_precision": 1,
    },
    "Warmwasser": {
        "unit": "kWh",
        "label": "Warmwasser in kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
        "suggested_display_precision": 0,
    },
}

_DEVICE_INFO = {
    "identifiers": ["brunata_fetcher"],
    "name": "BRUdirekt",
    "manufacturer": "BRUNATA-METRONA",
    "model": "Nutzerportal Scraper",
}

_OPTIONS_FILE = "/data/options.json"
_DISCOVERY_NODE = "brunata_fetcher"


# --- MQTT helpers ------------------------------------------------------------


def _connect_mqtt(host: str, port: int, user: str, password: str) -> mqtt.Client:
    """Connect to MQTT broker and return a started client."""
    _LOGGER.info(
        "MQTT connect start: host=%s port=%s user_set=%s", host, port, bool(user)
    )
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="brunata_fetcher")
    if user:
        client.username_pw_set(user, password)
    client.connect(host, port, keepalive=60)
    client.loop_start()
    _LOGGER.info("MQTT connect done")
    return client


def _discovery_topic(object_id: str) -> str:
    """Build grouped MQTT discovery topic for this add-on."""
    return f"homeassistant/sensor/{_DISCOVERY_NODE}/{object_id}/config"


def _publish_discovery(client: mqtt.Client, energy_types: list[str]) -> None:
    """Publish retained MQTT Discovery config messages for all sensors."""
    _LOGGER.info("Discovery publish start: %d energy types", len(energy_types))
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
            "suggested_display_precision": cfg["suggested_display_precision"],
            "device": _DEVICE_INFO,
        }
        client.publish(
            _discovery_topic(slug),
            json.dumps(payload),
            retain=True,
        )
        _LOGGER.info("Published discovery config for %s", energy_type)

    # Extra sensor: date of last portal update
    client.publish(
        _discovery_topic("last_update"),
        json.dumps(
            {
                "name": "Letztes Update",
                "unique_id": "brunata_fetcher_last_update",
                "state_topic": "brunata_fetcher/sensor/last_update/state",
                "icon": "mdi:calendar-check",
                "device": _DEVICE_INFO,
            }
        ),
        retain=True,
    )
    _LOGGER.info("Published discovery config for Letztes Update")

    client.publish(
        _discovery_topic("last_portal_query"),
        json.dumps(
            {
                "name": "Letzte Portal-Abfrage",
                "unique_id": "brunata_fetcher_last_portal_query",
                "state_topic": "brunata_fetcher/sensor/last_portal_query/state",
                "device_class": "timestamp",
                "icon": "mdi:clock-check-outline",
                "device": _DEVICE_INFO,
            }
        ),
        retain=True,
    )
    _LOGGER.info("Published discovery config for Letzte Portal-Abfrage")

    client.publish(
        _discovery_topic("next_portal_query"),
        json.dumps(
            {
                "name": "Naechste Portal-Abfrage",
                "unique_id": "brunata_fetcher_next_portal_query",
                "state_topic": "brunata_fetcher/sensor/next_portal_query/state",
                "device_class": "timestamp",
                "icon": "mdi:clock-outline",
                "device": _DEVICE_INFO,
            }
        ),
        retain=True,
    )
    _LOGGER.info("Published discovery config for Naechste Portal-Abfrage")
    _LOGGER.info("Discovery publish done")


def _publish_state(client: mqtt.Client, data: dict, energy_types: list[str]) -> None:
    """Publish current sensor states."""
    _LOGGER.info("State publish start")
    for energy_type in energy_types:
        value = data.get(energy_type)
        if value is None:
            continue
        slug = energy_type.lower().replace(" ", "_")
        client.publish(f"brunata_fetcher/sensor/{slug}/state", str(value), retain=True)
        _LOGGER.info("State: %s = %s", energy_type, value)
        _LOGGER.debug("State topic published: brunata_fetcher/sensor/%s/state", slug)

    last_update = data.get("last_update_date")
    if last_update:
        client.publish(
            "brunata_fetcher/sensor/last_update/state", last_update, retain=True
        )
        _LOGGER.info("State: last_update_date = %s", last_update)
    _LOGGER.info("State publish done")


def _publish_schedule_state(
    client: mqtt.Client, last_run: datetime, next_run: datetime
) -> None:
    """Publish timestamps for last and next planned portal query."""
    last_iso = last_run.isoformat()
    next_iso = next_run.isoformat()

    client.publish(
        "brunata_fetcher/sensor/last_portal_query/state",
        last_iso,
        retain=True,
    )
    client.publish(
        "brunata_fetcher/sensor/next_portal_query/state",
        next_iso,
        retain=True,
    )
    _LOGGER.info("State: last_portal_query = %s", last_iso)
    _LOGGER.info("State: next_portal_query = %s", next_iso)


# --- Scraper -----------------------------------------------------------------


async def _run_scrape(options: dict) -> dict | None:
    """Build scraper config from add-on options and call the scraper."""
    start = time.monotonic()
    _LOGGER.info("Scrape run config build start")
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
    _LOGGER.info(
        "Scrape run start: energy_types=%s playwright_timeout_ms=%s",
        config["energy_types"],
        config["playwright_timeout"],
    )
    try:
        result = await scrape(config)
        duration = time.monotonic() - start
        _LOGGER.info("Scrape run succeeded in %.2fs", duration)
        return result
    except RuntimeError as ex:
        duration = time.monotonic() - start
        if "LOGIN_FAILED" in str(ex):
            _LOGGER.error(
                "Login failed after %.2fs — check email and password in add-on options",
                duration,
            )
        else:
            _LOGGER.error("Scraping error after %.2fs: %s", duration, ex)
    except Exception as ex:
        duration = time.monotonic() - start
        _LOGGER.exception(
            "Unexpected error during scraping after %.2fs: %s", duration, ex
        )
    return None


# --- Main loop ---------------------------------------------------------------


async def main() -> None:
    """Load options, connect MQTT and run the polling loop."""
    _LOGGER.info("Server startup: loading options from %s", _OPTIONS_FILE)
    with open(_OPTIONS_FILE, encoding="utf-8") as fh:
        options = json.load(fh)
    _LOGGER.info("Options loaded successfully")

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

    cycle = 0
    while True:
        cycle += 1
        cycle_start = time.monotonic()
        run_started_at = datetime.now(UTC)
        _LOGGER.info("Cycle %d starting scrape", cycle)
        data = await _run_scrape(options)
        if data is not None:
            _publish_state(mqtt_client, data, energy_types)
            _LOGGER.info("Cycle %d scrape complete", cycle)
        else:
            _LOGGER.warning(
                "Cycle %d scrape returned no data — will retry after interval", cycle
            )

        cycle_duration = time.monotonic() - cycle_start
        next_run_at = datetime.now(UTC) + timedelta(seconds=scan_interval)
        _publish_schedule_state(mqtt_client, run_started_at, next_run_at)
        _LOGGER.info("Cycle %d finished in %.2fs", cycle, cycle_duration)
        _LOGGER.info("Next scrape in %d seconds", scan_interval)
        await asyncio.sleep(scan_interval)


if __name__ == "__main__":
    asyncio.run(main())
