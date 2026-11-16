"""Chromium `Login Data` sqlite store — read/write saved passwords.

Reads via temp copy (safe while running); writes need the browser quit.
`password_value` is a v10 blob (no host prefix, unlike cookies).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from mcp_browserdata import crypto
from mcp_browserdata.cookies_db import _copied_db, chrome_time_to_unix, unix_to_chrome_time
from mcp_browserdata.errors import BrowserRunningError
from mcp_browserdata.models import Credential


def read_credentials(db_path: Path, service: str) -> list[Credential]:
    out: list[Credential] = []
    with _copied_db(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT origin_url, action_url, username_value, password_value, "
            "date_created, date_last_used, times_used FROM logins"
        ):
            raw = crypto.decrypt_v10(row["password_value"], service)
            out.append(
                Credential(
                    origin=row["origin_url"].rstrip("/"),
                    url=row["action_url"] or row["origin_url"],
                    username=row["username_value"],
                    password=raw.decode("utf-8", errors="replace"),
                    date_created=chrome_time_to_unix(row["date_created"]),
                    date_last_used=chrome_time_to_unix(row["date_last_used"]),
                    times_used=row["times_used"] or 0,
                )
            )
    return out


def write_credentials(db_path: Path, creds: list[Credential], service: str) -> int:
    """Insert-or-update rows. Browser must be quit (DB locked otherwise)."""
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        raise BrowserRunningError("login DB write", "the browser") from exc
    try:
        written = 0
        for c in creds:
            blob = crypto.encrypt_v10(c.password.encode(), service)
            now_us = unix_to_chrome_time(time.time())
            updated = conn.execute(
                "UPDATE logins SET password_value=?, date_last_used=?, times_used=? "
                "WHERE origin_url=? AND username_value=?",
                (
                    blob,
                    unix_to_chrome_time(c.date_last_used) or now_us,
                    c.times_used,
                    c.origin + "/",
                    c.username,
                ),
            ).rowcount
            if not updated:
                conn.execute(
                    "INSERT INTO logins (origin_url, action_url, username_value, "
                    "password_value, date_created, date_last_used, times_used, "
                    "signon_realm, scheme, date_password_modified, blacklisted_by_user) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                    (
                        c.origin + "/",
                        c.url or c.origin + "/",
                        c.username,
                        blob,
                        unix_to_chrome_time(c.date_created) or now_us,
                        unix_to_chrome_time(c.date_last_used) or now_us,
                        c.times_used,
                        c.origin + "/",
                        0,
                        now_us,
                    ),
                )
            written += 1
        conn.commit()
        return written
    finally:
        conn.close()
