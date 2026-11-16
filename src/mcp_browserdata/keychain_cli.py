"""Safari passwords via the `security` CLI (best-effort).

Safari credentials live in the iCloud keychain; `security` sees a subset of
items and may raise a per-item UI prompt. Bulk enumeration is not possible —
lookups are per-site only.
"""

from __future__ import annotations

import re
import subprocess
from urllib.parse import urlparse

from mcp_browserdata.models import Credential


def _host(url: str) -> str:
    return urlparse(url if "://" in url else f"https://{url}").hostname or url


def get_credential(url: str, username: str | None = None) -> Credential | None:
    """Look up one site password. Returns None when not found/readable."""
    cmd = ["security", "find-internet-password", "-s", _host(url), "-g"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return None
    acct = re.search(r'"acct"<blob>="([^"]*)"', proc.stdout)
    pw = re.search(r'^password: "(.*)"$', proc.stderr + proc.stdout, re.M)
    return Credential(
        origin=f"https://{_host(url)}",
        username=acct.group(1) if acct else (username or ""),
        password=pw.group(1) if pw else "",
    )


def set_credential(cred: Credential) -> bool:
    """Add/update an internet-password item. Best-effort: lands in the login
    keychain, which is NOT the store Safari syncs to iCloud."""
    host = _host(cred.origin)
    # -U updates in place when the item already exists
    proc = subprocess.run(
        [
            "security",
            "add-internet-password",
            "-s",
            host,
            "-a",
            cred.username,
            "-w",
            cred.password,
            "-r",
            "http",
            "-U",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode == 0
