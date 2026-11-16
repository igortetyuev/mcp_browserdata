"""Merge/copy engine — moves data between two drivers server-side.

Values never leave the process: tools get back only SyncStats counters.
"""

from __future__ import annotations

import shutil
import time
from typing import Literal

from mcp_browserdata.drivers.base import BrowserDriver
from mcp_browserdata.drivers.chromium import ChromiumDriver
from mcp_browserdata.models import (
    ALL_KINDS,
    Bookmark,
    Cookie,
    Credential,
    DataKind,
    SiteStorage,
    SyncStats,
)

Direction = Literal["merge", "src_to_dst", "dst_to_src"]
Conflict = Literal["newest", "prefer_src", "prefer_dst", "skip"]


def _write_dir(direction: Direction) -> tuple[bool, bool]:
    """(write_to_src, write_to_dst)"""
    return direction in ("merge", "dst_to_src"), direction in ("merge", "src_to_dst")


async def sync_data(
    src: BrowserDriver,
    dst: BrowserDriver,
    kinds: list[DataKind] | None = None,
    domain: str | None = None,
    direction: Direction = "merge",
    dry_run: bool = True,
    conflict: Conflict = "newest",
) -> list[SyncStats]:
    stats: list[SyncStats] = []
    for kind in kinds or list(ALL_KINDS):
        fn = {
            "cookies": _sync_cookies,
            "bookmarks": _sync_bookmarks,
            "credentials": _sync_credentials,
            "storage": _sync_storage,
        }[kind]
        stats.append(await fn(src, dst, domain, direction, dry_run, conflict))
    return stats


# --- cookies ---


def _cookie_winner(a: Cookie, b: Cookie, conflict: Conflict) -> Cookie | None:
    """a is the src-side row, b the dst-side row."""
    if conflict == "prefer_src":
        return a
    if conflict == "prefer_dst":
        return b
    if conflict == "skip":
        return None
    ea = a.expires or float("inf")
    eb = b.expires or float("inf")
    return a if ea >= eb else b


async def _sync_cookies(src, dst, domain, direction, dry_run, conflict) -> SyncStats:
    st = SyncStats(kind="cookies")
    now = time.time()
    src_c = {c.key: c for c in await src.get_cookies(domain) if not c.is_expired(now)}
    dst_c = {c.key: c for c in await dst.get_cookies(domain) if not c.is_expired(now)}
    st.read_src, st.read_dst = len(src_c), len(dst_c)

    merged_src = dict(dst_c)  # what src should end up with
    merged_dst = dict(src_c)  # what dst should end up with
    for key in set(src_c) & set(dst_c):
        if src_c[key].value == dst_c[key].value:
            continue
        st.conflicts += 1
        winner = _cookie_winner(src_c[key], dst_c[key], conflict)
        if winner is not None:
            merged_src[key] = merged_dst[key] = winner

    w_src = [c for k, c in merged_src.items() if src_c.get(k) != c]
    w_dst = [c for k, c in merged_dst.items() if dst_c.get(k) != c]
    to_src, to_dst = _write_dir(direction)
    st.written_src = len(w_src) if to_src else 0
    st.written_dst = len(w_dst) if to_dst else 0
    if not dry_run:
        if to_src and w_src:
            st.written_src = await src.set_cookies(w_src)
        if to_dst and w_dst:
            st.written_dst = await dst.set_cookies(w_dst)
    return st


# --- bookmarks ---


def _bm_key(b: Bookmark) -> str:
    return b.url.rstrip("/").lower()


async def _sync_bookmarks(src, dst, domain, direction, dry_run, conflict) -> SyncStats:
    st = SyncStats(kind="bookmarks")
    src_b = {_bm_key(b): b for b in await src.get_bookmarks()}
    dst_b = {_bm_key(b): b for b in await dst.get_bookmarks()}
    if domain:
        q = domain.lower()
        src_b = {k: b for k, b in src_b.items() if q in k}
        dst_b = {k: b for k, b in dst_b.items() if q in k}
    st.read_src, st.read_dst = len(src_b), len(dst_b)

    missing_in_dst = [b for k, b in src_b.items() if k not in dst_b]
    missing_in_src = [b for k, b in dst_b.items() if k not in src_b]
    to_src, to_dst = _write_dir(direction)
    st.written_src = len(missing_in_src) if to_src else 0
    st.written_dst = len(missing_in_dst) if to_dst else 0
    if not dry_run:
        if to_src and missing_in_src:
            st.written_src = await src.add_bookmarks(missing_in_src)
        if to_dst and missing_in_dst:
            st.written_dst = await dst.add_bookmarks(missing_in_dst)
    return st


# --- credentials ---


