# mcp-browserdata

MCP server (stdio, FastMCP) for reading, writing, copying and two-way syncing
**cookies, passwords, bookmarks and local/session storage** between installed
browsers: Google Chrome, Yandex Browser, Chromium, Safari (best-effort) and
obscura (a lightweight headless scraping browser).

Secret values move **inside the server process**: `sync_data` / `export_state`
return only counters, and `get_*` tools mask values unless `reveal=True` is
passed explicitly.

## How it reaches each browser

| Browser | Channel |
|---|---|
| `chrome` | Live CDP (Chrome inspect-mode remote debugging) **and** profile files + Keychain decrypt |
| `yandex` | Profile files (`Cookies`/`Login Data`/`Bookmarks` sqlite+JSON) + "Yandex Safe Storage" keychain decrypt |
| `chromium` | Same as Chrome when a profile exists |
| `safari` | `Cookies.binarycookies` + `Bookmarks.plist` (needs **Full Disk Access**), passwords per-site via `security` CLI |
| `obscura` | Spawns its own `obscura --stealth mcp` child and talks MCP to it |

Chromium `v10` blobs are AES-128-CBC with a key derived (PBKDF2, salt
`saltysalt`, 1003 iters) from the browser's `* Safe Storage` login-keychain
item — the macOS prompt appears once per requesting binary.

## Capability matrix

| Kind | Chrome | Yandex | obscura | Safari |
|---|---|---|---|---|
| cookies read | CDP live + file | file | MCP | file (FDA) |
| cookies write | CDP live | file — browser must quit | MCP | file — Safari must quit + FDA |
| bookmarks r/w | file — write needs quit | file — write needs quit | — | plist — needs FDA (+quit for write) |
| passwords read | file + decrypt | file + decrypt | — | per-site `security` |
| passwords write | file — browser must quit | file — browser must quit | — | `security` per-site |
| local/session storage | CDP per-origin tab; raw leveldb copy when quit | raw copy when quit | storage_state | — |

## Install

```bash
git clone <this repo> && cd mcp_browserdata
uv sync
```

## MCP client config

```json
{
  "mcpServers": {
    "browserdata": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp_browserdata", "mcp-browserdata"],
      "transport": "stdio"
    }
  }
}
```

## Tools

- `list_browsers()` — detected browsers, profile paths, running/CDP/FDA
  state, capability matrix.
- `get_cookies(browser, domain?, reveal?)` / `set_cookies(browser, cookies)`
- `list_bookmarks(browser)` / `add_bookmark(browser, url, title, folder?)`
- `get_credentials(browser, domain?, reveal?)` / `set_credential(browser, origin, username, password)`
- `get_site_storage(browser, origin, include_session?, reveal?)` / `set_site_storage(...)`
- `sync_data(src, dst, kinds?, domain?, direction?, conflict?, dry_run?)` —
  merge or one-way copy of `cookies | bookmarks | credentials | storage`;
  returns `SyncStats` counters only. `direction` = `merge | src_to_dst |
  dst_to_src`; `conflict` = `newest | prefer_src | prefer_dst | skip`;
  `dry_run` defaults to true.
- `export_state(browser, path, kinds?, origins?, redact?)` /
  `import_state(browser, path, kinds?, dry_run?)` — JSON file, chmod 600;
  values masked unless `redact=False`.

Merge keys: cookie `(domain, path, name)`, credential `(origin, username)`,
bookmark normalized URL, storage per-origin key.

## Requirements & permissions

- macOS; Python ≥ 3.12, [uv](https://docs.astral.sh/uv/)
- Chrome: remote debugging on (`chrome://inspect/#remote-debugging`) for live
  cookie/storage access; every new connection shows an Allow sheet in Chrome.
- Keychain prompts ("* Safe Storage") on first decrypt per binary.
- Safari: grant **Full Disk Access** to the app hosting this MCP server, or
  Safari tools degrade to per-site `security` lookups.
- Most **writes** need the target browser **quit** (sqlite locks, files
  clobbered on exit) — errors say which app to close.

## Security notes

- This server exists to move *your own* credentials between *your own*
  browsers. Treat its host app as trusted exactly like Keychain Access.
- Syncing a live session copies refresh tokens — two browsers sharing one
  account will invalidate each other on token rotation.
- `obscura` state is ephemeral (in-memory jar of a spawned child process) and
  unrelated to any other obscura instance your tools may run.

## Development

```bash
uv run pytest          # unit tests only
uv run pytest -m live  # touches real Chrome/Yandex/obscura (prompts!)
uv run ruff check
```

## License

MIT — see [LICENSE](LICENSE).
