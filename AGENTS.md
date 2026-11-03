# AGENTS.md

Guide for AI coding agents and human contributors. `CLAUDE.md` imports this file, so keep every shared rule here.

## What this is

who-is-home shows who is on a home network, how much each device is used and which sites it looks up. One Python process (`who_is_home.py`) runs:

1. **Collector** (`Collector`), with one thread per job:
   - `scan`: pings the subnet in parallel and reads the ARP table (`arp -anl` on macOS). A ping reply or a valid ARP entry marks a device as seen. Devices without a signal for `offline_minutes` go offline.
   - `poll`: reads AdGuard Home's `/control/querylog` (basic auth), maps each client IP to a MAC and calls `ingest`.
   - `names`: mDNS reverse lookup, NetBIOS node status and AdGuard clients.
   - `maintenance`: pruning (`keep_days`) and the weekly summary.
2. **HTTP server** (`Handler`): the dashboard (`static/`) and a JSON API on the LAN.
3. **Notifier**: ntfy alerts through the system `curl`.

`ingest` aggregates lookups into `domains` (per day, device and site), `hourly` (per day, device and hour) and `activity` (one row per device-minute "in use"). A minute is "in use" when the device made at least `activity_min_queries` unblocked lookups outside `PASSIVE_CATEGORIES`.

## Hard constraints

- **Python 3.8 compatible** (Command Line Tools Python on macOS 11). Check with
  `python3 -c "import ast; ast.parse(open('who_is_home.py').read(), feature_version=(3, 8))"`.
- **Standard library only.** No pip packages.
- **SQLite without UPSERT**: use `INSERT OR IGNORE` + `UPDATE` (older system SQLite).
- **The frontend must work offline.** Vanilla JS and CSS, no CDNs, no web fonts.
- **Strict CSP** (`script-src 'self'`): no inline `<script>` and no inline event handlers. Inline `style` is allowed.
- **Static files are allow-listed** in `STATIC_FILES`.
- **Never commit `dados/`**: it holds the AdGuard password and the ntfy topic.
- **Every user-visible text exists in en, pt and zh** (`static/i18n.js` and `TEXTS`). `tests/test_i18n.py` checks parity.
- **Never return the AdGuard credentials** from the API.

## Security rules

- Domain names and hostnames are attacker-controlled. Escape them with `WH.esc()` before `innerHTML`.
- Keep the `Host` allow-list, the `X-Who-Is-Home: 1` header on POSTs and `SECURITY_HEADERS`.
- Subprocesses always take argument lists. Never use `shell=True`.

## Layout

```
who_is_home.py        collector, AdGuard client, names, statistics, HTTP handler, CLI
static/index.html     dashboard          static/app.js       dashboard logic
static/device.html    device page        static/device.js    device logic
static/common.js      shared helpers (WH.*): i18n, theme, formatting, charts, tooltips
static/i18n.js        UI strings for en / pt / zh
static/style.css      styles; light/dark tokens on :root (same look as down-again)
tests/                parsers, translations, static files, statistics
tools/demo.py         demo server with 7 days of simulated data (temp dir, port 8767)
tools/icons.py        regenerates static/icon.svg and the PNG icons
tools/capture.mjs     regenerates docs/<lang>/ images (cover, screenshots, GIF) via headless Chrome + ffmpeg
tools/cover.html      cover template (one per language via ?lang=)
docs/<lang>/          README images per language: cover.png, demo.gif, dashboard.png, device.png
```

## Commands

```bash
python3 who_is_home.py                   # collector + dashboard on :8080 (uses ./dados)
python3 who_is_home.py setup | check | install | uninstall
python3 -m unittest discover -s tests
python3 tools/demo.py                    # http://localhost:8767, simulated data
node tools/capture.mjs                   # regenerate docs/<lang>/ images (demo must be running; LANGS=en to limit)
```

`WHOISHOME_DATA=/some/dir` moves the data folder (the demo and tests use it).

## Conventions

- Code comments are in **Brazilian Portuguese**.
- Keep `who_is_home.py` a single file, in section order: utilities → network → domains → AdGuard → notifier → collector → statistics → web server → commands.
- New config keys go in `DEFAULTS` with a short comment.
- READMEs are short and exist in three languages, each with its own images in `docs/<lang>/`. If the UI changes in a visible way, regenerate them with `node tools/capture.mjs`.
