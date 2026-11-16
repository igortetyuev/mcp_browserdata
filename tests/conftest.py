import sqlite3
from pathlib import Path

import pytest

from mcp_browserdata import crypto

TEST_KEY = b"0123456789abcdef"


@pytest.fixture(autouse=True)
def fake_keychain_key(monkeypatch):
    """All tests use a fixed AES key instead of the real keychain."""
    monkeypatch.setattr(crypto, "_derived_key", lambda service: TEST_KEY)
    monkeypatch.setattr(
        crypto, "safe_storage_password", lambda service: "test-password"
    )


COOKIES_SCHEMA = """
CREATE TABLE cookies(
    creation_utc INTEGER NOT NULL,
    host_key TEXT NOT NULL,
    top_frame_site_key TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    encrypted_value BLOB NOT NULL,
    path TEXT NOT NULL,
    expires_utc INTEGER NOT NULL,
    is_secure INTEGER NOT NULL,
    is_httponly INTEGER NOT NULL,
    last_access_utc INTEGER NOT NULL,
    has_expires INTEGER NOT NULL DEFAULT 1,
    is_persistent INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 1,
    samesite INTEGER NOT NULL DEFAULT -1,
    source_scheme INTEGER NOT NULL DEFAULT 0,
    source_port INTEGER NOT NULL DEFAULT -1,
    last_update_utc INTEGER NOT NULL DEFAULT 0,
    source_type INTEGER NOT NULL DEFAULT 0,
    has_cross_site_ancestor INTEGER NOT NULL DEFAULT 1,
    UNIQUE (host_key, top_frame_site_key, name, path)
)"""

LOGINS_SCHEMA = """
CREATE TABLE logins(
    origin_url TEXT NOT NULL,
    action_url TEXT,
    username_element TEXT,
    username_value TEXT,
    password_element TEXT,
    password_value BLOB,
    date_created INTEGER NOT NULL,
    date_last_used INTEGER NOT NULL DEFAULT 0,
    date_password_modified INTEGER NOT NULL DEFAULT 0,
    times_used INTEGER NOT NULL DEFAULT 0,
    signon_realm TEXT,
    scheme INTEGER NOT NULL DEFAULT 0,
    blacklisted_by_user INTEGER NOT NULL DEFAULT 0,
    UNIQUE (origin_url, username_value)
)"""


@pytest.fixture
def cookies_db_path(tmp_path: Path) -> Path:
    db = tmp_path / "Cookies"
    conn = sqlite3.connect(db)
    conn.execute(COOKIES_SCHEMA)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def logins_db_path(tmp_path: Path) -> Path:
    db = tmp_path / "Login Data"
    conn = sqlite3.connect(db)
    conn.execute(LOGINS_SCHEMA)
    conn.commit()
    conn.close()
    return db
