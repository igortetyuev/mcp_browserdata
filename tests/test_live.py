"""Live tests against real browsers — `uv run pytest -m live`.

Chrome: needs remote debugging enabled + keychain access granted.
Yandex: file-level only (keychain prompt for "Yandex Safe Storage").
Safari: needs Full Disk Access for the test host.
"""

import time

import pytest

from mcp_browserdata.drivers import get_driver
from mcp_browserdata.models import Cookie

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_chrome_cookie_roundtrip_cdp():
    d = get_driver("chrome")
    info = d.info()
    if not info.cdp:
        pytest.skip("chrome remote debugging off")
    c = Cookie(name="mcpbd_test", value="v1", domain=".mcpbd.test",
               expires=time.time() + 600, http_only=True)
    try:
        assert await d.set_cookies([c]) == 1
        got = {x.name: x for x in await d.get_cookies("mcpbd.test")}
        assert "mcpbd_test" in got
    finally:
        await d.set_cookies([Cookie(name="mcpbd_test", value="", domain=".mcpbd.test",
                                  expires=1)])


@pytest.mark.asyncio
async def test_file_level_cookie_read():
    for name in ("chrome", "yandex"):
        d = get_driver(name)
        if d.info().file_access != "ok":
            pytest.skip(f"{name} profile files not readable")
        cookies = await d.get_cookies("example.com")
        assert isinstance(cookies, list)
