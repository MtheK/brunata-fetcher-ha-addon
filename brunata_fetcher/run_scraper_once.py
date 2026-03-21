#!/usr/bin/env python3
"""Run the Brunata scraper once with config from a local .env file.

This script is for local development outside Home Assistant add-on runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from _brunata_scraper import scrape

_DEFAULT_LOGIN_URL = (
    "https://nutzerportal.brunata-muenchen.de/np_anmeldung/index.html?sap-language=DE"
)

_DEFAULT_SELECTORS = {
    "selector_email": "#__component0---Start--idEmailInput-inner",
    "selector_password": "#__component0---Start--idPassword-inner",
    "selector_login_button": 'button:has-text("Anmelden")',
    "selector_date": "#__xmlview1--idConsumptionDate-inner",
    "selector_value": "#__xmlview1--idConsumptionValue-inner",
}


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Read KEY=VALUE pairs from a .env file."""
    if not env_path.is_file():
        raise FileNotFoundError(f"Env file not found: {env_path}")

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("export "):
            raw = raw[7:].strip()
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _env_bool(value: str, default: bool) -> bool:
    """Parse boolean-ish env values."""
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_config_from_env(env: dict[str, str]) -> dict:
    """Build scraper config from environment values."""
    email = env.get("BRUNATA_EMAIL", "").strip()
    password = env.get("BRUNATA_PASSWORD", "").strip()
    if not email or not password:
        raise ValueError("Missing BRUNATA_EMAIL or BRUNATA_PASSWORD in env file")

    raw_energy_types = env.get(
        "BRUNATA_ENERGY_TYPES",
        "Heizung,Kaltwasser,Warmwasser",
    )
    energy_types = [
        item.strip() for item in raw_energy_types.split(",") if item.strip()
    ]
    if not energy_types:
        raise ValueError("No energy types configured in BRUNATA_ENERGY_TYPES")

    login_url = env.get("BRUNATA_LOGIN_URL", _DEFAULT_LOGIN_URL).strip()
    headless = _env_bool(env.get("BRUNATA_HEADLESS", "true"), True)
    playwright_timeout = int(env.get("BRUNATA_PLAYWRIGHT_TIMEOUT_MS", "30000"))
    timeout_before = int(env.get("BRUNATA_TIMEOUT_BEFORE_LOGIN_MS", "1000"))
    timeout_after = int(env.get("BRUNATA_TIMEOUT_AFTER_LOGIN_MS", "2000"))
    timeout_between = int(env.get("BRUNATA_TIMEOUT_BETWEEN_CLICKS_MS", "2000"))

    return {
        "email": email,
        "password": password,
        "energy_types": energy_types,
        "login_url": login_url,
        **_DEFAULT_SELECTORS,
        "timeout_before_login": timeout_before,
        "timeout_after_login": timeout_after,
        "timeout_between_clicks": timeout_between,
        "playwright_timeout": playwright_timeout,
        "headless": headless,
        "energy_type_labels": {
            "Heizung": "Heizung in kWh",
            "Kaltwasser": "Kaltwasser in m3",
            "Warmwasser": "Warmwasser in kWh",
        },
    }


def main() -> None:
    """Run a single scraper cycle with .env-based login data."""
    parser = argparse.ArgumentParser(
        description="Run Brunata scraper once outside Home Assistant add-on"
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to env file (default: .env)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    env_path = Path(args.env_file)
    if not env_path.is_absolute():
        env_path = Path.cwd() / env_path

    try:
        env_file_values = _read_env_file(env_path)
        merged_env = {**os.environ, **env_file_values}
        config = _build_config_from_env(merged_env)
    except (FileNotFoundError, OSError, ValueError) as ex:
        print(f"Configuration error: {ex}", file=sys.stderr)
        sys.exit(2)

    try:
        result = asyncio.run(scrape(config))
    except RuntimeError as ex:
        if "LOGIN_FAILED" in str(ex):
            print("Login failed: check BRUNATA_EMAIL/BRUNATA_PASSWORD", file=sys.stderr)
        else:
            print(f"Scraper runtime error: {ex}", file=sys.stderr)
        sys.exit(1)
    except (ModuleNotFoundError, TimeoutError, OSError, ValueError) as ex:
        print(f"Scraper failed: {ex}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
