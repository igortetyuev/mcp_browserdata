"""obscura driver — bridges into `obscura --stealth mcp` via fastmcp.Client.

obscura keeps its cookie jar / storage in process memory only, so state is
ephemeral: it lives for the lifetime of the spawned child (and dies with this
MCP server). It is also a *different* process than any obscura MCP already
configured in the host app — cookies copied here are not shared with it.
"""

from __future__ import annotations

import json
import shutil
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from mcp_browserdata.errors import BrowserDataError, UnsupportedKindError
from mcp_browserdata.models import (
    Bookmark,
    BrowserInfo,
    Cookie,
    Credential,
    SiteStorage,
)


class ObscuraDriver:
    name = "obscura"
    kind = "obscura"

    def __init__(self, binary: str = "obscura") -> None:
        self._binary = binary
        self._client: Client | None = None
        self._ctx = None

    async def _mcp(self) -> Client:
        if self._client is None:
            if not shutil.which(self._binary):
                raise BrowserDataError(f"'{self._binary}' not found on PATH")
            client = Client(StdioTransport(self._binary, ["--stealth", "mcp"]))
            self._ctx = client
            await client.__aenter__()
            self._client = client
        return self._client

    async def _call(self, tool: str, args: dict | None = None) -> Any:
        result = await (await self._mcp()).call_tool(tool, args or {})
        if result.is_error:
            text = "".join(
                getattr(c, "text", "") for c in result.content
            )
            raise BrowserDataError(f"obscura {tool} failed: {text[:300]}")
        if result.data is not None:
            return result.data
        text = "".join(getattr(c, "text", "") for c in result.content)
        return text

    def info(self) -> BrowserInfo:
        ok = shutil.which(self._binary) is not None
        caps = {
            "cookies": {"read": ok, "write": ok},
            "storage": {"read": ok, "write": ok},
            "bookmarks": {"read": False, "write": False},
            "credentials": {"read": False, "write": False},
        }
        return BrowserInfo(
            name=self.name,
            kind=self.kind,
            profile_dir=None,
            running=False,
            cdp=False,
            file_access="missing",
            capabilities=caps,
        )

    # --- cookies ---

    async def get_cookies(self, domain: str | None = None) -> list[Cookie]:
        data = await self._call(
            "browser_get_cookies", {"domain": domain} if domain else {}
        )
        rows = [json.loads(line) for line in str(data).splitlines() if line.strip()]
        return [_cookie_from_obscura(r) for r in rows]

    async def set_cookies(self, cookies: list[Cookie]) -> int:
        if not cookies:
            return 0
        # bulk via storage_state (preserves expires/sameSite unlike per-cookie tool)
        state = {"cookies": [_cookie_to_obscura(c) for c in cookies]}
        await self._call("browser_set_storage_state", {"state": state})
        return len(cookies)

    # --- site storage ---

    async def get_site_storage(
        self, origin: str, include_session: bool = False
    ) -> SiteStorage:
        await self._call("browser_navigate", {"url": origin})
        local = await self._call(
            "browser_evaluate",
            {"expression": "JSON.stringify(Object.entries(localStorage))"},
        )
        session = (
            await self._call(
                "browser_evaluate",
                {"expression": "JSON.stringify(Object.entries(sessionStorage))"},
            )
            if include_session
            else "[]"
        )
        return SiteStorage(
            origin=origin,
            local=dict(json.loads(local or "[]")),
            session=dict(json.loads(session or "[]")),
        )

    async def set_site_storage(self, storage: SiteStorage) -> int:
        entry = {
            "origin": storage.origin,
            "localStorage": [
                {"name": k, "value": v} for k, v in storage.local.items()
            ],
            "sessionStorage": [
                {"name": k, "value": v} for k, v in storage.session.items()
            ],
        }
        await self._call(
            "browser_set_storage_state", {"state": {"origins": [entry]}}
        )
        return len(storage.local) + len(storage.session)

    # --- unsupported kinds ---

    async def get_bookmarks(self) -> list[Bookmark]:
        raise UnsupportedKindError(self.name, "bookmarks", "read of")

    async def add_bookmarks(self, bookmarks: list[Bookmark]) -> int:
        raise UnsupportedKindError(self.name, "bookmarks", "write of")

    async def get_credentials(self, domain: str | None = None) -> list[Credential]:
        raise UnsupportedKindError(self.name, "credentials", "read of")

    async def set_credentials(self, creds: list[Credential]) -> int:
        raise UnsupportedKindError(self.name, "credentials", "write of")


def _cookie_from_obscura(raw: dict) -> Cookie:
    return Cookie(
        name=raw["name"],
        value=raw.get("value", ""),
        domain=raw.get("domain", ""),
        path=raw.get("path", "/"),
        expires=raw.get("expires") or raw.get("expires_utc"),
        secure=bool(raw.get("secure")),
        http_only=bool(raw.get("httpOnly", raw.get("http_only"))),
        same_site=raw.get("sameSite", raw.get("same_site")),
    )


def _cookie_to_obscura(c: Cookie) -> dict:
    out = {
        "name": c.name,
        "value": c.value,
        "domain": c.domain,
        "path": c.path,
        "expires": c.expires if c.expires is not None else -1,
        "httpOnly": c.http_only,
        "secure": c.secure,
    }
    if c.same_site:
        out["sameSite"] = c.same_site
    return out
