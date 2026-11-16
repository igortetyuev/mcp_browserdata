"""Safari profile file paths and Full Disk Access checks."""

from __future__ import annotations

import plistlib
import uuid
from pathlib import Path

from mcp_browserdata.errors import NeedsFullDiskAccessError
from mcp_browserdata.models import Bookmark

HOME = Path.home()
COOKIES_PATH = (
    HOME
    / "Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies"
)
BOOKMARKS_PATH = HOME / "Library/Safari/Bookmarks.plist"


def readable(path: Path) -> bool:
    try:
        path.open("rb").close()
        return True
    except OSError:
        return False


def require_fda(path: Path) -> None:
    if not readable(path):
        raise NeedsFullDiskAccessError(str(path))


def read_bookmarks(path: Path = BOOKMARKS_PATH) -> list[Bookmark]:
    require_fda(path)
    data = plistlib.loads(path.read_bytes())
    out: list[Bookmark] = []

    def walk(node: dict, folder: tuple[str, ...]) -> None:
        if node.get("WebBookmarkType") == "WebBookmarkTypeLeaf":
            url = node.get("URLString")
            if url:
                out.append(
                    Bookmark(
                        url=url,
                        title=(node.get("URIDictionary") or {}).get("title", ""),
                        folder=folder,
                    )
                )
        else:
            title = node.get("Title") or ""
            child_folder = (*folder, title) if title else folder
            for child in node.get("Children", []):
                walk(child, child_folder)

    walk(data, ())
    return out


def add_bookmarks(
    bookmarks: list[Bookmark], path: Path = BOOKMARKS_PATH
) -> int:
    """Append missing bookmarks (dedup by URL) into a flat 'Imported' folder."""
    require_fda(path)
    data = plistlib.loads(path.read_bytes())
    existing = {b.url.rstrip("/").lower() for b in read_bookmarks(path)}
    root_children = data.setdefault("Children", [])
    imported = next(
        (
            c
            for c in root_children
            if c.get("WebBookmarkType") == "WebBookmarkTypeList"
            and c.get("Title") == "Imported"
        ),
        None,
    )
    if imported is None:
        imported = {
            "WebBookmarkType": "WebBookmarkTypeList",
            "Title": "Imported",
            "WebBookmarkUUID": str(uuid.uuid4()).upper(),
            "Children": [],
        }
        root_children.append(imported)
    added = 0
    for b in bookmarks:
        if b.url.rstrip("/").lower() in existing:
            continue
        imported.setdefault("Children", []).append(
            {
                "WebBookmarkType": "WebBookmarkTypeLeaf",
                "URLString": b.url,
                "URIDictionary": {"title": b.title},
                "WebBookmarkUUID": str(uuid.uuid4()).upper(),
            }
        )
        existing.add(b.url.rstrip("/").lower())
        added += 1
    if added:
        path.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY))
    return added
