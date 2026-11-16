import time

from mcp_browserdata import binarycookies
from mcp_browserdata.models import Cookie


def test_roundtrip(tmp_path):
    cookies = [
        Cookie(name="sid", value="abc123", domain=".example.com", path="/",
               expires=time.time() + 3600, secure=True, http_only=True),
        Cookie(name="plain", value="x", domain="example.com", path="/app"),
    ]
    path = tmp_path / "Cookies.binarycookies"
    binarycookies.write_file(path, cookies)
    got = {c.name: c for c in binarycookies.read_file(path)}
    assert set(got) == {"sid", "plain"}
    c = got["sid"]
    assert c.value == "abc123" and c.domain == ".example.com"
    assert c.secure and c.http_only
    assert abs((c.expires or 0) - cookies[0].expires) < 1
    assert got["plain"].path == "/app"


def test_write_creates_backup(tmp_path):
    path = tmp_path / "Cookies.binarycookies"
    binarycookies.write_file(path, [Cookie(name="a", value="1", domain="x.io")])
    binarycookies.write_file(path, [Cookie(name="b", value="2", domain="x.io")])
    assert (tmp_path / "Cookies.binarycookies.bak-mcpbrowserdata").exists()
