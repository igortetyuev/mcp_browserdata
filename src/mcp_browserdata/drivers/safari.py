"""Safari driver — file formats only, degrades gracefully without FDA."""

from __future__ import annotations

import subprocess

from mcp_browserdata import binarycookies, keychain_cli, safari_files
from mcp_browserdata.errors import BrowserRunningError, UnsupportedKindError
from mcp_browserdata.models import (
    Bookmark,
    BrowserInfo,
    Cookie,
    Credential,
    SiteStorage,
)


class SafariDriver:
    name = "safari"
    kind = "safari"

    def is_running(self) -> bool:
        proc = subprocess.run(["pgrep", "-x", "Safari"], capture_output=True)
        return proc.returncode == 0

    def info(self) -> BrowserInfo:
        ok = safari_files.readable(safari_files.COOKIES_PATH)
        access = "ok" if ok else "needs_fda"
        caps = {
            "cookies": {"read": ok, "write": ok},
            "bookmarks": {
                "read": safari_files.readable(safari_files.BOOKMARKS_PATH),
                "write": safari_files.readable(safari_files.BOOKMARKS_PATH),
            },
            "credentials": {"read": True, "write": True},  # security CLI, per-site
            "storage": {"read": False, "write": False},
        }
        return BrowserInfo(
            name=self.name,
            kind=self.kind,
            profile_dir=None,
            running=self.is_running(),
            cdp=False,
            file_access=access,
            capabilities=caps,
        )

    # --- cookies ---

    async def get_cookies(self, domain: str | None = None) -> list[Cookie]:
        safari_files.require_fda(safari_files.COOKIES_PATH)
        cookies = binarycookies.read_file(safari_files.COOKIES_PATH)
        if domain:
            q = domain.lstrip(".").lower()
            cookies = [c for c in cookies if c.domain.lstrip(".").lower().endswith(q)]
        return cookies

    async def set_cookies(self, cookies: list[Cookie]) -> int:
        safari_files.require_fda(safari_files.COOKIES_PATH)
        if self.is_running():
            raise BrowserRunningError("Safari", "cookie file write")
        existing = {c.key: c for c in binarycookies.read_file(safari_files.COOKIES_PATH)}
        for c in cookies:
            existing[c.key] = c
        binarycookies.write_file(safari_files.COOKIES_PATH, list(existing.values()))
        return len(cookies)

    # --- bookmarks ---

    async def get_bookmarks(self) -> list[Bookmark]:
        return safari_files.read_bookmarks()

    async def add_bookmarks(self, bookmarks: list[Bookmark]) -> int:
        if self.is_running():
            raise BrowserRunningError("Safari", "bookmarks.plist write")
        return safari_files.add_bookmarks(bookmarks)

    # --- credentials (per-site, best-effort) ---

    async def get_credentials(self, domain: str | None = None) -> list[Credential]:
        if not domain:
            raise UnsupportedKindError(
                self.name, "credentials", "bulk read of (pass domain= for per-site lookup)"
            )
        cred = keychain_cli.get_credential(domain)
        return [cred] if cred else []

    async def set_credentials(self, creds: list[Credential]) -> int:
        return sum(1 for c in creds if keychain_cli.set_credential(c))

    # --- storage ---

    async def get_site_storage(
        self, origin: str, include_session: bool = False
    ) -> SiteStorage:
        raise UnsupportedKindError(self.name, "storage")

    async def set_site_storage(self, storage: SiteStorage) -> int:
        raise UnsupportedKindError(self.name, "storage")
