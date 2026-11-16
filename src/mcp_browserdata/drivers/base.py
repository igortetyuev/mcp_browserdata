"""Driver protocol: one implementation per browser family."""

from __future__ import annotations

from typing import Protocol

from mcp_browserdata.models import (
    Bookmark,
    BrowserInfo,
    Cookie,
    Credential,
    SiteStorage,
)


class BrowserDriver(Protocol):
    name: str
    kind: str  # "chromium" | "safari" | "obscura"

    def info(self) -> BrowserInfo: ...

    async def get_cookies(self, domain: str | None = None) -> list[Cookie]: ...

    async def set_cookies(self, cookies: list[Cookie]) -> int: ...

    async def get_bookmarks(self) -> list[Bookmark]: ...

    async def add_bookmarks(self, bookmarks: list[Bookmark]) -> int: ...

    async def get_credentials(self, domain: str | None = None) -> list[Credential]: ...

    async def set_credentials(self, creds: list[Credential]) -> int: ...

    async def get_site_storage(
        self, origin: str, include_session: bool = False
    ) -> SiteStorage: ...

    async def set_site_storage(self, storage: SiteStorage) -> int: ...
