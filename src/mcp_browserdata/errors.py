"""Errors surfaced to tool callers as readable messages."""

from __future__ import annotations


class BrowserDataError(RuntimeError):
    """Base for all user-facing errors."""


class BrowserRunningError(BrowserDataError):
    def __init__(self, browser: str, what: str) -> None:
        super().__init__(
            f"{what} requires {browser} to be quit "
            f"(e.g. osascript -e 'quit app \"{browser}\"'); live access is not available."
        )


class NeedsFullDiskAccessError(BrowserDataError):
    def __init__(self, path: str) -> None:
        super().__init__(
            f"macOS denied access to {path}. Grant Full Disk Access to the app "
            "hosting this MCP server (System Settings → Privacy & Security → "
            "Full Disk Access), then retry."
        )


class CdpUnavailableError(BrowserDataError):
    pass


class UnsupportedKindError(BrowserDataError):
    def __init__(self, browser: str, kind: str, direction: str = "access") -> None:
        super().__init__(f"{browser} does not support {direction} of '{kind}' data.")


class BrowserNotFoundError(BrowserDataError):
    pass
