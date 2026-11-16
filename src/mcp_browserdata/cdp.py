"""Minimal CDP client for Chromium browsers via inspect-mode remote debugging.

Generalized from mcp_ozon.cdp: same restricted endpoint (Browser.getVersion,
Target.createTarget/attachToTarget(flatten)/closeTarget, Runtime.*, Network.*,
Storage.* — target enumeration is blocked), plus helpers for per-origin
background tabs (local/session storage access) and cookie jar read/write.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from mcp_browserdata.errors import BrowserDataError, CdpUnavailableError

ALLOW_TIMEOUT_S = 60.0
CMD_TIMEOUT_S = 30.0
LOAD_TIMEOUT_S = 30.0


class CdpError(BrowserDataError):
    pass


def discover_ws_url(profile_dir: Path) -> str:
    """Read <profile>/DevToolsActivePort and build the browser websocket URL."""
    port_file = profile_dir / "DevToolsActivePort"
    try:
        port, path = port_file.read_text().splitlines()[:2]
    except (FileNotFoundError, ValueError) as exc:
        raise CdpUnavailableError(
            f"remote debugging is off for {profile_dir.name} ({port_file} not found)"
        ) from exc
    return f"ws://127.0.0.1:{port.strip()}{path.strip()}"


class CdpSession:
    """Browser-level CDP connection; page-level commands go through session_id."""

    def __init__(self, profile_dir: Path, ws_url: str | None = None) -> None:
        self._profile_dir = profile_dir
        self._ws_url = ws_url
        self._ws: Any = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._listeners: dict[str, list[Callable[[dict, str | None], None]]] = {}
        self._reader: asyncio.Task | None = None

    async def connect(self) -> None:
        if self._ws_url is None:
            self._ws_url = discover_ws_url(self._profile_dir)
        try:
            async with asyncio.timeout(ALLOW_TIMEOUT_S):
                self._ws = await connect(self._ws_url, max_size=64 * 2**20, open_timeout=30)
                self._reader = asyncio.create_task(self._read_loop())
                await self.send("Browser.getVersion")
        except (TimeoutError, ConnectionClosed, OSError) as exc:
            await self.close()
            raise CdpError(
                "No answer from the browser within 60s — click Allow on the remote "
                "debugging prompt in the browser window and retry."
            ) from exc

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(CdpError("connection closed"))
        self._pending.clear()

    async def __aenter__(self) -> CdpSession:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def on(self, method: str, cb: Callable[[dict, str | None], None]) -> None:
        self._listeners.setdefault(method, []).append(cb)

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut is not None and not fut.done():
                        if "error" in msg:
                            fut.set_exception(CdpError(msg["error"].get("message", "CDP error")))
                        else:
                            fut.set_result(msg.get("result", {}))
                else:
                    for cb in self._listeners.get(msg.get("method", ""), ()):
                        cb(msg.get("params", {}), msg.get("sessionId"))
        except (ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(CdpError("connection closed"))
            self._pending.clear()

    async def send(
        self, method: str, params: dict | None = None, session_id: str | None = None
    ) -> dict:
        if self._ws is None:
            raise CdpError("not connected")
        self._next_id += 1
        msg_id = self._next_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        payload: dict[str, Any] = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        await self._ws.send(json.dumps(payload))
        async with asyncio.timeout(CMD_TIMEOUT_S):
            return await fut

    async def attach_url(self, url: str, background: bool = True) -> tuple[str, str]:
        """Create a (background) tab on `url`, attach, wait for load. Returns
        (target_id, session_id). Caller must close_target() when done."""
        res = await self.send("Target.createTarget", {"url": url, "background": background})
        target_id = res["targetId"]
        res = await self.send(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        session_id = res["sessionId"]
        await self.send("Runtime.enable", session_id=session_id)
        async with asyncio.timeout(LOAD_TIMEOUT_S):
            while await self.evaluate(session_id, "document.readyState") != "complete":
                await asyncio.sleep(0.3)
        return target_id, session_id

    async def close_target(self, target_id: str) -> None:
        with contextlib.suppress(CdpError, ConnectionClosed, TimeoutError):
            await self.send("Target.closeTarget", {"targetId": target_id})

    async def evaluate(self, session_id: str, expression: str) -> Any:
        res = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
            session_id=session_id,
        )
        if "exceptionDetails" in res:
            detail = res["exceptionDetails"]
            desc = (detail.get("exception") or {}).get("description") or detail.get("text")
            raise CdpError(f"JS exception: {desc}")
        return res.get("result", {}).get("value")

    # --- cookie jar ---

    async def get_cookies(self, urls: list[str] | None = None) -> list[dict]:
        """All cookies (HttpOnly included) via Storage domain.
        With `urls`, scoped to those URLs via Network domain (needs a session)."""
        if urls is None:
            res = await self.send("Storage.getCookies")
            return res.get("cookies", [])
        target_id, session_id = await self.attach_url(urls[0])
        try:
            res = await self.send(
                "Network.getCookies", {"urls": urls}, session_id=session_id
            )
            return res.get("cookies", [])
        finally:
            await self.close_target(target_id)

    async def set_cookies(self, cookies: list[dict]) -> int:
        """Write cookies into the jar via Storage.setCookies (browser-level).
        Returns count accepted (CDP does not report per-cookie status)."""
        if not cookies:
            return 0
        await self.send("Storage.setCookies", {"cookies": cookies})
        return len(cookies)
