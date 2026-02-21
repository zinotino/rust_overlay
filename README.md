# Rust Time Overlay

A lightweight always-on-top overlay for Rust that displays the current in-game server time (day/night) and live player population.

![overlay preview](icon.png)

## Features

- ☀️ / 🌙 Day/night indicator with exact server time
- ☠ Live server population count
- Fully transparent, borderless overlay — stays on top while you play
- Drag to reposition, scroll wheel to resize
- Configurable font size, transparency, and color
- Persists settings between sessions

## Requirements

- Windows 10/11
- [Node.js](https://nodejs.org) (for first-time server pairing only)
- The **Rust+** companion app on your phone

## First-time Setup

1. **Install Node.js** — download from [nodejs.org](https://nodejs.org) and run the installer
2. Open **Rust Time Overlay** — the setup screen will guide you through the rest:
   - Link your Steam account (opens a browser page once)
   - Pair with your server (press Pair from inside Rust)
3. The overlay connects automatically and starts tracking

Node.js is only needed during initial setup. Once paired, the overlay works standalone.

## Building from Source

**Dependencies:**

```
pip install rustplus pyinstaller
```

**Build:**

Double-click `build.bat` — produces `dist\Rust Time Overlay.exe`.

Or manually:

```
pyinstaller "Rust Time Overlay.spec" --noconfirm
```

## Config

Settings are saved automatically to `rust_overlay_config.json` in the same folder as the exe.
This file is excluded from git as it contains your personal server credentials.

## Controls

| Action | Result |
|--------|--------|
| Drag overlay | Reposition |
| Scroll wheel on overlay | Resize font |
| Double-click overlay | Open settings |
| Right-click overlay | Context menu |
| Escape in settings | Hide settings |
