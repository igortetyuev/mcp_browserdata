"""Browser driver registry."""

from __future__ import annotations

from mcp_browserdata.drivers.base import BrowserDriver
from mcp_browserdata.drivers.chromium import CHROMIUM_BROWSERS, ChromiumDriver
from mcp_browserdata.drivers.obscura import ObscuraDriver
from mcp_browserdata.drivers.safari import SafariDriver
from mcp_browserdata.errors import BrowserNotFoundError


def all_drivers() -> dict[str, BrowserDriver]:
    drivers: dict[str, BrowserDriver] = {
        name: ChromiumDriver(spec, name=name) for name, spec in CHROMIUM_BROWSERS.items()
    }
    drivers["safari"] = SafariDriver()
    drivers["obscura"] = ObscuraDriver()
    return drivers


def get_driver(name: str) -> BrowserDriver:
    drivers = all_drivers()
    try:
        return drivers[name.lower()]
    except KeyError:
        raise BrowserNotFoundError(
            f"unknown browser '{name}'; known: {', '.join(sorted(drivers))}"
        ) from None
