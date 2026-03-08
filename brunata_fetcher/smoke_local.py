#!/usr/bin/env python3
"""Local smoke checks for Brunata add-on publishing and parsing.

This script validates two core behaviors without requiring a real MQTT broker
or Brunata login:
1. MQTT Discovery and state payload/topic generation
2. German number parsing for common portal formats

Run from this directory:
    python3 smoke_local.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from _brunata_scraper import _parse_german_number
from server import (
    _clear_removed_energy_type_entities,
    _publish_discovery,
    _publish_schedule_state,
    _publish_state,
)


class CapturingMqttClient:
    """Minimal MQTT client test double for publish capture."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str, bool]] = []

    class _Info:
        def __init__(self) -> None:
            self.rc = 0

        def wait_for_publish(self) -> None:
            return

    def publish(
        self,
        topic: str,
        payload: str,
        qos: int = 0,
        retain: bool = False,
    ) -> _Info:
        """Capture publish calls in-memory."""
        _ = qos
        self.published.append((topic, payload, retain))
        return self._Info()


def _assert_parser() -> None:
    """Validate German number parsing behavior."""
    cases = {
        "1.234,56": 1234.56,
        "2.150,0 kWh": 2150.0,
        "13,25 m³": 13.25,
        "0,5": 0.5,
    }
    for raw, expected in cases.items():
        value = _parse_german_number(raw)
        if value != expected:
            raise AssertionError(f"Parser mismatch for '{raw}': {value} != {expected}")


def _assert_discovery_and_state() -> None:
    """Validate discovery/state topic and payload shape."""
    client = CapturingMqttClient()

    energy_types = ["Heizung", "Kaltwasser"]
    _publish_discovery(client, energy_types)
    _clear_removed_energy_type_entities(client, energy_types)
    _publish_state(
        client,
        {
            "Heizung": 2150.0,
            "Kaltwasser": 12.5,
            "last_update_date": "28.02.2026",
        },
        energy_types,
    )
    _publish_schedule_state(
        client,
        datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        datetime(2026, 3, 2, 10, 0, tzinfo=UTC) + timedelta(minutes=1),
    )

    topics = [topic for topic, _, _ in client.published]
    expected_topics = {
        "homeassistant/sensor/brunata_fetcher/heizung/config",
        "homeassistant/sensor/brunata_fetcher/kaltwasser/config",
        "homeassistant/sensor/brunata_fetcher/warmwasser/config",
        "homeassistant/sensor/brunata_fetcher/last_update/config",
        "homeassistant/sensor/brunata_fetcher/last_portal_query/config",
        "homeassistant/sensor/brunata_fetcher/next_portal_query/config",
        "brunata_fetcher/sensor/heizung/state",
        "brunata_fetcher/sensor/kaltwasser/state",
        "brunata_fetcher/sensor/warmwasser/state",
        "brunata_fetcher/sensor/last_update/state",
        "brunata_fetcher/sensor/last_portal_query/state",
        "brunata_fetcher/sensor/next_portal_query/state",
    }

    missing = expected_topics - set(topics)
    if missing:
        raise AssertionError(f"Missing expected MQTT topics: {sorted(missing)}")

    discovery_payload = next(
        payload
        for topic, payload, _ in client.published
        if topic == "homeassistant/sensor/brunata_fetcher/heizung/config"
    )
    discovery = json.loads(discovery_payload)
    if discovery["state_topic"] != "brunata_fetcher/sensor/heizung/state":
        raise AssertionError("Unexpected state_topic in Heizung discovery payload")
    if discovery["unit_of_measurement"] != "kWh":
        raise AssertionError("Unexpected unit_of_measurement in Heizung payload")
    if discovery["suggested_display_precision"] != 0:
        raise AssertionError(
            "Unexpected suggested_display_precision in Heizung payload"
        )

    cold_water_payload = next(
        payload
        for topic, payload, _ in client.published
        if topic == "homeassistant/sensor/brunata_fetcher/kaltwasser/config"
    )
    cold_water_discovery = json.loads(cold_water_payload)
    if cold_water_discovery["suggested_display_precision"] != 1:
        raise AssertionError(
            "Unexpected suggested_display_precision in Kaltwasser payload"
        )

    if not all(retain for _, _, retain in client.published):
        raise AssertionError("All publish calls must be retained for this smoke test")


def main() -> None:
    """Run local smoke checks and print a short result."""
    _assert_parser()
    _assert_discovery_and_state()
    print("Smoke test passed: parser and MQTT payload generation look good")


if __name__ == "__main__":
    main()
