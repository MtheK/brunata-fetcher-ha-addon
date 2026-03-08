#!/usr/bin/env python3
"""Standalone Brunata portal scraper, invoked as a subprocess by HA.

Reads a JSON config from stdin, scrapes the Brunata portal using Playwright,
and writes the result as JSON to stdout.

Output on success:
    {"status": "ok", "data": {"Heizung": 2150.0, "last_update_date": "28.02.2026"}}
Output on error:
    {"status": "error", "type": "login"|"scraping"|"config", "message": "..."}
"""

from __future__ import annotations

import asyncio
import json
import re
import sys


def _parse_german_number(text: str) -> float:
    if not text:
        raise ValueError("Text is empty")
    normalized = re.sub(
        r"\s*(kWh|m\xb3|m\xb3\/h|Liter|L|l)\s*$", "", text, flags=re.IGNORECASE
    ).strip()
    as_number = normalized.replace(".", "").replace(",", ".")
    try:
        return float(as_number)
    except ValueError as ex:
        raise ValueError(f"Could not parse '{text}' as number") from ex


async def scrape(config: dict) -> dict:
    from playwright.async_api import async_playwright

    email = config["email"]
    password = config["password"]
    energy_types = config["energy_types"]
    login_url = config["login_url"]
    sel_email = config["selector_email"]
    sel_password = config["selector_password"]
    sel_login = config["selector_login_button"]
    sel_date = config["selector_date"]
    sel_value = config["selector_value"]
    timeout_before = config.get("timeout_before_login", 1000)
    timeout_after = config.get("timeout_after_login", 2000)
    timeout_clicks = config.get("timeout_between_clicks", 2000)
    pw_timeout = config.get("playwright_timeout", 30000)
    headless = config.get("headless", True)
    energy_type_labels = config.get("energy_type_labels", {})

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(pw_timeout)
        try:
            await page.goto(login_url, wait_until="networkidle")
            await page.wait_for_timeout(timeout_before)
            await page.fill(sel_email, email)
            await page.fill(sel_password, password)
            await page.wait_for_timeout(timeout_before)
            await page.click(sel_login)
            try:
                await page.wait_for_load_state("networkidle")
            except Exception:
                pass
            await page.wait_for_timeout(500)

            # Detect login failure
            page_text = await page.text_content("body") or ""
            if any(
                w in page_text.lower()
                for w in ["ungültig", "invalid", "fehler", "error", "incorrect"]
            ):
                current_url = page.url
                if "anmeldung" in current_url or "login" in current_url.lower():
                    raise RuntimeError("LOGIN_FAILED")

            await page.wait_for_timeout(timeout_after)

            consumption: dict = {"last_update_date": None}
            await page.wait_for_timeout(timeout_clicks)

            for energy_type in energy_types:
                label = energy_type_labels.get(energy_type, energy_type)
                clicked = False
                for btn_sel in [
                    f'button:has-text("{energy_type}")',
                    f'button:has-text("{label}")',
                ]:
                    try:
                        await page.click(btn_sel, timeout=5000)
                        clicked = True
                        break
                    except Exception:
                        continue

                if not clicked:
                    consumption[energy_type] = None
                    continue

                await page.wait_for_timeout(timeout_clicks)

                if consumption["last_update_date"] is None:
                    raw_date = await page.text_content(sel_date)
                    if raw_date:
                        candidate = raw_date.strip()
                        if candidate and candidate != "--":
                            consumption["last_update_date"] = candidate

                value_text = await page.text_content(sel_value)
                if not value_text:
                    consumption[energy_type] = None
                    continue
                try:
                    consumption[energy_type] = _parse_german_number(value_text.strip())
                except ValueError:
                    consumption[energy_type] = None

        finally:
            await page.close()
            await context.close()
            await browser.close()

    return consumption


def main() -> None:
    try:
        config = json.loads(sys.stdin.read())
    except Exception as ex:
        print(json.dumps({"status": "error", "type": "config", "message": str(ex)}))
        sys.exit(1)

    try:
        result = asyncio.run(scrape(config))
        print(json.dumps({"status": "ok", "data": result}))
    except RuntimeError as ex:
        if "LOGIN_FAILED" in str(ex):
            print(json.dumps({
                "status": "error",
                "type": "login",
                "message": "Login failed: invalid credentials",
            }))
        else:
            print(json.dumps({"status": "error", "type": "scraping", "message": str(ex)}))
        sys.exit(1)
    except Exception as ex:
        print(json.dumps({"status": "error", "type": "scraping", "message": str(ex)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
