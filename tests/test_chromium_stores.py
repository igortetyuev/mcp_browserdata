import json
import sqlite3
import time

from mcp_browserdata import bookmarks_file, cookies_db, crypto, logins_db
from mcp_browserdata.models import Bookmark, Cookie, Credential

SVC = "Test Safe Storage"
NOW = cookies_db.unix_to_chrome_time(time.time())


def _insert_cookie(db, host, name, path, value, secure=0, http=0, persistent=1):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO cookies (creation_utc, host_key, name, value, encrypted_value, "
        "path, expires_utc, is_secure, is_httponly, last_access_utc, is_persistent) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            NOW,
            host,
            name,
            "",
            crypto.encrypt_cookie_value(value, host, SVC),
            path,
            NOW + 10_000_000_000_000,
            secure,
            http,
            NOW,
            persistent,
        ),
    )
    conn.commit()
    conn.close()


def test_read_cookies_decrypts(cookies_db_path):
    _insert_cookie(cookies_db_path, ".example.com", "sid", "/", "token123", http=1)
    _insert_cookie(cookies_db_path, "other.net", "a", "/x", "v2", secure=1)
    got = {c.name: c for c in cookies_db.read_cookies(cookies_db_path, SVC)}
    assert got["sid"].value == "token123"
    assert got["sid"].http_only and not got["sid"].secure
    assert got["a"].domain == "other.net"
    assert got["a"].secure and got["a"].expires is not None


def test_write_then_read_cookies(cookies_db_path):
    cookies_db.write_cookies(
        cookies_db_path,
        [Cookie(name="n1", value="v1", domain=".x.io", secure=True, http_only=True)],
        SVC,
    )
    got = cookies_db.read_cookies(cookies_db_path, SVC)
    assert len(got) == 1
    assert got[0].value == "v1" and got[0].secure and got[0].http_only


def test_write_replaces_same_key(cookies_db_path):
    c = Cookie(name="n", value="old", domain=".x.io")
    cookies_db.write_cookies(cookies_db_path, [c], SVC)
    cookies_db.write_cookies(
        cookies_db_path, [Cookie(name="n", value="new", domain=".x.io")], SVC
    )
    got = cookies_db.read_cookies(cookies_db_path, SVC)
    assert [x.value for x in got] == ["new"]


def test_logins_roundtrip(logins_db_path):
    logins_db.write_credentials(
        logins_db_path,
        [
            Credential(
                origin="https://ex.com",
                username="u@x",
                password="päss",
                times_used=3,
            )
        ],
        SVC,
    )
    got = logins_db.read_credentials(logins_db_path, SVC)
    assert len(got) == 1
    assert got[0].username == "u@x"
    assert got[0].password == "päss"
    assert got[0].times_used == 3


def test_logins_update(logins_db_path):
    c = Credential(origin="https://ex.com", username="u", password="p1")
    logins_db.write_credentials(logins_db_path, [c], SVC)
    logins_db.write_credentials(
        logins_db_path,
        [Credential(origin="https://ex.com", username="u", password="p2")],
        SVC,
    )
    got = logins_db.read_credentials(logins_db_path, SVC)
    assert len(got) == 1 and got[0].password == "p2"


def test_bookmarks_read_add(tmp_path):
    path = tmp_path / "Bookmarks"
    path.write_text(
        json.dumps(
            {
                "next_id": "5",
                "roots": {
                    "bookmark_bar": {
                        "type": "folder",
                        "name": "Bookmarks bar",
                        "children": [
                            {"type": "url", "name": "A", "url": "https://a.io/"}
                        ],
                    },
                    "other": {"type": "folder", "name": "Other", "children": []},
                    "synced": {"type": "folder", "name": "Mobile", "children": []},
                },
            }
        )
    )
    got = bookmarks_file.read_bookmarks(path)
    assert len(got) == 1 and got[0].url == "https://a.io/"
    assert got[0].folder == ("Bookmarks bar",)

    added = bookmarks_file.add_bookmarks(
        path,
        [
            Bookmark(url="https://a.io", title="dup"),  # dup by normalized url
            Bookmark(url="https://b.io/", title="B", folder=("Bookmarks bar", "Work")),
        ],
    )
    assert added == 1
    got = bookmarks_file.read_bookmarks(path)
    b = next(x for x in got if x.title == "B")
    assert b.folder == ("Bookmarks bar", "Work")
