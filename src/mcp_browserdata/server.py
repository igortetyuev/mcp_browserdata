"""FastMCP stdio server for cross-browser data copy/sync."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP

from mcp_browserdata import statefile, sync
from mcp_browserdata.drivers import all_drivers, get_driver
from mcp_browserdata.models import (
    Bookmark,
    Cookie,
    Credential,
    SiteStorage,
    to_jsonable,
)

INSTRUCTIONS = """\
Cross-browser data tools: read/write/sync cookies, passwords, bookmarks and
local/session storage across installed browsers (chrome, yandex, chromium,
safari, obscura).

Security policy:
- sync_data/export_state move secret VALUES inside this process only and
  return counters — never paste cookies/passwords into the conversation.
- get_cookies/get_credentials/get_site_storage return values ONLY when
  reveal=True is passed explicitly. Otherwise metadata with masked values.
- Write tools (set_*, sync_data with dry_run=False, import_state, add_bookmark)
  must be called ONLY on the user's explicit request.

Gotchas:
- Most file-level writes require the target browser to be QUIT (sqlite locks,
  Bookmarks/Cookies clobbered on exit) — errors will say so.
- Safari file access needs Full Disk Access for the host app; without it the
  tools return an FDA-needed error. Safari passwords are per-site only.
- obscura keeps data in memory of a spawned child process — state is
  ephemeral and unrelated to any other obscura MCP instance.
- Syncing live login sessions copies refresh tokens; two browsers sharing one
  account will invalidate each other on token rotation.
"""

mcp = FastMCP("browserdata", instructions=INSTRUCTIONS)


@mcp.tool
async def list_browsers() -> list[dict[str, Any]]:
    """Detected browsers: profile paths, running state, CDP/file access and
    per-kind capabilities (read/write flags)."""
    return to_jsonable([d.info() for d in all_drivers().values()])


@mcp.tool
async def get_cookies(
    browser: str, domain: str | None = None, reveal: bool = False
) -> list[dict[str, Any]]:
    """Cookies for a browser, optionally filtered by domain suffix.
    Without reveal=True the `value` field is masked."""
    cookies = await get_driver(browser).get_cookies(domain)
    rows = to_jsonable(cookies)
    if not reveal:
        for r in rows:
            r["value"] = "***"
    return rows


@mcp.tool
async def set_cookies(browser: str, cookies: list[dict[str, Any]]) -> dict[str, Any]:
    """Write cookies into a browser's jar. ONLY on explicit user request.
    Each item: {name, value, domain, path?, expires?, secure?, http_only?, same_site?}."""
    written = await get_driver(browser).set_cookies([Cookie(**c) for c in cookies])
    return {"written": written, "browser": browser}


@mcp.tool
async def list_bookmarks(browser: str) -> list[dict[str, Any]]:
    """All bookmarks with folder paths."""
    return to_jsonable(await get_driver(browser).get_bookmarks())


@mcp.tool
async def add_bookmark(
    browser: str, url: str, title: str, folder: list[str] | None = None
) -> dict[str, Any]:
    """Add one bookmark. ONLY on explicit user request."""
    n = await get_driver(browser).add_bookmarks(
        [Bookmark(url=url, title=title, folder=tuple(folder or ("Bookmarks bar",)))]
    )
    return {"added": n, "browser": browser}


@mcp.tool
async def get_credentials(
    browser: str, domain: str | None = None, reveal: bool = False
) -> list[dict[str, Any]]:
    """Saved passwords. Passwords are masked unless reveal=True.
    Safari supports per-site lookup only — pass domain there."""
    creds = await get_driver(browser).get_credentials(domain)
    rows = to_jsonable(creds)
    if not reveal:
        for r in rows:
            r["password"] = "***"
    return rows


@mcp.tool
async def set_credential(
    browser: str, origin: str, username: str, password: str
) -> dict[str, Any]:
    """Write one login/password. ONLY on explicit user request."""
    n = await get_driver(browser).set_credentials(
        [Credential(origin=origin, username=username, password=password)]
    )
    return {"written": n, "browser": browser}


@mcp.tool
async def get_site_storage(
    browser: str,
    origin: str,
    include_session: bool = False,
    reveal: bool = False,
) -> dict[str, Any]:
    """localStorage (+sessionStorage) for one origin, e.g. "https://example.com".
    Values masked unless reveal=True."""
    s = await get_driver(browser).get_site_storage(origin, include_session)
    row = to_jsonable(s)
    if not reveal:
        row["local"] = {k: "***" for k in row["local"]}
        row["session"] = {k: "***" for k in row["session"]}
    return row


@mcp.tool
async def set_site_storage(
    browser: str,
    origin: str,
    local: dict[str, str] | None = None,
    session: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write localStorage/sessionStorage entries for an origin.
    ONLY on explicit user request."""
    n = await get_driver(browser).set_site_storage(
        SiteStorage(origin=origin, local=local or {}, session=session or {})
    )
    return {"written": n, "browser": browser}


@mcp.tool
async def sync_data(
    src: str,
    dst: str,
    kinds: list[Literal["cookies", "bookmarks", "credentials", "storage"]] | None = None,
    domain: str | None = None,
    direction: Literal["merge", "src_to_dst", "dst_to_src"] = "merge",
    conflict: Literal["newest", "prefer_src", "prefer_dst", "skip"] = "newest",
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    """Copy/merge data between two browsers. Returns COUNTERS ONLY — secret
    values stay inside the server.

    kinds defaults to all four. domain limits cookies/credentials/bookmarks by
    substring and is REQUIRED for per-origin storage sync (unless both browsers
    are quit Chromium — then whole storage dirs are raw-copied).
    direction=merge syncs both ways. dry_run=True (default) reports what would
    change without writing. Run writes only on explicit user request."""
    stats = await sync.sync_data(
        get_driver(src),
        get_driver(dst),
        kinds=kinds,
        domain=domain,
        direction=direction,
        conflict=conflict,
        dry_run=dry_run,
    )
    return to_jsonable(stats)


@mcp.tool
async def export_state(
    browser: str,
    path: str,
    kinds: list[Literal["cookies", "bookmarks", "credentials", "storage"]] | None = None,
    origins: list[str] | None = None,
    redact: bool = True,
) -> dict[str, Any]:
    """Export browser state to a JSON file (chmod 600). Returns path+counts.
    redact=True (default) masks secret values — set False for a real backup.
    `origins` lists origins whose storage to include."""
    return await statefile.export_state(
        get_driver(browser), Path(path), kinds=kinds, origins=origins, redact=redact
    )


@mcp.tool
async def import_state(
    browser: str,
    path: str,
    kinds: list[Literal["cookies", "bookmarks", "credentials", "storage"]] | None = None,
    dry_run: bool = True,
) -> dict[str, int]:
    """Import a file produced by export_state. ONLY on explicit user request
    (dry_run=False)."""
    return await statefile.import_state(
        get_driver(browser), Path(path), kinds=kinds, dry_run=dry_run
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
