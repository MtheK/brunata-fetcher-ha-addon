"""Brunata Fetcher add-on — main server.

Reads /data/options.json (injected by HAOS supervisor), scrapes the Brunata
Nutzerportal via Playwright, and publishes results as MQTT Discovery sensors.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import logging
import os
import sys
import time
from urllib import error as urlerror
from urllib import request as urlrequest

import paho.mqtt.client as mqtt

from _brunata_scraper import scrape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
_LOGGER = logging.getLogger("brunata_fetcher")

# --- Brunata portal constants ------------------------------------------------

_DEFAULT_BRUNATA_LOGIN_URL = (
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


def _publish_mqtt(
    client: mqtt.Client,
    topic: str,
    payload: str,
    *,
    retain: bool = True,
    qos: int = 1,
) -> None:
    """Publish MQTT message and wait for broker acknowledgment."""
    info = client.publish(topic, payload, qos=qos, retain=retain)
    info.wait_for_publish()
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        _LOGGER.error(
            "MQTT publish failed: topic=%s rc=%s retain=%s qos=%s",
            topic,
            info.rc,
            retain,
            qos,
        )
        return
    _LOGGER.debug(
        "MQTT publish ack: topic=%s retain=%s qos=%s",
        topic,
        retain,
        qos,
    )


def _discovery_topic(object_id: str) -> str:
    """Build grouped MQTT discovery topic for this add-on."""
    return f"homeassistant/sensor/{_DISCOVERY_NODE}/{object_id}/config"


def _extract_advanced_options(options: dict) -> dict:
    """Extract advanced options with fallback defaults and legacy compatibility."""
    advanced = options.get("advanced")
    if not isinstance(advanced, dict):
        advanced = {}

    # Keep compatibility with older flat option keys if they still exist.
    mqtt_host = advanced.get("mqtt_host") or options.get("mqtt_host")
    mqtt_port = advanced.get("mqtt_port") or options.get("mqtt_port")
    mqtt_user = advanced.get("mqtt_user") or options.get("mqtt_user")
    mqtt_password = advanced.get("mqtt_password") or options.get("mqtt_password")
    scraper_url = advanced.get("scraper_url") or _DEFAULT_BRUNATA_LOGIN_URL

    return {
        "mqtt_host": mqtt_host,
        "mqtt_port": mqtt_port,
        "mqtt_user": mqtt_user,
        "mqtt_password": mqtt_password,
        "scraper_url": scraper_url,
    }


def _fetch_supervisor_mqtt_service() -> dict | None:
    """Fetch MQTT service details from Supervisor API if available."""
    token = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HASSIO_TOKEN")
    if not token:
        _LOGGER.info("Supervisor token not available; skipping MQTT service discovery")
        return None

    req = urlrequest.Request(
        "http://supervisor/services/mqtt",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as ex:
        body = ""
        try:
            body = ex.read().decode("utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive logging only
            body = "<unavailable>"
        _LOGGER.warning(
            "Supervisor MQTT service discovery failed with HTTP %s: %s",
            ex.code,
            body,
        )
        return None
    except (urlerror.URLError, TimeoutError, json.JSONDecodeError) as ex:
        _LOGGER.warning("Supervisor MQTT service discovery failed: %s", ex)
        return None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        _LOGGER.warning("Supervisor MQTT service response missing data section")
        return None

    _LOGGER.info(
        "Supervisor MQTT service discovered: host=%s port=%s user_set=%s",
        data.get("host"),
        data.get("port"),
        bool(data.get("username") or data.get("user")),
    )
    return data


def _resolve_mqtt_options(advanced: dict) -> dict:
    """Resolve MQTT options with priority: manual > supervisor service > defaults."""
    discovered = _fetch_supervisor_mqtt_service() or {}

    manual_host = (advanced.get("mqtt_host") or "").strip()
    manual_port = advanced.get("mqtt_port")
    manual_user = advanced.get("mqtt_user") or ""
    manual_password = advanced.get("mqtt_password") or ""

    host = manual_host or discovered.get("host") or "core-mosquitto"
    if manual_host:
        # If a manual host is configured, treat port as manual too.
        port_raw = manual_port if manual_port else 1883
    else:
        # Keep service discovery effective when manual host is left empty.
        port_raw = discovered.get("port") or manual_port or 1883
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        _LOGGER.warning("Invalid MQTT port '%s'; using default 1883", port_raw)
        port = 1883

    user = manual_user or discovered.get("username") or discovered.get("user") or ""
    password = (
        manual_password
        or discovered.get("password")
        or discovered.get("pass")
        or ""
    )

    _LOGGER.info(
        "Resolved MQTT settings: host=%s port=%s user_set=%s",
        host,
        port,
        bool(user),
    )

    return {
        "mqtt_host": host,
        "mqtt_port": port,
        "mqtt_user": user,
        "mqtt_password": password,
    }


def _normalize_energy_types(
    configured: dict[str, bool] | list[str] | str | None,
) -> list[str]:
    """Return known energy types in canonical order without duplicates."""
    if configured is None:
        configured = []

    if isinstance(configured, dict):
        normalized = [
            energy_type
            for energy_type in _ENERGY_TYPES
            if bool(configured.get(energy_type, False))
        ]
        if not normalized:
            return list(_ENERGY_TYPES)
        return normalized

    if isinstance(configured, str):
        configured = [configured]

    selected = set(configured)
    normalized = [
        energy_type for energy_type in _ENERGY_TYPES if energy_type in selected
    ]
    if not normalized:
        return list(_ENERGY_TYPES)
    return normalized


def _clear_removed_energy_type_entities(
    client: mqtt.Client, selected_energy_types: list[str]
) -> None:
    """Remove HA entities for disabled energy types via retained empty payloads."""
    disabled = set(_ENERGY_TYPES).difference(selected_energy_types)
    for energy_type in disabled:
        slug = energy_type.lower().replace(" ", "_")
        _publish_mqtt(client, _discovery_topic(slug), "")
        _publish_mqtt(client, f"brunata_fetcher/sensor/{slug}/state", "")
        _LOGGER.info("Removed disabled energy type entity: %s", energy_type)


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
        _publish_mqtt(
            client,
            _discovery_topic(slug),
            json.dumps(payload),
        )
        _LOGGER.info("Published discovery config for %s", energy_type)

    # Extra sensor: date of last portal update
    _publish_mqtt(
        client,
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
    )
    _LOGGER.info("Published discovery config for Letztes Update")

    _publish_mqtt(
        client,
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
    )
    _LOGGER.info("Published discovery config for Letzte Portal-Abfrage")

    _publish_mqtt(
        client,
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
        _publish_mqtt(client, f"brunata_fetcher/sensor/{slug}/state", str(value))
        _LOGGER.info("State: %s = %s", energy_type, value)
        _LOGGER.debug("State topic published: brunata_fetcher/sensor/%s/state", slug)

    last_update = data.get("last_update_date")
    if last_update:
        _publish_mqtt(client, "brunata_fetcher/sensor/last_update/state", last_update)
        _LOGGER.info("State: last_update_date = %s", last_update)
    _LOGGER.info("State publish done")


def _publish_schedule_state(
    client: mqtt.Client, last_run: datetime, next_run: datetime
) -> None:
    """Publish timestamps for last and next planned portal query."""
    last_iso = last_run.isoformat()
    next_iso = next_run.isoformat()

    _publish_mqtt(client, "brunata_fetcher/sensor/last_portal_query/state", last_iso)
    _publish_mqtt(client, "brunata_fetcher/sensor/next_portal_query/state", next_iso)
    _LOGGER.info("State: last_portal_query = %s", last_iso)
    _LOGGER.info("State: next_portal_query = %s", next_iso)


# --- Scraper -----------------------------------------------------------------


async def _run_scrape(options: dict, scraper_url: str) -> dict | None:
    """Build scraper config from add-on options and call the scraper."""
    start = time.monotonic()
    _LOGGER.info("Scrape run config build start")
    config = {
        "email": options["email"],
        "password": options["password"],
        "energy_types": _normalize_energy_types(options.get("energy_types")),
        "login_url": scraper_url,
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

    energy_types: list[str] = _normalize_energy_types(options.get("energy_types"))
    scan_interval: int = int(options.get("scan_interval_hours", 24)) * 3600
    advanced = _extract_advanced_options(options)
    mqtt_options = _resolve_mqtt_options(advanced)

    _LOGGER.info(
        "Starting — energy_types=%s, interval=%dh",
        energy_types,
        options.get("scan_interval_hours", 24),
    )

    mqtt_client = _connect_mqtt(
        mqtt_options["mqtt_host"],
        int(mqtt_options["mqtt_port"]),
        mqtt_options["mqtt_user"],
        mqtt_options["mqtt_password"],
    )

    _publish_discovery(mqtt_client, energy_types)
    _clear_removed_energy_type_entities(mqtt_client, energy_types)

    cycle = 0
    while True:
        cycle += 1
        cycle_start = time.monotonic()
        run_started_at = datetime.now(UTC)
        _LOGGER.info("Cycle %d starting scrape", cycle)
        data = await _run_scrape(options, advanced["scraper_url"])
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