def _cred_winner(a: Credential, b: Credential, conflict: Conflict) -> Credential | None:
    if conflict == "prefer_src":
        return a
    if conflict == "prefer_dst":
        return b
    if conflict == "skip":
        return None
    ta = max(a.date_last_used or 0, a.date_created or 0)
    tb = max(b.date_last_used or 0, b.date_created or 0)
    return a if ta >= tb else b


async def _sync_credentials(src, dst, domain, direction, dry_run, conflict) -> SyncStats:
    st = SyncStats(kind="credentials")
    src_c = {c.key: c for c in await src.get_credentials(domain)}
    dst_c = {c.key: c for c in await dst.get_credentials(domain)}
    st.read_src, st.read_dst = len(src_c), len(dst_c)

    merged_src = dict(dst_c)
    merged_dst = dict(src_c)
    for key in set(src_c) & set(dst_c):
        if src_c[key].password == dst_c[key].password:
            continue
        st.conflicts += 1
        winner = _cred_winner(src_c[key], dst_c[key], conflict)
        if winner is not None:
            merged_src[key] = merged_dst[key] = winner

    w_src = [c for k, c in merged_src.items() if src_c.get(k) != c]
    w_dst = [c for k, c in merged_dst.items() if dst_c.get(k) != c]
    to_src, to_dst = _write_dir(direction)
    st.written_src = len(w_src) if to_src else 0
    st.written_dst = len(w_dst) if to_dst else 0
    if not dry_run:
        if to_src and w_src:
            st.written_src = await src.set_credentials(w_src)
        if to_dst and w_dst:
            st.written_dst = await dst.set_credentials(w_dst)
    return st


# --- site storage ---


async def _sync_storage(src, dst, domain, direction, dry_run, conflict) -> SyncStats:
    st = SyncStats(kind="storage")
    to_src, to_dst = _write_dir(direction)

    # Fast path: Chromium→Chromium bulk raw copy (both quit, no origin filter).
    if (
        domain is None
        and isinstance(src, ChromiumDriver)
        and isinstance(dst, ChromiumDriver)
    ):
        if src.is_running() or dst.is_running():
            st.notes.append(
                "raw leveldb copy needs both browsers quit; pass domain=<origin> "
                "for per-origin sync over CDP instead"
            )
            return st
        if dry_run:
            st.notes.append("would copy Local Storage/leveldb and Session Storage dirs")
            return st
        return _raw_storage_copy(src, dst, direction, st)

    if domain is None:
        st.notes.append(
            "storage sync requires domain=<origin> unless both browsers are quit Chromium"
        )
        return st

    src_s = await src.get_site_storage(domain, include_session=True)
    dst_s = await dst.get_site_storage(domain, include_session=True)
    st.read_src = len(src_s.local) + len(src_s.session)
    st.read_dst = len(dst_s.local) + len(dst_s.session)

    def merge(a: dict, b: dict) -> dict:
        out = dict(b)
        for k, v in a.items():
            if k in out and out[k] != v:
                st.conflicts += 1
                if conflict in ("newest", "prefer_src"):
                    out[k] = v
                elif conflict == "prefer_dst":
                    pass
            elif k not in out:
                out[k] = v
        return out

    merged_local = merge(src_s.local, dst_s.local)
    merged_session = merge(src_s.session, dst_s.session)
    w_src = SiteStorage(domain, merged_local, merged_session)
    w_dst = SiteStorage(domain, merged_local, merged_session)
    n = len(merged_local) + len(merged_session)
    st.written_src = n if to_src else 0
    st.written_dst = n if to_dst else 0
    if not dry_run:
        if to_src:
            st.written_src = await src.set_site_storage(w_src)
        if to_dst:
            st.written_dst = await dst.set_site_storage(w_dst)
    return st


def _raw_storage_copy(
    src: ChromiumDriver, dst: ChromiumDriver, direction: Direction, st: SyncStats
) -> SyncStats:
    """Copy Local Storage/Session Storage trees wholesale (both quit)."""
    src_dirs, dst_dirs = src.raw_storage_dirs(), dst.raw_storage_dirs()
    for name in ("local", "session"):
        for frm, to in ((src_dirs, dst_dirs), (dst_dirs, src_dirs)):
            if frm is src_dirs and direction == "dst_to_src":
                continue
            if frm is dst_dirs and direction == "src_to_dst":
                continue
            src_dir, dst_dir = frm[name], to[name]
            if not src_dir.exists():
                continue
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)
            st.notes.append(f"copied {name} storage {src_dir} → {dst_dir}")
    st.written_dst = 1 if direction != "dst_to_src" else 0
    st.written_src = 1 if direction != "src_to_dst" else 0
    return st
