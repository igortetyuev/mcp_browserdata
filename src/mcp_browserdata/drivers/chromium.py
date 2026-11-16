"""Chromium-family driver (Chrome, Yandex, Chromium): files + Keychain decrypt,
CDP when DevToolsActivePort is present."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from mcp_browserdata import bookmarks_file, cookies_db, logins_db, storage_local
from mcp_browserdata.cdp import CdpSession, discover_ws_url
from mcp_browserdata.errors import (
    BrowserDataError,
    BrowserRunningError,
    UnsupportedKindError,
)
from mcp_browserdata.models import (
    Bookmark,
    BrowserInfo,
    Cookie,
    Credential,
    SiteStorage,
)


@dataclass(frozen=True)
class ChromiumSpec:
    profile_dir: Path
    keychain_service: str
    process_name: str
    app_name: str  # for osascript quit hints


HOME = Path.home()
CHROMIUM_BROWSERS: dict[str, ChromiumSpec] = {
    "chrome": ChromiumSpec(
        HOME / "Library/Application Support/Google/Chrome",
        "Chrome Safe Storage",
        "Google Chrome",
        "Google Chrome",
    ),
    "yandex": ChromiumSpec(
        HOME / "Library/Application Support/Yandex/YandexBrowser",
        "Yandex Safe Storage",
        "Yandex",
        "Yandex",
    ),
    "chromium": ChromiumSpec(
        HOME / "Library/Application Support/Chromium",
        "Chromium Safe Storage",
        "Chromium",
        "Chromium",
    ),
}


def _domain_match(cookie_domain: str, query: str) -> bool:
    q = query.lstrip(".").lower()
    d = cookie_domain.lstrip(".").lower()
    return d == q or d.endswith("." + q)


class ChromiumDriver:
    kind = "chromium"

    def __init__(self, spec: ChromiumSpec, name: str | None = None) -> None:
        self.spec = spec
        self.name = name or spec.process_name
        self._cdp: CdpSession | None = None

    # --- paths ---

    @property
    def profile(self) -> Path:
        return self.spec.profile_dir / "Default"

    @property
    def cookies_db(self) -> Path:
        return self.profile / "Cookies"

    @property
    def logins_db(self) -> Path:
        return self.profile / "Login Data"

    @property
    def bookmarks_path(self) -> Path:
        return self.profile / "Bookmarks"

    # --- environment ---

    def is_running(self) -> bool:
        proc = subprocess.run(
            ["pgrep", "-x", self.spec.process_name], capture_output=True
        )
        return proc.returncode == 0

    @property
    def cdp_available(self) -> bool:
        try:
            discover_ws_url(self.spec.profile_dir)
            return True
        except BrowserDataError:
            return False

    def _cdp_error_hint(self) -> str:
        return (
            f"live access needs remote debugging on {self.spec.app_name} "
            "(DevToolsActivePort in the profile dir). File-level access works "
            "with the browser quit."
        )

    async def _cdp_session(self) -> CdpSession:
        if self._cdp is None or self._cdp._ws is None:
            self._cdp = CdpSession(self.spec.profile_dir)
            await self._cdp.connect()
        return self._cdp

    def info(self) -> BrowserInfo:
        files = self.cookies_db.exists()
        cdp = self.cdp_available
        bm = self.bookmarks_path.exists()
        logins = self.logins_db.exists()
        caps = {
            "cookies": {"read": files or cdp, "write": cdp or files},
            "bookmarks": {"read": bm, "write": bm},
            "credentials": {"read": logins, "write": logins},
            "storage": {"read": cdp, "write": cdp},
        }
        return BrowserInfo(
            name=self.name,
            kind=self.kind,
            profile_dir=str(self.profile),
            running=self.is_running(),
            cdp=cdp,
            file_access="ok" if files else "missing",
            capabilities=caps,
        )

    # --- cookies ---

    async def get_cookies(self, domain: str | None = None) -> list[Cookie]:
        if not self.cookies_db.exists():
            raise BrowserDataError(f"{self.cookies_db} not found")
        cookies = cookies_db.read_cookies(self.cookies_db, self.spec.keychain_service)
        if domain:
            cookies = [c for c in cookies if _domain_match(c.domain, domain)]
        return cookies

    async def set_cookies(self, cookies: list[Cookie]) -> int:
        if self.cdp_available:
            cdp = await self._cdp_session()
            raw = [
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                    **({"expires": c.expires} if c.expires else {}),
                    "secure": c.secure,
                    "httpOnly": c.http_only,
                    **({"sameSite": c.same_site} if c.same_site else {}),
                }
                for c in cookies
            ]
            return await cdp.set_cookies(raw)
        return cookies_db.write_cookies(
            self.cookies_db, cookies, self.spec.keychain_service
        )

    # --- bookmarks ---

    async def get_bookmarks(self) -> list[Bookmark]:
        if not self.bookmarks_path.exists():
            return []
        return bookmarks_file.read_bookmarks(self.bookmarks_path)

    async def add_bookmarks(self, bookmarks: list[Bookmark]) -> int:
        if self.is_running():
            raise BrowserRunningError(self.spec.app_name, "bookmark write")
        return bookmarks_file.add_bookmarks(self.bookmarks_path, bookmarks)

    # --- credentials ---

    async def get_credentials(self, domain: str | None = None) -> list[Credential]:
        if not self.logins_db.exists():
            return []
        creds = logins_db.read_credentials(self.logins_db, self.spec.keychain_service)
        if domain:
            q = domain.lower()
            creds = [c for c in creds if q in c.origin.lower()]
        return creds

    async def set_credentials(self, creds: list[Credential]) -> int:
        return logins_db.write_credentials(
            self.logins_db, creds, self.spec.keychain_service
        )

    # --- site storage ---

    async def get_site_storage(
        self, origin: str, include_session: bool = False
    ) -> SiteStorage:
        if not self.cdp_available:
            raise UnsupportedKindError(self.name, "storage", "live read of")
        cdp = await self._cdp_session()
        return await storage_local.cdp_get_storage(cdp, origin, include_session)

    async def set_site_storage(self, storage: SiteStorage) -> int:
        if not self.cdp_available:
            raise UnsupportedKindError(self.name, "storage", "live write of")
        cdp = await self._cdp_session()
        return await storage_local.cdp_set_storage(cdp, storage)

    # --- raw leveldb copy (used by sync for Chromium→Chromium when both quit) ---

    def raw_storage_dirs(self) -> dict[str, Path]:
        return {
            "local": self.profile / "Local Storage" / "leveldb",
            "session": self.profile / "Session Storage",
        }
