"""Normalized data models exchanged between browser drivers and the sync engine."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

DataKind = Literal["cookies", "bookmarks", "credentials", "storage"]
ALL_KINDS: tuple[DataKind, ...] = ("cookies", "bookmarks", "credentials", "storage")


@dataclass
class Cookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    expires: float | None = None  # unix seconds; None = session cookie
    secure: bool = False
    http_only: bool = False
    same_site: str | None = None  # "Lax" | "Strict" | "None"

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.domain.lower(), self.path, self.name)

    def is_expired(self, now: float) -> bool:
        return self.expires is not None and self.expires <= now


@dataclass
class Credential:
    origin: str  # scheme://host[:port]
    username: str
    password: str
    url: str | None = None  # full signon realm / action url
    date_created: float | None = None  # unix seconds
    date_last_used: float | None = None
    times_used: int = 0

    @property
    def key(self) -> tuple[str, str]:
        return (self.origin, self.username)


@dataclass
class Bookmark:
    url: str
    title: str
    folder: tuple[str, ...] = ()  # path from root, e.g. ("Bookmarks bar", "Work")
    date_added: float | None = None


@dataclass
class SiteStorage:
    origin: str
    local: dict[str, str] = field(default_factory=dict)
    session: dict[str, str] = field(default_factory=dict)


@dataclass
class BrowserInfo:
    """What list_browsers() reports."""

    name: str
    kind: str  # "chromium" | "safari" | "obscura"
    profile_dir: str | None
    running: bool
    cdp: bool
    file_access: str  # "ok" | "needs_fda" | "missing"
    capabilities: dict[str, dict[str, bool]]  # kind -> {"read":…, "write":…}


@dataclass
class SyncStats:
    kind: str
    read_src: int = 0
    read_dst: int = 0
    written_src: int = 0
    written_dst: int = 0
    conflicts: int = 0
    skipped: int = 0
    notes: list[str] = field(default_factory=list)


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, list | tuple | set):
        return [to_jsonable(i) for i in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, float | int | str | bool) or obj is None:
        return obj
    return json.loads(json.dumps(obj, default=str))
