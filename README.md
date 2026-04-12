# Rust Time Overlay

A lightweight always-on-top overlay for Rust that displays the current in-game server time, live player population, and online status of tracked players — pulled in real time through Rust's own official API. No game modifications, no memory reading, no third-party accounts.

**Anti-cheat safe.** The overlay is a regular desktop window. It communicates only through the Rust+ WebSocket API (the same one the official phone app uses) and the public BattleMetrics REST API. It never touches the game process, reads memory, hooks system calls, or interacts with Easy Anti-Cheat in any way. Facepunch built and officially supports the Rust+ API for exactly this kind of companion use.

## Download

**[⬇ Download latest release](../../releases/latest)**

Unzip and run `Rust Time Overlay.exe`. No installation required.

---

## Features

- **☀️ / 🌙 Server time** — exact in-game time with day/night icon, updated every 12 seconds directly from the Rust+ API
- **☠ Live population** — current player count for your server, shown alongside the time
- **● Player tracker** — monitor specific players by name or Steam ID; each shows a green (online) or red (offline) dot on the overlay, refreshed every 30 seconds via the BattleMetrics public API — no account or API key required
- Fully transparent, borderless overlay that stays on top while you play
- Drag to reposition anywhere on screen
- Scroll wheel to resize the font on the fly
- Configurable font size, transparency, and text color
- All settings saved automatically between sessions
- Reconnects to your last server automatically on every launch

---

## How It Works

