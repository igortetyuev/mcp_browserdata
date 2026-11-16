import time

import pytest

from mcp_browserdata import sync
from mcp_browserdata.errors import UnsupportedKindError
from mcp_browserdata.models import Bookmark, Cookie, Credential, SiteStorage


class FakeDriver:
    kind = "fake"

    def __init__(self, name):
        self.name = name
        self.cookies = {}
        self.bookmarks = {}
        self.creds = {}
        self.storage = {}

    async def get_cookies(self, domain=None):
        return list(self.cookies.values())

    async def set_cookies(self, cookies):
        for c in cookies:
            self.cookies[c.key] = c
        return len(cookies)

    async def get_bookmarks(self):
        return list(self.bookmarks.values())

    async def add_bookmarks(self, bookmarks):
        for b in bookmarks:
            self.bookmarks[b.url.rstrip("/").lower()] = b
        return len(bookmarks)

    async def get_credentials(self, domain=None):
        return list(self.creds.values())

    async def set_credentials(self, creds):
        for c in creds:
            self.creds[c.key] = c
        return len(creds)

    async def get_site_storage(self, origin, include_session=False):
        if origin not in self.storage:
            raise UnsupportedKindError(self.name, "storage")
        return self.storage[origin]

    async def set_site_storage(self, storage):
        self.storage[storage.origin] = storage
        return len(storage.local) + len(storage.session)


def ck(name, value, domain=".x.io", expires=None):
    return Cookie(name=name, value=value, domain=domain, expires=expires)


@pytest.mark.asyncio
async def test_cookies_merge_both_ways():
    a, b = FakeDriver("a"), FakeDriver("b")
    a.cookies[("d.io", "/", "only_a")] = ck("only_a", "1", "d.io")
    b.cookies[("d.io", "/", "only_b")] = ck("only_b", "2", "d.io")
    stats = (await sync.sync_data(a, b, kinds=["cookies"], dry_run=False))[0]
    assert stats.written_src == 1 and stats.written_dst == 1
    assert len(a.cookies) == 2 and len(b.cookies) == 2


@pytest.mark.asyncio
async def test_cookies_conflict_newest_expiry_wins():
    a, b = FakeDriver("a"), FakeDriver("b")
    key = ("d.io", "/", "tok")
    a.cookies[key] = ck("tok", "old", "d.io", expires=time.time() + 1000)
    b.cookies[key] = ck("tok", "new", "d.io", expires=time.time() + 2000)
    stats = (await sync.sync_data(a, b, kinds=["cookies"], dry_run=False))[0]
    assert stats.conflicts == 1
    assert a.cookies[key].value == "new" and b.cookies[key].value == "new"


@pytest.mark.asyncio
async def test_cookies_src_to_dst_direction():
    a, b = FakeDriver("a"), FakeDriver("b")
    a.cookies[("d.io", "/", "x")] = ck("x", "1", "d.io")
    stats = (
        await sync.sync_data(a, b, kinds=["cookies"], direction="src_to_dst", dry_run=False)
    )[0]
    assert stats.written_dst == 1 and stats.written_src == 0
    assert len(b.cookies) == 1


@pytest.mark.asyncio
async def test_dry_run_writes_nothing():
    a, b = FakeDriver("a"), FakeDriver("b")
    a.cookies[("d.io", "/", "x")] = ck("x", "1", "d.io")
    stats = (await sync.sync_data(a, b, kinds=["cookies"], dry_run=True))[0]
    assert stats.written_dst == 1  # planned
    assert len(b.cookies) == 0  # but not written


@pytest.mark.asyncio
async def test_expired_cookies_skipped():
    a, b = FakeDriver("a"), FakeDriver("b")
    a.cookies[("d.io", "/", "old")] = ck("old", "v", "d.io", expires=1)
    stats = (await sync.sync_data(a, b, kinds=["cookies"], dry_run=False))[0]
    assert stats.read_src == 0 and len(b.cookies) == 0


@pytest.mark.asyncio
async def test_bookmarks_dedup_by_url():
    a, b = FakeDriver("a"), FakeDriver("b")
    a.bookmarks["https://u.io"] = Bookmark(url="https://u.io/", title="U")
    b.bookmarks["https://v.io"] = Bookmark(url="https://v.io/", title="V")
    await sync.sync_data(a, b, kinds=["bookmarks"], dry_run=False)
    assert set(a.bookmarks) == set(b.bookmarks) == {"https://u.io", "https://v.io"}


@pytest.mark.asyncio
async def test_credentials_conflict_last_used():
    a, b = FakeDriver("a"), FakeDriver("b")
    key = ("https://x.io", "u")
    a.creds[key] = Credential(origin="https://x.io", username="u", password="p_old",
                            date_last_used=100)
    b.creds[key] = Credential(origin="https://x.io", username="u", password="p_new",
                              date_last_used=200)
    await sync.sync_data(a, b, kinds=["credentials"], dry_run=False)
    assert a.creds[key].password == "p_new" and b.creds[key].password == "p_new"


@pytest.mark.asyncio
async def test_storage_merge_per_origin():
    a, b = FakeDriver("a"), FakeDriver("b")
    a.storage["https://x.io"] = SiteStorage("https://x.io", local={"k1": "a"}, session={})
    b.storage["https://x.io"] = SiteStorage("https://x.io", local={"k2": "b"}, session={})
    await sync.sync_data(a, b, kinds=["storage"], domain="https://x.io", dry_run=False)
    assert a.storage["https://x.io"].local == {"k1": "a", "k2": "b"}
    assert b.storage["https://x.io"].local == {"k1": "a", "k2": "b"}


@pytest.mark.asyncio
async def test_storage_requires_origin_for_fake():
    a, b = FakeDriver("a"), FakeDriver("b")
    stats = (await sync.sync_data(a, b, kinds=["storage"], dry_run=True))[0]
    assert stats.notes and "requires domain" in stats.notes[0]
