"""Safari Cookies.binarycookies format — parser and writer.

Layout (as of Safari 13+/Big Sur; still current):
  "cook" magic, page count (BE u32), page sizes (BE u32 each),
  pages: header 0x00000100 (LE), count, cookie offsets (LE, page-relative),
         4 zero bytes, then records.
  record (all LE): size, 1, flags, 0, url_off, name_off, path_off, value_off,
         8 zero bytes, expires f64, created f64 (Mac epoch 2001-01-01),
         then NUL-terminated strings at the given record-relative offsets.
  trailer: 8-byte little-endian checksum (sum of page sizes), then
         the 4-byte tail constant 0x07172005.
flags: bit0 secure, bit2 httpOnly.
"""

from __future__ import annotations

import struct
import time
from pathlib import Path

from mcp_browserdata.models import Cookie

MAC_EPOCH = 978307200  # seconds between 1970-01-01 and 2001-01-01
_PAGE_HEADER = 0x00000100
_TRAILER_MAGIC = b"\x05\x20\x17\x07"  # 0x07172005 little-endian

_FLAG_SECURE = 1
_FLAG_HTTPONLY = 4


def parse(data: bytes) -> list[Cookie]:
    if data[:4] != b"cook":
        raise ValueError("not a binarycookies file")
    num_pages = struct.unpack_from(">I", data, 4)[0]
    sizes = struct.unpack_from(f">{num_pages}I", data, 8)
    pos = 8 + 4 * num_pages
    out: list[Cookie] = []
    for size in sizes:
        page = data[pos : pos + size]
        pos += size
        (header,) = struct.unpack_from("<I", page, 0)
        if header != _PAGE_HEADER:
            continue
        (count,) = struct.unpack_from("<I", page, 4)
        offsets = struct.unpack_from(f"<{count}I", page, 8)
        for off in offsets:
            out.append(_parse_record(page, off))
    return out


def _cstr(buf: bytes, off: int) -> str:
    end = buf.index(b"\x00", off)
    return buf[off:end].decode("utf-8", errors="replace")


def _parse_record(page: bytes, off: int) -> Cookie:
    (size, _u1, flags, _u2, url_off, name_off, path_off, value_off) = struct.unpack_from(
        "<8I", page, off
    )
    expires, _created = struct.unpack_from("<dd", page, off + 40)
    rec = page[off : off + size]
    return Cookie(
        name=_cstr(rec, name_off),
        value=_cstr(rec, value_off),
        domain=_cstr(rec, url_off),
        path=_cstr(rec, path_off) or "/",
        expires=expires + MAC_EPOCH if expires else None,
        secure=bool(flags & _FLAG_SECURE),
        http_only=bool(flags & _FLAG_HTTPONLY),
    )


def build(cookies: list[Cookie]) -> bytes:
    """Serialize cookies into a single-page binarycookies file."""
    records = [_build_record(c) for c in cookies]
    header_len = 4 + 4 + 4 * len(records) + 4
    offsets = []
    pos = header_len
    for rec in records:
        offsets.append(pos)
        pos += len(rec)
    page = (
        struct.pack("<II", _PAGE_HEADER, len(records))
        + b"".join(struct.pack("<I", o) for o in offsets)
        + b"\x00" * 4
        + b"".join(records)
    )
    checksum = len(page)
    return (
        b"cook"
        + struct.pack(">I", 1)
        + struct.pack(">I", len(page))
        + page
        + struct.pack("<Q", checksum)
        + _TRAILER_MAGIC
    )


def _build_record(c: Cookie) -> bytes:
    strings = b"".join(
        s.encode() + b"\x00" for s in (c.domain, c.name, c.path, c.value)
    )
    header_len = 56
    url_off, name_off, path_off, value_off = (
        header_len,
        header_len + len(c.domain) + 1,
        header_len + len(c.domain) + len(c.name) + 2,
        header_len + len(c.domain) + len(c.name) + len(c.path) + 3,
    )
    flags = (c.secure * _FLAG_SECURE) | (c.http_only * _FLAG_HTTPONLY)
    expires = (c.expires - MAC_EPOCH) if c.expires else 0.0
    created = time.time() - MAC_EPOCH
    size = header_len + len(strings)
    head = struct.pack(
        "<8I", size, 1, flags, 0, url_off, name_off, path_off, value_off
    )
    return head + b"\x00" * 8 + struct.pack("<dd", expires, created) + strings


def read_file(path: Path) -> list[Cookie]:
    return parse(path.read_bytes())


def write_file(path: Path, cookies: list[Cookie]) -> int:
    import shutil
    import tempfile

    if path.exists():
        shutil.copy2(path, path.with_suffix(".binarycookies.bak-mcpbrowserdata"))
    with tempfile.NamedTemporaryFile(
        dir=path.parent, delete=False, prefix=".binarycookies."
    ) as tmp:
        tmp.write(build(cookies))
    Path(tmp.name).replace(path)
    return len(cookies)