**Server time and population** are fetched over a persistent WebSocket connection to your Rust server using the official [Rust+ API](https://github.com/liamcottle/rustplus.js) — the same protocol the Rust+ phone app uses. It requires a one-time pairing step inside the game, which produces an auth token stored locally on your machine only. The overlay polls time and population every 12 seconds — two small requests per cycle. No credentials ever leave your machine.

**Player tracking** uses the [BattleMetrics](https://www.battlemetrics.com) public REST API, which indexes Rust servers and their online player lists from public data. The overlay resolves your server's BattleMetrics ID from its IP address once, then fetches the full online player list in a single request every 30 seconds — regardless of how many players you're tracking. You can enter either an in-game display name (case-insensitive match) or a 17-digit Steam ID (resolved to a BattleMetrics player record once, then cached — no repeated lookups). No BattleMetrics account, API key, or login is required.

Both data sources run in background daemon threads, completely separate from the UI. CPU usage is negligible — the app sleeps between polls and does no continuous work. Memory footprint is under 50MB including the Python runtime.

---

## Requirements

- Windows 10 or 11
- [Node.js](https://nodejs.org) — only needed once during first-time setup for the pairing process
- The **Rust+** companion app installed on your phone and linked to your Steam account

---

## First-time Setup

1. **Download and run** `Rust Time Overlay.exe`
2. The setup screen opens automatically and walks you through three steps:

   **Step 1 — Install Node.js**
   Node.js is used to run the `rustplus.js` CLI that handles Steam authentication and server pairing. If it's not detected, click **Install Node.js → nodejs.org**, run the installer, then click **I've installed it — Check Again**.

   **Step 2 — Link your Steam account**
   Click **Link Steam Account**. A browser page opens — sign in to Steam and close it. This registers your Steam identity with the local `rustplus.js` toolchain. Only needs to be done once per machine.

   **Step 3 — Pair with your Rust server**
   Click **Start Listening for Pair**. The overlay listens for a pairing notification from Rust. In-game, go to **Menu → alarm clock icon → Pair**. The overlay receives your server IP, port, Steam ID, and auth token and connects automatically.

3. Done — the overlay appears and starts showing live data. On every future launch it reconnects automatically with no setup required.

> Node.js is only used during the pairing process. Once paired, the overlay runs fully standalone.

---

## Changing Servers

Open settings (double-click the overlay or right-click → Open Settings), then click **Change Server**. This skips straight to the pairing step. Click **Start Listening for Pair** and pair again from inside Rust. The old token is replaced and BattleMetrics re-resolves the new server automatically.

---

## Player Tracker

In the settings panel, under **Track players**:

1. Enter one player per line — either their exact in-game display name or their 17-digit Steam ID
2. Click **Save**

The overlay adds a row per player below the population count:

| Dot color | Meaning |
|-----------|---------|
| Green ● | Player is currently online on your server |
| Red ● | Player is offline (or not found on the server) |
| Grey ● | Resolving — waiting for first poll result |

**Name matching** is case-insensitive and exact. If you enter `MintyFresh`, it matches `mintyfresh`, `MINTYFRESH`, etc., against the live BattleMetrics player list for your server.

**Steam ID matching** does a one-time lookup via the BattleMetrics identifiers API to resolve the Steam ID to a display name. After that first resolution the name is cached and subsequent polls use it — no extra API calls per cycle.

The status line below the player list shows when data was last fetched (e.g. `✓ Updated 12s ago`) or `⟳ Querying BattleMetrics…` while a poll is in progress.

---

## Controls

| Action | Result |
|--------|--------|
| Drag overlay | Reposition it on screen |
| Scroll wheel on overlay | Resize the font |
| Double-click overlay | Open settings panel |
| Right-click overlay | Quick menu (reconnect / exit) |
| Escape in settings | Hide the settings panel |
| Hide button | Minimize to overlay only |

---

## Settings

All settings are in the settings panel (double-click the overlay to open):

| Setting | Description |
|---------|-------------|
| Font Size | Slider — adjusts overlay text size (12–60) |
| Transparency | Slider — adjusts overlay opacity (40%–100%) |
| Text Color | Color picker for all overlay text |
| Show population | Toggle the ☠ player count row on/off |
| Track players | Toggle all player tracker rows on/off |
| Player names or Steam IDs | One per line — accepts display names or 17-digit Steam IDs. Click **Save** to apply. |

---

## Privacy & Security

Your server credentials (IP, port, Steam ID, auth token) are stored locally in `rust_overlay_config.json` next to the exe. This file is never uploaded anywhere and is excluded from the repository via `.gitignore`.

The overlay makes outbound connections **only** to:

| Destination | Protocol | Purpose | Auth |
|-------------|----------|---------|------|
| Your Rust game server | WebSocket (Rust+ protocol) | Time and population | Local token only |
| `api.battlemetrics.com` | HTTPS | Player online status | None — public API |

No analytics, no telemetry, no crash reporting, no external accounts, no background updater. The source code is fully readable in `source/rust_time_overlay.pyw` — a single Python file with no obfuscation.

---

## Building from Source

**Install dependencies:**
```
pip install rustplus pyinstaller
```

**Build the exe:**

Double-click `build.bat` — it detects your Python, installs/upgrades dependencies, cleans previous build artifacts, and produces `dist\Rust Time Overlay.exe` automatically. A copy is also placed in `release\`.

Or manually:
```
pyinstaller "Rust Time Overlay.spec" --noconfirm
```

The `.spec` file excludes heavy unused packages (numpy, scipy, Pillow, etc.) to keep the exe under 15MB.

---

## Troubleshooting

**Overlay doesn't connect after launch**
Your server auth token may have expired. Click **Change Server** in settings and pair again from inside Rust.

**Player shows grey dot and never updates**
The Steam ID may not be indexed on BattleMetrics, or the player has never been seen on a BM-tracked server. Try entering their in-game display name instead.

**Player tracker shows "Server not found on BattleMetrics"**
Some private or recently-launched servers aren't indexed yet. BattleMetrics picks up servers organically as players join; there's nothing to configure on your end.

**"rustplus library not installed" warning**
Open a terminal and run:
```
"C:\Python3xx\python.exe" -m pip install rustplus
```
Use the exact Python path shown in the warning.

**Node.js not detected after installing**
Restart your PC so the PATH update takes effect, then click **I've installed it — Check Again**.
