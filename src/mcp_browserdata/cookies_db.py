"""Chromium `Cookies` sqlite store (file-level access for browsers without CDP).

Reads copy db+WAL sidecars to a temp dir (safe while the browser runs).
Writes go to the live DB and fail with BrowserRunningError when sqlite is locked.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mcp_browserdata import crypto
from mcp_browserdata.errors import BrowserRunningError
from mcp_browserdata.models import Cookie

WEBKIT_EPOCH_US = 11644473600000000  # microseconds between 1601-01-01 and 1970-01-01

_SAMESITE = {-1: None, 0: "None", 1: "Lax", 2: "Strict"}
_SAMESITE_REV = {v: k for k, v in _SAMESITE.items()}


def chrome_time_to_unix(us: int | None) -> float | None:
    if not us:
        return None
    return (us - WEBKIT_EPOCH_US) / 1_000_000


def unix_to_chrome_time(unix: float | None) -> int:
    return int((unix or 0) * 1_000_000) + WEBKIT_EPOCH_US


@contextmanager
def _copied_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a read connection on a temp copy of db + -wal/-shm sidecars."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / db_path.name
        for suffix in ("", "-wal", "-shm"):
            src = Path(f"{db_path}{suffix}")
            if src.exists():
                shutil.copy2(src, Path(f"{copy}{suffix}"))
        conn = sqlite3.connect(copy)
        try:
            yield conn
        finally:
            conn.close()


def read_cookies(db_path: Path, service: str) -> list[Cookie]:
    """Decrypt every cookie row. Works while the browser runs (temp copy)."""
    out: list[Cookie] = []
    with _copied_db(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT host_key, name, path, value, encrypted_value, expires_utc, "
            "is_secure, is_httponly, samesite, is_persistent FROM cookies"
        ):
            out.append(
                Cookie(
                    name=row["name"],
                    value=crypto.decrypt_cookie_value(
                        row["encrypted_value"], row["value"], row["host_key"], service
                    ),
                    domain=row["host_key"],
                    path=row["path"],
                    expires=chrome_time_to_unix(row["expires_utc"])
                    if row["is_persistent"]
                    else None,
                    secure=bool(row["is_secure"]),
                    http_only=bool(row["is_httponly"]),
                    same_site=_SAMESITE.get(row["samesite"]),
                )
            )
    return out


def write_cookies(db_path: Path, cookies: list[Cookie], service: str) -> int:
    """Upsert cookies into the live DB. Browser must be quit (DB locked otherwise)."""
    now_us = int(time.time() * 1_000_000) + WEBKIT_EPOCH_US
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        raise BrowserRunningError("cookie DB write", "the browser") from exc
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(cookies)")}
        written = 0
        for c in cookies:
            row = {
                "creation_utc": now_us,
                "host_key": c.domain,
                "top_frame_site_key": "",
                "name": c.name,
                "value": "",
                "encrypted_value": crypto.encrypt_cookie_value(c.value, c.domain, service),
                "path": c.path,
                "expires_utc": unix_to_chrome_time(c.expires or (time.time() + 31_536_000)),
                "is_secure": int(c.secure),
                "is_httponly": int(c.http_only),
                "last_access_utc": now_us,
                "has_expires": int(c.expires is not None),
                "is_persistent": int(c.expires is not None),
                "priority": 1,
                "samesite": _SAMESITE_REV.get(c.same_site, -1),
                "source_scheme": 2 if c.secure else 1,
                "source_port": -1,
                "is_same_party": 0,
                "last_update_utc": now_us,
                "source_type": 0,
                "has_cross_site_ancestor": 1,
            }
            use = {k: v for k, v in row.items() if k in cols}
            keys = ", ".join(use)
            ph = ", ".join(f":{k}" for k in use)
            conn.execute(
                f"INSERT OR REPLACE INTO cookies ({keys}) VALUES ({ph})", use
            )
            written += 1
        conn.commit()
        return written
    finally:
        conn.close()
