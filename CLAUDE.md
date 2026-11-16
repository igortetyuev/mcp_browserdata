# mcp-browserdata

Stdio MCP server (FastMCP) for reading/writing/syncing cookies, passwords,
bookmarks and local/session storage across installed browsers. Secrets move
inside the server process — sync/export tools return counters only.

## Commands

```bash
uv sync
uv run pytest                  # unit tests only
uv run pytest -m live          # touches real Chrome/Yandex (keychain prompts)
uv run ruff check
uv run mcp-browserdata         # the MCP server (stdio)
```

## Browser registry / access channels

| browser | profile | access |
|---|---|---|
| `chrome` | `~/Library/Application Support/Google/Chrome` | CDP live (DevToolsActivePort, inspect-mode endpoint) + files |
| `yandex` | `~/Library/Application Support/Yandex/YandexBrowser` | files only (no DevToolsActivePort unless relaunched with `--remote-debugging-port`) |
| `chromium` | `~/Library/Application Support/Chromium` | same, profile nearly empty |
| `safari` | `~/Library/Safari` + container `…/com.apple.Safari/…` | files, needs **Full Disk Access** for the MCP host app |
| `obscura` | none (in-memory jar) | spawned child `obscura --stealth mcp` via fastmcp.Client |

- Chromium cookie/login values: `v10` + AES-128-CBC, key = PBKDF2(keychain
  `"<X> Safe Storage"` password, salt `saltysalt`, iter 1003), IV=16 spaces.
  Cookie plaintext = SHA256(host)‖value (Chrome 80+); login plaintext = bare
  password. Keychain prompt fires once per requesting binary.
- CDP on the inspect-mode endpoint: `Browser.getVersion`, `Target.createTarget/
  attachToTarget(flatten)/closeTarget`, `Runtime.*`, `Network.*`,
  `Storage.getCookies` **and** `Storage.setCookies` — all verified live.
  Target enumeration is blocked; a new WS connection needs an Allow click in
  the browser window (60s timeout = "go click Allow").
- Site storage: per-origin background tab + `localStorage`/`sessionStorage`
  JS; for Chromium→Chromium with both quit, sync raw-copies the
  `Local Storage/leveldb` and `Session Storage` dirs.
- Safari `Cookies.binarycookies`: parser+writer in `binarycookies.py`
  (single-page build, `.bak` before replace, Safari must be quit).
  Bookmarks = `~/Library/Safari/Bookmarks.plist` (plistlib). Passwords =
  `security find/add-internet-password` per-site only (iCloud keychain isn't
  bulk-readable).

## Merge semantics (`sync_data`)

- keys: cookie `(domain,path,name)`, credential `(origin,username)`, bookmark
  normalized URL, storage per-origin key.
- conflicts → `newest` (later cookie expires / max(date_last_used,created)),
  or `prefer_src|prefer_dst|skip`. `direction=merge|src_to_dst|dst_to_src`,
  `dry_run=True` by default — returns `SyncStats` counters + notes.

## Gotchas

- File writes require the browser QUIT (sqlite lock / clobber-on-exit):
  BrowserRunningError names the app to quit.
- obscura's `browser_set_cookie` drops expires/sameSite — bulk writes go
  through `browser_set_storage_state`; export may normalize domain
  (`.x`→`x`) and report http_only=False.
- `Login Data For Account` (Google-account-scoped store) is read but never
  written; writes go to classic `Login Data`.
- Syncing live sessions copies refresh tokens → rotation races invalidate
  one side. Copy right before use.
