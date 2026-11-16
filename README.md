# mcp-browserdata

MCP server (stdio, FastMCP) that reads, writes, copies and syncs cookies,
passwords, bookmarks and local/session storage between installed browsers:
Chrome, Yandex Browser, Chromium, Safari (best-effort) and obscura.

Secrets never enter the LLM transcript: `sync_data` / `export_state` move
values inside the server process and return counters. `get_*` tools mask
values unless `reveal=True` is passed.

## Install / run

```bash
uv sync
uv run mcp-browserdata     # stdio MCP server
```

Register in your MCP host as a stdio server: `uv run --directory <repo> mcp-browserdata`.

## Tools

- `list_browsers()` — detected browsers, profile paths, running/CDP/file-access state, capability matrix.
- `get_cookies(browser, domain?, reveal?)` / `set_cookies(browser, cookies)`
- `list_bookmarks(browser)` / `add_bookmark(browser, url, title, folder?)`
- `get_credentials(browser, domain?, reveal?)` / `set_credential(browser, origin, username, password)`
- `get_site_storage(browser, origin, include_session?, reveal?)` / `set_site_storage(...)`
- `sync_data(src, dst, kinds?, domain?, direction?, conflict?, dry_run?)` — merge or one-way copy; returns `SyncStats` counters.
- `export_state(browser, path, kinds?, origins?, redact?)` / `import_state(browser, path, kinds?, dry_run?)` — JSON file, chmod 600, values masked by default.

Browsers: `chrome`, `yandex`, `chromium`, `safari`, `obscura`.
Kinds: `cookies`, `bookmarks`, `credentials`, `storage`.

## Access notes

- **Chrome**: live read/write via CDP (remote debugging at chrome://inspect/#remote-debugging) and file-level decrypt via the "Chrome Safe Storage" keychain item.
- **Yandex**: file-level only (Cookies/Login Data/Bookmarks + "Yandex Safe Storage" keychain). Writes need Yandex quit.
- **Safari**: file access needs Full Disk Access for the host app; passwords are per-site via `security` CLI.
- **obscura**: state lives in the memory of a spawned `obscura --stealth mcp` child — ephemeral and unrelated to other obscura instances.
