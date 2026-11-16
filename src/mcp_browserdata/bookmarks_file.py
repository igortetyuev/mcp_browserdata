"""Chromium `Bookmarks` JSON store.

Reads are safe while the browser runs. Writes must happen with the browser
quit — Chrome/Yandex rewrite the file on exit and would clobber our edits.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from mcp_browserdata.models import Bookmark

_ROOTS = ("bookmark_bar", "other", "synced")
_ROOT_TITLES = {
    "bookmark_bar": "Bookmarks bar",
    "other": "Other bookmarks",
    "synced": "Mobile bookmarks",
}


def read_bookmarks(path: Path) -> list[Bookmark]:
    data = json.loads(path.read_text())
    out: list[Bookmark] = []

    def walk(node: dict, folder: tuple[str, ...]) -> None:
        for child in node.get("children", []):
            if child.get("type") == "folder":
                walk(child, (*folder, child.get("name") or ""))
            elif child.get("url"):
                try:
                    added = int(child.get("date_added") or 0)
                except (TypeError, ValueError):
                    added = 0
                out.append(
                    Bookmark(
                        url=child["url"],
                        title=child.get("name") or "",
                        folder=folder,
                        date_added=(added - 11644473600000000) / 1e6 if added else None,
                    )
                )

    for root in _ROOTS:
        node = data.get("roots", {}).get(root)
        if node:
            walk(node, (_ROOT_TITLES[root],))
    return out


def add_bookmarks(path: Path, bookmarks: list[Bookmark]) -> int:
    """Merge bookmarks into the file, dedup by URL. Browser must be quit."""
    data = json.loads(path.read_text())
    existing: set[str] = set()
    for b in read_bookmarks(path):
        existing.add(_norm(b.url))

    def next_id() -> str:
        data["next_id"] = str(int(data.get("next_id") or "1") + 1)
        return data["next_id"]

    def folder_node(names: tuple[str, ...]) -> dict:
        root_key = "bookmark_bar"
        if names and names[0] in _ROOT_TITLES.values():
            key_by_title = {v: k for k, v in _ROOT_TITLES.items()}
            root_key = key_by_title[names[0]]
            names = names[1:]
        node = data["roots"][root_key]
        node.setdefault("children", [])
        for name in names:
            for child in node["children"]:
                if child.get("type") == "folder" and child.get("name") == name:
                    node = child
                    break
            else:
                folder = {
                    "type": "folder",
                    "name": name,
                    "id": next_id(),
                    "guid": str(uuid.uuid4()),
                    "date_added": "0",
                    "date_modified": "0",
                    "children": [],
                }
                node["children"].append(folder)
                node = folder
            node.setdefault("children", [])
        return node

    added = 0
    for b in bookmarks:
        if _norm(b.url) in existing:
            continue
        node = folder_node(b.folder)
        node["children"].append(
            {
                "type": "url",
                "name": b.title,
                "url": b.url,
                "id": next_id(),
                "guid": str(uuid.uuid4()),
                "date_added": str(int((b.date_added or 0) * 1e6) + 11644473600000000),
            }
        )
        existing.add(_norm(b.url))
        added += 1
    if added:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=3))
    return added


def _norm(url: str) -> str:
    return url.rstrip("/").lower()
