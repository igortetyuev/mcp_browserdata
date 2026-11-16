"""localStorage/sessionStorage access.

Live path: per-origin background tab over CDP + Runtime.evaluate.
Bulk path: raw leveldb dir copy between two Chromium profiles (both quit) —
handled by sync.py via ChromiumDriver.raw_storage_dirs().
"""

from __future__ import annotations

import json

from mcp_browserdata.cdp import CdpSession
from mcp_browserdata.models import SiteStorage


async def cdp_get_storage(
    cdp: CdpSession, origin: str, include_session: bool = False
) -> SiteStorage:
    target_id, session_id = await cdp.attach_url(origin)
    try:
        local = await cdp.evaluate(
            session_id, "JSON.stringify(Object.entries(localStorage))"
        )
        session = (
            await cdp.evaluate(
                session_id, "JSON.stringify(Object.entries(sessionStorage))"
            )
            if include_session
            else "[]"
        )
        return SiteStorage(
            origin=origin,
            local=dict(json.loads(local or "[]")),
            session=dict(json.loads(session or "[]")),
        )
    finally:
        await cdp.close_target(target_id)


async def cdp_set_storage(cdp: CdpSession, storage: SiteStorage) -> int:
    target_id, session_id = await cdp.attach_url(storage.origin)
    try:
        payload = json.dumps({"local": storage.local, "session": storage.session})
        return int(
            await cdp.evaluate(
                session_id,
                "(()=>{const d="
                + payload
                + ";let n=0;"
                + "for(const[k,v]of Object.entries(d.local||{})){localStorage.setItem(k,v);n++}"
                + "for(const[k,v]of Object.entries(d.session||{})){sessionStorage.setItem(k,v);n++}"
                + "return n;})()",
            )
        )
    finally:
        await cdp.close_target(target_id)
