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
import logging
import re
import sys
import time


_LOGGER = logging.getLogger("brunata_fetcher.scraper")


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

    start = time.monotonic()
    _LOGGER.info("Scraper entry")

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
    masked_email = f"***{email[-4:]}" if len(email) >= 4 else "***"
    _LOGGER.info(
        "Scraper config loaded: user=%s energy_types=%s headless=%s timeout_ms=%s",
        masked_email,
        energy_types,
        headless,
        pw_timeout,
    )

    # Delete Playwright browser user data directory for a clean session
    import shutil
    from pathlib import Path

    user_data_dir = Path("/tmp/playwright_user_data")
    if user_data_dir.exists():
        try:
            shutil.rmtree(user_data_dir)
            _LOGGER.info("Deleted browser user data directory: %s", user_data_dir)
        except Exception as ex:
            _LOGGER.warning("Failed to delete browser user data directory: %s", ex)

    async with async_playwright() as pw:
        _LOGGER.info("Playwright start")
        # browser = await pw.chromium.launch(headless=headless)
        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-accelerated-2d-canvas",
                "--disable-accelerated-video-decode",
                "--disable-accelerated-mjpeg-decode",
                "--disable-accelerated-video-encode",
                "--disable-extensions",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--disable-breakpad",
                "--disable-client-side-phishing-detection",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-features=site-per-process",
                "--disable-hang-monitor",
                "--disable-infobars",
                "--disable-popup-blocking",
                "--disable-prompt-on-repost",
                "--disable-sync",
                "--metrics-recording-only",
                "--mute-audio",
                "--no-first-run",
                "--safebrowsing-disable-auto-update",
                "--enable-automation",
                "--password-store=basic",
                "--use-mock-keychain",
                "--single-process",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        _LOGGER.info("Browser launched")
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(pw_timeout)
        try:
            _LOGGER.info("Open login page")
            await page.goto(login_url, wait_until="domcontentloaded")
            # Dump HTML for debugging
            try:
                html = await page.content()
                with open("/tmp/portal_debug1.html", "w", encoding="utf-8") as f:
                    f.write(html)
                _LOGGER.info("Wrote portal_debug1.html for troubleshooting")
            except Exception as ex:
                _LOGGER.warning("Failed to write portal_debug1.html: %s", ex)

            await page.wait_for_selector(sel_email, timeout=30000)
            _LOGGER.info("Login page loaded and email selector found")

            # Dump HTML and screenshot for debugging
            try:
                html = await page.content()
                with open("/tmp/portal_debug2.html", "w", encoding="utf-8") as f:
                    f.write(html)
                await page.screenshot(path="/tmp/portal_debug2.png")
                _LOGGER.info(
                    "Wrote portal_debug2.html and portal_debug2.png for troubleshooting"
                )
            except Exception as ex:
                _LOGGER.warning(
                    "Failed to write portal_debug2.html or screenshot: %s", ex
                )

            await page.wait_for_timeout(timeout_before)
            await page.fill(sel_email, email)
            await page.fill(sel_password, password)

            _LOGGER.info("Credentials filled")
            await page.screenshot(path="/tmp/portal_debug3.png")
            _LOGGER.info("Wrote portal_debug3.png for troubleshooting")

            await page.wait_for_timeout(timeout_before)
            await page.click(sel_login)
            _LOGGER.info("Login button clicked")
            try:
                await page.wait_for_load_state("domcontentloaded")
            except Exception:
                _LOGGER.warning(
                    "wait_for_load_state(networkidle) timed out after login click"
                )
            await page.wait_for_timeout(500)
            _LOGGER.info("Post-login wait complete")

            await page.screenshot(path="/tmp/portal_debug4.png")
            _LOGGER.info("Wrote portal_debug4.png for troubleshooting")

            # Detect login failure
            page_text = await page.text_content("body") or ""
            if any(
                w in page_text.lower()
                for w in ["ungültig", "invalid", "fehler", "error", "incorrect"]
            ):
                current_url = page.url
                if "anmeldung" in current_url or "login" in current_url.lower():
                    _LOGGER.error("Login failure detected via page text/url")
                    raise RuntimeError("LOGIN_FAILED")
            _LOGGER.info("No immediate login failure detected")

            await page.wait_for_timeout(timeout_after)
            _LOGGER.info("After-login settle wait complete")

            await page.screenshot(path="/tmp/portal_debug5.png")
            _LOGGER.info("Wrote portal_debug5.png for troubleshooting")

            consumption: dict = {"last_update_date": None}
            await page.wait_for_timeout(timeout_clicks)
            _LOGGER.info("Starting energy type extraction")

            for energy_type in energy_types:
                _LOGGER.info("Energy extraction start: %s", energy_type)
                label = energy_type_labels.get(energy_type, energy_type)
                clicked = False
                for btn_sel in [
                    f'button:has-text("{energy_type}")',
                    f'button:has-text("{label}")',
                ]:
                    try:
                        _LOGGER.debug(
                            "Trying selector for %s: %s", energy_type, btn_sel
                        )
                        await page.click(btn_sel, timeout=5000)
                        clicked = True
                        _LOGGER.info(
                            "Selector click success for %s: %s", energy_type, btn_sel
                        )
                        break
                    except Exception:
                        _LOGGER.debug(
                            "Selector click failed for %s: %s",
                            energy_type,
                            btn_sel,
                        )
                        continue

                if not clicked:
                    _LOGGER.warning(
                        "No selector matched for energy type: %s", energy_type
                    )
                    consumption[energy_type] = None
                    continue

                await page.wait_for_timeout(timeout_clicks)
                _LOGGER.info("Post-click wait complete for %s", energy_type)

                if consumption["last_update_date"] is None:
                    raw_date = await page.text_content(sel_date)
                    if raw_date:
                        candidate = raw_date.strip()
                        if candidate and candidate != "--":
                            consumption["last_update_date"] = candidate
                            _LOGGER.info("Detected last_update_date=%s", candidate)

                value_text = await page.text_content(sel_value)
                if not value_text:
                    _LOGGER.warning("No value text found for %s", energy_type)
                    consumption[energy_type] = None
                    continue
                try:
                    consumption[energy_type] = _parse_german_number(value_text.strip())
                    _LOGGER.info(
                        "Parsed %s value=%s", energy_type, consumption[energy_type]
                    )
                except ValueError:
                    _LOGGER.warning(
                        "Failed to parse value for %s: %s", energy_type, value_text
                    )
                    consumption[energy_type] = None

            _LOGGER.info("Energy extraction finished")

        finally:
            _LOGGER.info("Scraper cleanup start")
            await page.close()
            await context.close()
            await browser.close()
            _LOGGER.info("Scraper cleanup done")

    duration = time.monotonic() - start
    _LOGGER.info("Scraper exit success in %.2fs", duration)

    return consumption


def main() -> None:
    try:
        config = json.loads(sys.stdin.read())
    except Exception as ex:
        _LOGGER.exception("Config decode failed")
        print(json.dumps({"status": "error", "type": "config", "message": str(ex)}))
        sys.exit(1)

    try:
        result = asyncio.run(scrape(config))
        print(json.dumps({"status": "ok", "data": result}))
    except RuntimeError as ex:
        if "LOGIN_FAILED" in str(ex):
            _LOGGER.error("Scraper runtime login error")
            print(
                json.dumps(
                    {
                        "status": "error",
                        "type": "login",
                        "message": "Login failed: invalid credentials",
                    }
                )
            )
        else:
            _LOGGER.exception("Scraper runtime error")
            print(
                json.dumps({"status": "error", "type": "scraping", "message": str(ex)})
            )
        sys.exit(1)
    except Exception as ex:
        _LOGGER.exception("Unhandled scraper exception")
        print(json.dumps({"status": "error", "type": "scraping", "message": str(ex)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
