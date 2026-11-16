"""Export/import a browser's state to a JSON file.

Files are written chmod 600. With redact=True (default for exports meant to
be shared) secret values are replaced with "***" — only metadata survives.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_browserdata.drivers.base import BrowserDriver
from mcp_browserdata.errors import BrowserDataError
from mcp_browserdata.models import (
    ALL_KINDS,
    Bookmark,
    Cookie,
    Credential,
    DataKind,
    SiteStorage,
)

REDACTED = "***"


def _redact_cookie(d: dict) -> dict:
    return {**d, "value": REDACTED}


def _redact_cred(d: dict) -> dict:
    return {**d, "password": REDACTED}


def _redact_storage(d: dict) -> dict:
    return {
        **d,
        "local": {k: REDACTED for k in d["local"]},
        "session": {k: REDACTED for k in d["session"]},
    }


async def export_state(
    driver: BrowserDriver,
    path: Path,
    kinds: list[DataKind] | None = None,
    origins: list[str] | None = None,
    redact: bool = True,
) -> dict[str, Any]:
    kinds = kinds or list(ALL_KINDS)
    data: dict[str, Any] = {
        "version": 1,
        "browser": driver.name,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "kinds": {},
    }
    counts: dict[str, int] = {}
    if "cookies" in kinds:
        cookies = await driver.get_cookies()
        data["kinds"]["cookies"] = [
            _redact_cookie(asdict(c)) if redact else asdict(c) for c in cookies
        ]
        counts["cookies"] = len(cookies)
    if "bookmarks" in kinds:
        bookmarks = await driver.get_bookmarks()
        data["kinds"]["bookmarks"] = [asdict(b) for b in bookmarks]
        counts["bookmarks"] = len(bookmarks)
    if "credentials" in kinds:
        creds = await driver.get_credentials()
        data["kinds"]["credentials"] = [
            _redact_cred(asdict(c)) if redact else asdict(c) for c in creds
        ]
        counts["credentials"] = len(creds)
    if "storage" in kinds and origins:
        storages = [await driver.get_site_storage(o, include_session=True) for o in origins]
        data["kinds"]["storage"] = [
            _redact_storage(asdict(s)) if redact else asdict(s) for s in storages
        ]
        counts["storage"] = len(storages)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return {"path": str(path), "redacted": redact, "counts": counts}


async def import_state(
    driver: BrowserDriver,
    path: Path,
    kinds: list[DataKind] | None = None,
    dry_run: bool = True,
) -> dict[str, int]:
    data = json.loads(path.read_text())
    payload = data.get("kinds", {})
    kinds = kinds or [k for k in ALL_KINDS if k in payload]
    counts: dict[str, int] = {}

    if "cookies" in kinds and payload.get("cookies"):
        rows = payload["cookies"]
        for r in rows:
            if r.get("value") == REDACTED:
                raise BrowserDataError(
                    f"{path} was exported with redact=True — cookie values are masked"
                )
        cookies = [Cookie(**r) for r in rows]
        counts["cookies"] = len(cookies) if dry_run else await driver.set_cookies(cookies)

    if "bookmarks" in kinds and payload.get("bookmarks"):
        bookmarks = [Bookmark(**b) for b in payload["bookmarks"]]
        counts["bookmarks"] = (
            len(bookmarks) if dry_run else await driver.add_bookmarks(bookmarks)
        )

    if "credentials" in kinds and payload.get("credentials"):
        rows = payload["credentials"]
        for r in rows:
            if r.get("password") == REDACTED:
                raise BrowserDataError(
                    f"{path} was exported with redact=True — passwords are masked"
                )
        creds = [Credential(**r) for r in rows]
        counts["credentials"] = (
            len(creds) if dry_run else await driver.set_credentials(creds)
        )

    if "storage" in kinds and payload.get("storage"):
        rows = payload["storage"]
        for r in rows:
            if set(r.get("local", {}).values()) == {REDACTED} and r["local"]:
                raise BrowserDataError(
                    f"{path} was exported with redact=True — storage values are masked"
                )
        storages = [SiteStorage(**r) for r in rows]
        if dry_run:
            counts["storage"] = sum(len(s.local) + len(s.session) for s in storages)
        else:
            counts["storage"] = sum(
                await driver.set_site_storage(s) for s in storages
            )
    return counts
