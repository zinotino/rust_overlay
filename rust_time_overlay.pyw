import tkinter as tk
from tkinter import ttk, colorchooser, messagebox
import json, os, asyncio, threading, subprocess, pathlib, webbrowser, sys
import time as _time
import urllib.request as _urllib_req
import urllib.parse as _urllib_parse

__version__ = "3.8.0"

# ── Dependency check (non-blocking — warn after UI is up) ──────────────────────
try:
    from rustplus import RustSocket, ServerDetails
    RUSTPLUS_OK = True
except ImportError:
    RUSTPLUS_OK = False

# ── Base directory (works both as .py and frozen .exe) ────────────────────────
if getattr(sys, 'frozen', False):
    _base_dir = pathlib.Path(sys.executable).parent
else:
    _base_dir = pathlib.Path(__file__).parent

CONFIG_FILE = str(_base_dir / "rust_overlay_config.json")

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULTS = {
    "ip": "", "port": 28082, "steamid": 0, "token": 0,
    "x": 1680, "y": 60, "font_size": 28, "alpha": 0.92,
    "color": "#e8d5a3", "show_population": True,
    "tracked_players": [], "show_tracked": True,
    # Crosshair
    "crosshair_enabled": False,
    "crosshair_style": "cross",       # cross, dot, circle, cross_dot, chevron, t_shape
    "crosshair_color": "#00ff00",
    "crosshair_size": 20,             # line length (px)
    "crosshair_thickness": 2,         # line width (px)
    "crosshair_gap": 4,               # center gap for cross/t styles
    "crosshair_opacity": 1.0,         # window-level opacity
    "crosshair_rotation": 0,          # degrees rotation
    # Center dot
    "crosshair_dot_enabled": True,
    "crosshair_dot_size": 3,
    "crosshair_dot_color": "#00ff00",
    "crosshair_dot_opacity": 1.0,
    # Outline
    "crosshair_outline": False,
    "crosshair_outline_color": "#000000",
    "crosshair_outline_thickness": 2,
    "crosshair_outline_opacity": 1.0,
    # Position
    "crosshair_offset_x": 0,
    "crosshair_offset_y": 0,
    # T-shape (remove top arm)
    "crosshair_tshape": "never",      # never, always
    # Custom image
    "crosshair_image_path": "",
    "crosshair_image_scale": 1.0,
    # ADS hide (right-click hides crosshair)
    "crosshair_ads_hide": False,
    # Presets
    "crosshair_presets": {},           # {"name": {params...}}
    "crosshair_active_preset": "",
}
_KNOWN_KEYS = set(DEFAULTS.keys())

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError
            merged = {**DEFAULTS, **{k: v for k, v in raw.items() if k in _KNOWN_KEYS}}
            merged["font_size"] = max(12, min(60, int(merged["font_size"])))
            merged["alpha"]     = max(0.1, min(1.0, float(merged["alpha"])))
            merged["port"]      = max(1, min(65535, int(merged["port"])))
            raw_tracked = merged.get("tracked_players", [])
            if not isinstance(raw_tracked, list):
                raw_tracked = []
            merged["tracked_players"] = [str(x).strip() for x in raw_tracked if str(x).strip()]
            return merged
        except Exception:
            pass
    return dict(DEFAULTS)

def save_config(c):
    safe = {k: c[k] for k in _KNOWN_KEYS if k in c}
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(safe, f, indent=2)
    except Exception:
        pass

config = load_config()

def is_configured():
    try:
        return bool(
            str(config.get("ip", "")).strip() and
            int(config.get("steamid", 0)) != 0 and
            int(config.get("token", 0)) != 0
        )
    except (ValueError, TypeError):
        return False

# ── Connection state ──────────────────────────────────────────────────────────
state = {
    "time": "--:--", "is_day": True, "connected": False, "population": 0,
    "tracked_status": {},  # {steam_id_str: {"name": str, "online": bool|None}}
}

# Single background event loop — lives for the entire app session
_loop = asyncio.new_event_loop()
_conn_task = None   # current asyncio Task
_loop_thread = None

def _run_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()

def _ensure_loop_running():
    global _loop_thread
    if _loop_thread is None or not _loop_thread.is_alive():
        _loop_thread = threading.Thread(target=_run_loop, daemon=True, name="async-loop")
        _loop_thread.start()

async def _connection_task():
    """Runs inside _loop. Connects, polls, retries — stops when cancelled."""
    sock = None
    while True:
        if not is_configured() or not RUSTPLUS_OK:
            await asyncio.sleep(3)
            continue
        try:
            details = ServerDetails(
                config["ip"],
                int(config["port"]),
                int(config["steamid"]),
                int(config["token"])
            )
            sock = RustSocket(details)
            await sock.connect()
            state["connected"] = True

            while True:
                try:
                    t_obj = await sock.get_time()
                    t_str = getattr(t_obj, 'time', None)
                    if t_str and ':' in str(t_str):
                        state["time"] = str(t_str)[:5]
                        try:
                            hour = int(state["time"].split(':')[0])
                            state["is_day"] = 6 <= hour <= 19
                        except ValueError:
                            pass

                    if config.get("show_population"):
                        try:
                            info = await sock.get_info()
                            pop = (getattr(info, "players", None)
                                   or getattr(info, "current_players", None)
                                   or getattr(info, "playerCount", 0) or 0)
                            state["population"] = max(0, int(pop))
                        except Exception:
                            state["population"] = 0

                except asyncio.CancelledError:
                    raise
                except Exception:
                    break

                await asyncio.sleep(12)

        except asyncio.CancelledError:
            raise
        except Exception:
            state["connected"] = False

        finally:
            state["connected"] = False
            if sock:
                try:
                    await sock.disconnect()
                except Exception:
                    pass
                sock = None

        # Wait before retrying — but bail if cancelled
        try:
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            raise

def start_connection():
    global _conn_task
    _ensure_loop_running()
    # Cancel any existing task first
    if _conn_task and not _conn_task.done():
        _loop.call_soon_threadsafe(_conn_task.cancel)
    def _start():
        global _conn_task
        _conn_task = _loop.create_task(_connection_task())
    _loop.call_soon_threadsafe(_start)

def restart_connection():
    """Stop current connection and reconnect after a short delay."""
    global _conn_task
    if _conn_task and not _conn_task.done():
        _loop.call_soon_threadsafe(_conn_task.cancel)
    # Restart after delay using the existing loop
    async def _delayed_restart():
        await asyncio.sleep(1.5)
        global _conn_task
        _conn_task = _loop.create_task(_connection_task())
    _loop.call_soon_threadsafe(lambda: _loop.create_task(_delayed_restart()))

def stop_connection():
    global _conn_task
    if _conn_task and not _conn_task.done():
        _loop.call_soon_threadsafe(_conn_task.cancel)

# ── BattleMetrics player tracker ──────────────────────────────────────────────

_bm_server_id   = None  # resolved once per server IP
_bm_player_ids  = {}    # {entry: display_name}
_bm_thread      = None
_bm_status      = {"text": "Not started", "last_ok": None}  # updated by poll thread

def _bm_get(path):
    url = "https://api.battlemetrics.com" + path
    req = _urllib_req.Request(url, headers={"User-Agent": "RustTimeOverlay/3.8"})
    try:
        with _urllib_req.urlopen(req, timeout=8) as r:
            return json.load(r)
    except Exception:
        return None

def _bm_resolve_server(ip):
    data = _bm_get(f"/servers?filter[game]=rust&filter[search]={ip}&page[size]=5")
    if not data:
        return None
    for s in data.get("data", []):
        if s.get("attributes", {}).get("ip") == ip:
            return s["id"]
    return None

def _bm_fetch_online_players(bm_server_id):
    """Return dict of {bm_player_id: display_name} for all currently online players."""
    data = _bm_get(f"/servers/{bm_server_id}?include=player")
    if not data:
        return {}
    return {
        item["id"]: item["attributes"].get("name", "")
        for item in data.get("included", [])
        if item.get("type") == "player"
    }

def _bm_resolve_steam_id(steam_id, online_names):
    """Resolve a Steam ID to a display name via BM identifiers lookup,
    then check if that BM player ID is in the online set."""
    data = _bm_get(f"/players?filter[identifiers]={_urllib_parse.quote(steam_id)}&page[size]=5")
    if not data:
        return None, False
    players = data.get("data", [])
    if not players:
        return None, False
    bm_ids = {p["id"] for p in players}
    name = players[0]["attributes"].get("name", steam_id)
    is_on = bool(bm_ids & set(online_names.keys()))
    # Use the actual online name if available (most accurate)
    for bid in bm_ids:
        if bid in online_names:
            name = online_names[bid]
            break
    return name, is_on

def _bm_poll_loop():
    global _bm_server_id, _bm_player_ids
    _time.sleep(3)  # let UI finish initial render before first HTTP request
    while True:
        try:
            tracked = list(config.get("tracked_players", []))
            if tracked and config.get("ip") and config.get("show_tracked"):
                ip = config.get("ip", "")
                _bm_status["text"] = "Querying…"
                if not _bm_server_id and ip:
                    _bm_server_id = _bm_resolve_server(ip)
                if _bm_server_id:
                    # Fetch all currently online players (names + IDs) in one request
                    online = _bm_fetch_online_players(_bm_server_id)
                    # Build lowercase name lookup for fast matching
                    online_lower = {name.lower(): (bid, name) for bid, name in online.items()}

                    new_status = {}
                    for entry in tracked:
                        is_steam_id = entry.isdigit() and len(entry) == 17
                        if is_steam_id:
                            # Cache Steam ID → BM resolution (only needs to happen once)
                            if entry not in _bm_player_ids:
                                name, is_on = _bm_resolve_steam_id(entry, online)
                                _bm_player_ids[entry] = name or entry
                                _time.sleep(0.3)
                            else:
                                name = _bm_player_ids[entry]
                                bm_id_match = next(
                                    (bid for bid, n in online.items() if n == name), None
                                )
                                is_on = bm_id_match is not None
                            new_status[entry] = {"name": _bm_player_ids.get(entry, entry), "online": is_on}
                        else:
                            # Name lookup: find exact match (case-insensitive) in online list
                            match = online_lower.get(entry.lower())
                            if match:
                                _, display = match
                                new_status[entry] = {"name": display, "online": True}
                            else:
                                # Not online — use cached display name or entry itself
                                display = _bm_player_ids.get(entry, entry)
                                new_status[entry] = {"name": display, "online": False}
                            # Cache the display name for when they go offline
                            if entry not in _bm_player_ids and match:
                                _bm_player_ids[entry] = match[1]
                    state["tracked_status"] = new_status
                    _bm_status["last_ok"] = _time.monotonic()
                    _bm_status["text"] = "idle"
                else:
                    _bm_status["text"] = "Server not found on BattleMetrics"
            elif not config.get("ip"):
                _bm_status["text"] = "No server IP configured"
            else:
                _bm_status["text"] = "idle"
        except Exception:
            _bm_status["text"] = "Error during query"
        _time.sleep(30)

def _ensure_bm_running():
    global _bm_thread
    if _bm_thread is None or not _bm_thread.is_alive():
        _bm_thread = threading.Thread(target=_bm_poll_loop, daemon=True, name="bm-poll")
        _bm_thread.start()

def _reset_bm():
    global _bm_server_id, _bm_player_ids
    _bm_server_id = None
    _bm_player_ids = {}
    state["tracked_status"] = {}

# ── Crosshair overlay ─────────────────────────────────────────────────────────

import math

_CH_WIN_SIZE = 300  # canvas size — large enough for max crosshair + rotation

# Keys that define a crosshair design (used for preset save/load)
_CH_DESIGN_KEYS = [
    "crosshair_style", "crosshair_color", "crosshair_size", "crosshair_thickness",
    "crosshair_gap", "crosshair_opacity", "crosshair_rotation",
    "crosshair_dot_enabled", "crosshair_dot_size", "crosshair_dot_color",
    "crosshair_dot_opacity", "crosshair_outline", "crosshair_outline_color",
    "crosshair_outline_thickness", "crosshair_outline_opacity",
    "crosshair_offset_x", "crosshair_offset_y",
    "crosshair_tshape", "crosshair_image_path", "crosshair_image_scale",
    "crosshair_ads_hide",
]

def _rotate_point(x, y, cx, cy, deg):
    """Rotate (x,y) around (cx,cy) by deg degrees."""
    rad = math.radians(deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = x - cx, y - cy
    return cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a

def _ch_draw(canvas, cfg, cx, cy):
    """Core crosshair drawing — used by both overlay and preview."""
    c = canvas
    c.delete("all")

    style     = cfg.get("crosshair_style", "cross")
    color     = cfg.get("crosshair_color", "#00ff00")
    size      = max(2, int(cfg.get("crosshair_size", 20)))
    thick     = max(1, int(cfg.get("crosshair_thickness", 2)))
    gap       = max(0, int(cfg.get("crosshair_gap", 4)))
    rot       = float(cfg.get("crosshair_rotation", 0))
    dot_on    = cfg.get("crosshair_dot_enabled", True)
    dot_r     = max(1, int(cfg.get("crosshair_dot_size", 3)))
    dot_color = cfg.get("crosshair_dot_color", color)
    outline   = cfg.get("crosshair_outline", False)
    out_color = cfg.get("crosshair_outline_color", "#000000")
    out_thick = max(1, int(cfg.get("crosshair_outline_thickness", 2)))
    out_w     = thick + out_thick * 2 if outline else 0
    tshape    = cfg.get("crosshair_tshape", "never")

    def _rp(x, y):
        if rot == 0:
            return x, y
        return _rotate_point(x, y, cx, cy, rot)

    def _line(x1, y1, x2, y2, col, w):
        rx1, ry1 = _rp(x1, y1)
        rx2, ry2 = _rp(x2, y2)
        c.create_line(rx1, ry1, rx2, ry2, fill=col, width=w, capstyle="round")

    def _draw_arms(col, w, skip_top=False):
        """Draw cross arms. skip_top=True for T-shape."""
        if not skip_top:
            _line(cx, cy - gap - 1, cx, cy - gap - size, col, w)  # top
        _line(cx, cy + gap + 1, cx, cy + gap + size, col, w)      # bottom
        _line(cx - gap - 1, cy, cx - gap - size, cy, col, w)      # left
        _line(cx + gap + 1, cy, cx + gap + size, cy, col, w)      # right

    def _draw_dot(col, r):
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="", width=0)

    def _draw_circle(col, w):
        c.create_oval(cx - size, cy - size, cx + size, cy + size,
                      outline=col, width=w, fill="")

    def _draw_chevron(col, w):
        half = size
        _line(cx - half, cy - half // 2, cx, cy, col, w)
        _line(cx + half, cy - half // 2, cx, cy, col, w)

    is_cross = style in ("cross", "cross_dot", "t_shape")
    skip_top = (tshape == "always") or (style == "t_shape")

    # ── Outline pass (drawn first, wider) ──
    if outline:
        if is_cross:
            _draw_arms(out_color, out_w, skip_top=skip_top)
        if style == "circle":
            _draw_circle(out_color, out_w)
        if style == "chevron":
            _draw_chevron(out_color, out_w)
        if dot_on and style in ("dot", "cross_dot"):
            _draw_dot(out_color, dot_r + out_thick)
        elif dot_on and is_cross:
            _draw_dot(out_color, dot_r + out_thick)

    # ── Main pass ──
    if is_cross:
        _draw_arms(color, thick, skip_top=skip_top)
    if style == "circle":
        _draw_circle(color, thick)
    if style == "chevron":
        _draw_chevron(color, thick)

    # Dot
    if dot_on:
        if outline:
            _draw_dot(out_color, dot_r + out_thick)
        _draw_dot(dot_color, dot_r)


class CrosshairOverlay:
    """Transparent always-on-top crosshair drawn at screen centre via Canvas."""

    def __init__(self, root):
        self.root = root
        self._win = None
        self._canvas = None
        self._visible = False
        self._ads_hidden = False      # temporarily hidden by ADS
        self._custom_img = None       # PhotoImage reference keeper
        self._build()
        if config.get("crosshair_enabled"):
            self.show()
        self._monitor_position()

    def _build(self):
        self._win = tk.Toplevel(self.root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-transparentcolor", "black")
        self._win.configure(bg="black")
        self._win.attributes("-alpha", config.get("crosshair_opacity", 1.0))
        self._canvas = tk.Canvas(
            self._win, width=_CH_WIN_SIZE, height=_CH_WIN_SIZE,
            bg="black", highlightthickness=0,
        )
        self._canvas.pack()
        self._win.wm_attributes("-disabled", True)  # click-through
        self._centre()
        self.redraw()
        self._win.withdraw()

    def _centre(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        ox = int(config.get("crosshair_offset_x", 0))
        oy = int(config.get("crosshair_offset_y", 0))
        x = sw // 2 - _CH_WIN_SIZE // 2 + ox
        y = sh // 2 - _CH_WIN_SIZE // 2 + oy
        self._win.geometry(f"{_CH_WIN_SIZE}x{_CH_WIN_SIZE}+{x}+{y}")

    def _monitor_position(self):
        if self._visible:
            self._centre()
        try:
            self.root.after(2000, self._monitor_position)
        except tk.TclError:
            pass

    # ── visibility ────────────────────────────────────────────────────────────
    def show(self):
        self._visible = True
        self._ads_hidden = False
        self._centre()
        self.redraw()
        self._win.deiconify()
        self._win.lift()

    def hide(self):
        self._visible = False
        self._win.withdraw()

    def toggle(self):
        if self._visible:
            self.hide()
        else:
            self.show()
        config["crosshair_enabled"] = self._visible
        save_config(config)

    @property
    def visible(self):
        return self._visible

    # ── ADS hide (right-click) ────────────────────────────────────────────────
    def ads_press(self):
        """Called on right-mouse-down when ads_hide is enabled."""
        if self._visible and config.get("crosshair_ads_hide"):
            self._ads_hidden = True
            self._win.withdraw()

    def ads_release(self):
        """Called on right-mouse-up."""
        if self._ads_hidden and self._visible:
            self._ads_hidden = False
            self._win.deiconify()
            self._win.lift()

    # ── drawing ───────────────────────────────────────────────────────────────
    def redraw(self):
        cx = _CH_WIN_SIZE // 2
        cy = _CH_WIN_SIZE // 2

        # Custom image mode
        img_path = config.get("crosshair_image_path", "")
        if img_path and os.path.isfile(img_path):
            self._draw_image(img_path, cx, cy)
        else:
            _ch_draw(self._canvas, config, cx, cy)

        try:
            self._win.attributes("-alpha", config.get("crosshair_opacity", 1.0))
        except tk.TclError:
            pass

    def _draw_image(self, path, cx, cy):
        """Overlay a custom PNG/GIF image as the crosshair."""
        c = self._canvas
        c.delete("all")
        try:
            scale = max(0.1, float(config.get("crosshair_image_scale", 1.0)))
            img = tk.PhotoImage(file=path)
            # Subsample/zoom for scaling (integer only in Tkinter)
            if scale >= 1.0:
                zoom = max(1, int(scale))
                img = img.zoom(zoom, zoom)
            else:
                sub = max(1, int(1.0 / scale))
                img = img.subsample(sub, sub)
            self._custom_img = img  # prevent GC
            c.create_image(cx, cy, image=img, anchor="center")
        except Exception:
            # Fallback to regular crosshair if image fails
            _ch_draw(c, config, cx, cy)

# ── Preset manager ────────────────────────────────────────────────────────────

def _get_design():
    """Extract current crosshair design params from config."""
    return {k: config[k] for k in _CH_DESIGN_KEYS if k in config}

def _apply_design(design):
    """Apply a design dict to config (does not save — caller saves)."""
    for k, v in design.items():
        if k in _CH_DESIGN_KEYS:
            config[k] = v

def preset_save(name):
    presets = config.get("crosshair_presets", {})
    presets[name] = _get_design()
    config["crosshair_presets"] = presets
    config["crosshair_active_preset"] = name
    save_config(config)

def preset_load(name):
    presets = config.get("crosshair_presets", {})
    if name not in presets:
        return False
    _apply_design(presets[name])
    config["crosshair_active_preset"] = name
    save_config(config)
    return True

def preset_delete(name):
    presets = config.get("crosshair_presets", {})
    presets.pop(name, None)
    config["crosshair_presets"] = presets
    if config.get("crosshair_active_preset") == name:
        config["crosshair_active_preset"] = ""
    save_config(config)

def preset_list():
    return sorted(config.get("crosshair_presets", {}).keys())

def preset_export_png(canvas, path):
    """Export the preview canvas to a .png via PostScript → PIL conversion."""
    try:
        from PIL import Image
        ps_path = path + ".ps"
        canvas.postscript(file=ps_path, colormode="color")
        img = Image.open(ps_path)
        img.save(path)
        os.remove(ps_path)
        return True
    except Exception:
        return False

# ── ADS hide (right-click mouse hook) ────────────────────────────────────────
# Uses a low-level Windows mouse hook to detect right-click even when the game
# has focus (since the overlay window is click-through / disabled).

_ads_hook_installed = False

def _install_ads_hook(ch_overlay):
    """Install a Windows low-level mouse hook for ADS hide."""
    global _ads_hook_installed
    if _ads_hook_installed:
        return
    try:
        import ctypes
        import ctypes.wintypes as wt

        user32 = ctypes.windll.user32
        WH_MOUSE_LL = 14
        WM_RBUTTONDOWN = 0x0204
        WM_RBUTTONUP   = 0x0205

        @ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wt.WPARAM, wt.LPARAM)
        def _mouse_proc(nCode, wParam, lParam):
            if nCode >= 0:
                if wParam == WM_RBUTTONDOWN:
                    try:
                        ch_overlay.root.after(0, ch_overlay.ads_press)
                    except Exception:
                        pass
                elif wParam == WM_RBUTTONUP:
                    try:
                        ch_overlay.root.after(0, ch_overlay.ads_release)
                    except Exception:
                        pass
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        hook = user32.SetWindowsHookExW(WH_MOUSE_LL, _mouse_proc, None, 0)
        if hook:
            _ads_hook_installed = True
            # The hook proc reference must stay alive
            ch_overlay._ads_hook_proc = _mouse_proc
            ch_overlay._ads_hook_handle = hook

            def _pump():
                """Pump Windows messages so the hook fires in our thread."""
                msg = wt.MSG()
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                try:
                    ch_overlay.root.after(16, _pump)
                except tk.TclError:
                    pass
            _pump()
    except Exception:
        pass  # non-Windows or ctypes not available — silently skip

# ── Overlay window ─────────────────────────────────────────────────────────────
overlay = tk.Tk()
overlay.overrideredirect(True)
overlay.attributes("-topmost", True)
overlay.attributes("-alpha", config["alpha"])
overlay.configure(bg="black")
overlay.attributes('-transparentcolor', 'black')
overlay.geometry(f"+{config['x']}+{config['y']}")

ovl_frame = tk.Frame(overlay, bg="black")
ovl_frame.pack(padx=20, pady=10)

icon_lbl = tk.Label(ovl_frame, text="☀️",
                    font=("Segoe UI Emoji", int(config["font_size"] * 0.9)),
                    bg="black", fg=config["color"])
icon_lbl.grid(row=0, column=0, sticky="w", padx=(0, 8))

time_lbl = tk.Label(ovl_frame, text="--:--",
                    font=("Segoe UI", config["font_size"], "bold"),
                    bg="black", fg=config["color"])
time_lbl.grid(row=0, column=1, sticky="w")

skull_lbl = tk.Label(ovl_frame, text="☠",
                     font=("Segoe UI Emoji", int(config["font_size"] * 0.9)),
                     bg="black", fg=config["color"])
pop_lbl = tk.Label(ovl_frame, text="",
                   font=("Segoe UI", config["font_size"]),
                   bg="black", fg=config["color"])

if config.get("show_population"):
    skull_lbl.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(2, 0))
    pop_lbl.grid(row=1, column=1, sticky="w", pady=(2, 0))

# ── Crosshair instance ────────────────────────────────────────────────────────
crosshair = CrosshairOverlay(overlay)
if config.get("crosshair_ads_hide"):
    _install_ads_hook(crosshair)

_tracked_labels = []  # list of (dot_lbl, name_lbl)

def _rebuild_tracked_labels():
    global _tracked_labels
    for dot, name in _tracked_labels:
        dot.destroy()
        name.destroy()
    _tracked_labels = []
    tracked = config.get("tracked_players", [])
    fs = config["font_size"]
    for i, sid in enumerate(tracked):
        dot = tk.Label(ovl_frame, text="●", font=("Segoe UI", int(fs * 0.6)),
                       bg="black", fg="#888888")
        dot.grid(row=i + 2, column=0, sticky="w", padx=(0, 8), pady=(2, 0))
        name = tk.Label(ovl_frame, text=sid[:8] + "…", font=("Segoe UI", int(fs * 0.75)),
                        bg="black", fg=config["color"])
        name.grid(row=i + 2, column=1, sticky="w", pady=(2, 0))
        for _w in (dot, name):
            _w.bind("<Button-1>", drag_start)
            _w.bind("<B1-Motion>", drag)
            _w.bind("<MouseWheel>", resize)
            _w.bind("<Double-Button-1>", lambda e: control_panel.deiconify())
            _w.bind("<Button-3>", lambda e: show_menu(e))
        _tracked_labels.append((dot, name))

def update_overlay():
    try:
        icon_lbl.config(text="☀️" if state["is_day"] else "🌙", fg=config["color"])
        time_lbl.config(text=state["time"], fg=config["color"])
        if config.get("show_population"):
            skull_lbl.config(fg=config["color"])
            pop_lbl.config(
                text=str(state["population"]) if state["population"] else "",
                fg=config["color"]
            )
            skull_lbl.grid()
            pop_lbl.grid()
        else:
            skull_lbl.grid_remove()
            pop_lbl.grid_remove()

        if config.get("show_tracked") and config.get("tracked_players"):
            tracked = config["tracked_players"]
            if len(tracked) != len(_tracked_labels):
                _rebuild_tracked_labels()
            for i, sid in enumerate(tracked):
                if i >= len(_tracked_labels):
                    break
                dot, name = _tracked_labels[i]
                status = state["tracked_status"].get(sid, {})
                is_on = status.get("online")
                dot.config(fg="#4CAF50" if is_on else ("#cc4444" if is_on is False else "#888888"))
                name.config(text=status.get("name", sid[:8] + "…"), fg=config["color"])
                dot.grid()
                name.grid()
        else:
            for dot, name in _tracked_labels:
                dot.grid_remove()
                name.grid_remove()
    except tk.TclError:
        return
    overlay.after(600, update_overlay)

update_overlay()

def drag_start(e):
    overlay._drag_x = e.x
    overlay._drag_y = e.y

def drag(e):
    config["x"] = overlay.winfo_x() - overlay._drag_x + e.x
    config["y"] = overlay.winfo_y() - overlay._drag_y + e.y
    overlay.geometry(f"+{config['x']}+{config['y']}")
    save_config(config)

def resize(e):
    config["font_size"] = max(12, min(60, config["font_size"] + (1 if e.delta > 0 else -1)))
    _apply_font()
    save_config(config)

def _apply_font():
    fs = config["font_size"]
    time_lbl.config(font=("Segoe UI", fs, "bold"))
    icon_lbl.config(font=("Segoe UI Emoji", int(fs * 0.9)))
    skull_lbl.config(font=("Segoe UI Emoji", int(fs * 0.9)))
    pop_lbl.config(font=("Segoe UI", fs))
    for dot, name in _tracked_labels:
        dot.config(font=("Segoe UI", int(fs * 0.6)))
        name.config(font=("Segoe UI", int(fs * 0.75)))

for _w in (ovl_frame, icon_lbl, time_lbl, skull_lbl, pop_lbl):
    _w.bind("<Button-1>", drag_start)
    _w.bind("<B1-Motion>", drag)
    _w.bind("<MouseWheel>", resize)
    _w.bind("<Double-Button-1>", lambda e: control_panel.deiconify())
    _w.bind("<Button-3>", lambda e: show_menu(e))

def show_menu(e):
    m = tk.Menu(overlay, tearoff=0, bg="#1c1810", fg="#e8d5a3")
    m.add_command(label="  ⚙  Open Settings", command=lambda: control_panel.deiconify())
    m.add_command(label="  ⟳  Reconnect",     command=restart_connection)
    ch_label = "  ✛  Crosshair OFF" if crosshair.visible else "  ✛  Crosshair ON"
    m.add_command(label=ch_label, command=crosshair.toggle)
    m.add_separator()
    m.add_command(label="  ✕  Exit",           command=do_quit)
    m.tk_popup(e.x_root, e.y_root)

# ── Control panel ──────────────────────────────────────────────────────────────
control_panel = tk.Toplevel(overlay)
control_panel.title("Rust Time Overlay")
control_panel.configure(bg="#1c1810")
control_panel.resizable(False, False)

_icon_path = _base_dir / "icon.ico"
if _icon_path.exists():
    try:
        control_panel.iconbitmap(str(_icon_path))
        overlay.iconbitmap(str(_icon_path))
    except Exception:
        pass

style = ttk.Style()
style.theme_use('clam')
style.configure('.', background="#1c1810", foreground="#e8d5a3")

# Header
hdr = tk.Frame(control_panel, bg="#2a2418")
hdr.pack(fill="x")
tk.Label(hdr, text="☢", bg="#2a2418", fg="#e8c070",
         font=("Segoe UI Emoji", 32)).pack(side="left", padx=24, pady=10)
tk.Label(hdr, text="Rust Time Overlay", bg="#2a2418", fg="#e8d5a3",
         font=("Segoe UI", 18, "bold")).pack(side="left", pady=10)
tk.Label(hdr, text=f"v{__version__}", bg="#2a2418", fg="#887050",
         font=("Segoe UI", 9)).pack(side="right", padx=24, pady=10)

# Footer — packed before body so side="bottom" reserves space correctly
foot = tk.Frame(control_panel, bg="#1c1810")
foot.pack(side="bottom", fill="x", padx=24, pady=(8, 16))

tk.Button(foot, text="Hide  (double-click overlay to reopen)", bg="#3f2f1f", fg="#e8d5a3",
          font=("Segoe UI", 10), relief="flat",
          command=control_panel.withdraw).pack(fill="x", ipady=10, pady=(0, 6))
tk.Button(foot, text="Quit", bg="#cc4444", fg="#ffffff",
          font=("Segoe UI", 10), relief="flat",
          command=lambda: do_quit()).pack(fill="x", ipady=10)

# Body — scrollable container for long settings panel
body = tk.Frame(control_panel, bg="#1c1810")
body.pack(fill="both", expand=True, padx=0, pady=(0, 0))

setup_frame = tk.Frame(body, bg="#1c1810")

# Scrollable settings frame
_scroll_canvas = tk.Canvas(body, bg="#1c1810", highlightthickness=0, bd=0)
_scroll_vsb = tk.Scrollbar(body, orient="vertical", command=_scroll_canvas.yview)
settings_frame = tk.Frame(_scroll_canvas, bg="#1c1810")

settings_frame.bind("<Configure>",
    lambda e: _scroll_canvas.configure(scrollregion=_scroll_canvas.bbox("all")))
_scroll_canvas.create_window((0, 0), window=settings_frame, anchor="nw", width=476)
_scroll_canvas.configure(yscrollcommand=_scroll_vsb.set)

def _on_mousewheel_settings(event):
    _scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

# Only bind scroll to the control panel window, not globally (overlay uses scroll for font resize)
def _bind_scroll_on_enter(event):
    _scroll_canvas.bind_all("<MouseWheel>", _on_mousewheel_settings)

def _unbind_scroll_on_leave(event):
    _scroll_canvas.unbind_all("<MouseWheel>")

_scroll_canvas.bind("<Enter>", _bind_scroll_on_enter)
_scroll_canvas.bind("<Leave>", _unbind_scroll_on_leave)

# Padding inside settings_frame content
_settings_pad = tk.Frame(settings_frame, bg="#1c1810")
_settings_pad.pack(fill="both", expand=True, padx=24, pady=(16, 0))

# Re-point settings_frame to the padded inner frame for all subsequent widgets
settings_frame = _settings_pad

def _fit_window():
    """Resize control panel to a comfortable scrollable height."""
    control_panel.update_idletasks()
    screen_h = control_panel.winfo_screenheight()
    max_h = min(screen_h - 80, 900)
    control_panel.geometry(f"520x{max_h}")
    _scroll_canvas.configure(width=500)

def show_setup(skip_to_pair=False):
    _scroll_canvas.pack_forget()
    _scroll_vsb.pack_forget()
    setup_frame.pack(fill="both", expand=True, padx=24, pady=(16, 0))
    _check_and_rebuild(skip_to_pair=skip_to_pair)

def show_settings():
    setup_frame.pack_forget()
    _scroll_vsb.pack(side="right", fill="y")
    _scroll_canvas.pack(side="left", fill="both", expand=True)
    control_panel.after(10, _fit_window)

# ── Setup frame ────────────────────────────────────────────────────────────────
tk.Label(setup_frame, text="Get Started",
         font=("Segoe UI", 13, "bold"), bg="#1c1810", fg="#e8d5a3").pack(anchor="w", pady=(0, 12))

steps_frame = tk.Frame(setup_frame, bg="#2a2418")
steps_frame.pack(fill="x", pady=(0, 12))

setup_status = tk.Label(setup_frame, text="", font=("Segoe UI", 10),
                         bg="#1c1810", fg="#e8d5a3", wraplength=440, justify="left")
setup_status.pack(anchor="w", pady=(0, 6))

action_frame = tk.Frame(setup_frame, bg="#1c1810")
action_frame.pack(fill="x")

def set_status(msg, color="#e8d5a3"):
    try:
        setup_status.config(text=msg, fg=color)
    except tk.TclError:
        pass

def node_available():
    try:
        subprocess.check_output(["node", "--version"],
                                stderr=subprocess.DEVNULL, timeout=5)
        return True
    except Exception:
        return False

def steam_linked():
    return (pathlib.Path.home() / "Documents" / "rustplus" / "rustplus.config.json").exists()

def rebuild_setup(skip_to_pair=False, node_ok=None, steam_ok=None):
    for w in steps_frame.winfo_children():
        w.destroy()
    for w in action_frame.winfo_children():
        w.destroy()

    node_checking = (node_ok is None) and not skip_to_pair
    if node_ok is None:
        node_ok = False
    else:
        node_ok = node_ok or skip_to_pair
    if steam_ok is None:
        steam_ok = steam_linked() or skip_to_pair
    else:
        steam_ok = steam_ok or skip_to_pair

    for ok, label in [
        (node_ok,  "Node.js installed" + (" (checking…)" if node_checking else "")),
        (steam_ok, "Steam account linked"),
        (False,    "Pair with your Rust server"),
    ]:
        row = tk.Frame(steps_frame, bg="#2a2418")
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text="✓" if ok else "○", bg="#2a2418",
                 fg="#5cb85c" if ok else "#555", font=("Segoe UI", 12)).pack(side="left", padx=(0, 10))
        tk.Label(row, text=label, bg="#2a2418",
                 fg="#e8d5a3" if ok else "#887050", font=("Segoe UI", 11)).pack(side="left")

    if node_checking:
        set_status("Checking for Node.js…", "#887050")
    elif not node_ok:
        set_status("Node.js is required for the automated pairing process.", "#ffaa00")
        tk.Button(action_frame, text="Install Node.js  →  nodejs.org",
                  bg="#3f2f1f", fg="#e8d5a3", font=("Segoe UI", 11, "bold"), relief="flat",
                  command=lambda: webbrowser.open("https://nodejs.org")
                  ).pack(fill="x", ipady=12, pady=(0, 6))
        tk.Button(action_frame, text="I've installed it — Check Again",
                  bg="#3f2f1f", fg="#e8d5a3", font=("Segoe UI", 10), relief="flat",
                  command=_check_and_rebuild).pack(fill="x", ipady=8)
    elif not steam_ok:
        set_status("Link your Steam account once. This opens a browser page — sign in and close it.", "#e8d5a3")
        tk.Button(action_frame, text="Link Steam Account",
                  bg="#3f2f1f", fg="#e8d5a3", font=("Segoe UI", 11, "bold"), relief="flat",
                  command=do_link_steam).pack(fill="x", ipady=12)
    else:
        set_status("Launch Rust, open the in-game menu, tap the alarm clock icon, then press Pair.", "#e8d5a3")
        tk.Button(action_frame, text="Start Listening for Pair",
                  bg="#5a8a3a", fg="#ffffff", font=("Segoe UI", 11, "bold"), relief="flat",
                  command=do_pair_server).pack(fill="x", ipady=12)
        if is_configured():
            tk.Button(action_frame, text="← Back to Settings",
                      bg="#2a2418", fg="#e8d5a3", font=("Segoe UI", 9), relief="flat",
                      command=show_settings).pack(fill="x", ipady=6, pady=(6, 0))

    control_panel.after(10, _fit_window)

def _check_and_rebuild(skip_to_pair=False):
    """Runs node_available() off the main thread to prevent blocking Tkinter."""
    if skip_to_pair:
        rebuild_setup(skip_to_pair=True)
        return
    # Show "checking" state immediately (non-blocking)
    rebuild_setup(skip_to_pair=False, node_ok=None, steam_ok=None)

    def _worker():
        n_ok = node_available()
        s_ok = steam_linked()
        control_panel.after(0, lambda: rebuild_setup(
            skip_to_pair=False, node_ok=n_ok, steam_ok=s_ok
        ))

    threading.Thread(target=_worker, daemon=True, name="node-check").start()

def do_link_steam():
    set_status("Opening browser — sign in to Steam, then come back here.", "#ffaa00")
    def run():
        try:
            subprocess.call(["npx", "@liamcottle/rustplus.js", "fcm-register"], timeout=120)
        except Exception:
            pass
        control_panel.after(0, _check_and_rebuild)
        control_panel.after(0, lambda: set_status("Steam linked! Now click 'Start Listening for Pair'.", "#5cb85c"))
    threading.Thread(target=run, daemon=True).start()

def do_pair_server():
    set_status("Listening… In Rust: Menu → alarm clock icon → Pair. Waiting…", "#ffaa00")
    threading.Thread(target=start_listen, daemon=True).start()

def start_listen():
    try:
        proc = subprocess.Popen(
            ["npx", "@liamcottle/rustplus.js", "fcm-listen"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
    except Exception as ex:
        overlay.after(0, lambda e=ex: set_status(f"Failed to start listener: {e}", "#cc4444"))
        return

    paired = False
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line or "playerToken" not in line:
                continue
            try:
                s = line.find('{')
                if s == -1:
                    continue
                body = json.loads(line[s:])
                ip      = str(body.get("ip") or body.get("server", {}).get("ip", "")).strip()
                port    = int(body.get("port") or body.get("server", {}).get("port", 28082))
                steamid = int(body.get("playerId") or body.get("playerSteamId", 0))
                token   = int(body.get("playerToken", 0))

                if not ip or token == 0 or steamid == 0 or not (1 <= port <= 65535):
                    continue

                if ip != config.get("ip"):
                    _reset_bm()
                config["ip"]      = ip
                config["port"]    = port
                config["steamid"] = steamid
                config["token"]   = token
                save_config(config)
                paired = True
                start_connection()
                overlay.after(0, show_settings)
                overlay.after(0, lambda: set_status("Paired! Connecting to server…", "#5cb85c"))
                break
            except Exception as ex:
                overlay.after(0, lambda e=ex: set_status(f"Parse error: {e}", "#cc4444"))
    finally:
        try:
            proc.kill()
        except Exception:
            pass

    if not paired:
        overlay.after(0, lambda: set_status("No pairing token received. Try again.", "#ffaa00"))

_check_and_rebuild()

# ── Settings frame ─────────────────────────────────────────────────────────────
conn_strip = tk.Frame(settings_frame, bg="#2a2418")
conn_strip.pack(fill="x", pady=(0, 16))

conn_dot = tk.Label(conn_strip, text="●", bg="#2a2418", fg="#ffaa00", font=("Segoe UI", 12))
conn_dot.pack(side="left", padx=(12, 6), pady=8)
conn_lbl = tk.Label(conn_strip, text="Connecting…", bg="#2a2418", fg="#e8d5a3", font=("Segoe UI", 10))
conn_lbl.pack(side="left", pady=8)
tk.Button(conn_strip, text="Reconnect", bg="#3f2f1f", fg="#e8d5a3",
          font=("Segoe UI", 9), relief="flat", padx=8,
          command=restart_connection).pack(side="right", padx=12, pady=6)
tk.Button(conn_strip, text="Change Server", bg="#3f2f1f", fg="#e8d5a3",
          font=("Segoe UI", 9), relief="flat", padx=8,
          command=lambda: show_setup(skip_to_pair=True)).pack(side="right", padx=(0, 4), pady=6)

def refresh_conn_status():
    try:
        if state["connected"]:
            conn_dot.config(fg="#5cb85c")
            conn_lbl.config(text=f"Connected  —  {config.get('ip','')}:{config.get('port','')}")
        else:
            conn_dot.config(fg="#ffaa00")
            conn_lbl.config(text="Connecting…" if is_configured() else "Not configured")
        settings_frame.after(2000, refresh_conn_status)
    except tk.TclError:
        pass

refresh_conn_status()

# Font size
tk.Label(settings_frame, text="Font Size", bg="#1c1810", fg="#e8d5a3",
         font=("Segoe UI", 10)).pack(anchor="w")
size_var = tk.IntVar(value=config["font_size"])

def live_font_update(v=None):
    config["font_size"] = size_var.get()
    _apply_font()
    save_config(config)

tk.Scale(settings_frame, from_=12, to=60, variable=size_var, orient="horizontal",
         bg="#2a2418", fg="#e8d5a3", troughcolor="#3f2f1f", highlightthickness=0,
         command=live_font_update).pack(fill="x", pady=(2, 12))

# Transparency
tk.Label(settings_frame, text="Transparency", bg="#1c1810", fg="#e8d5a3",
         font=("Segoe UI", 10)).pack(anchor="w")
alpha_var = tk.DoubleVar(value=config["alpha"])

def live_alpha_update(v):
    val = max(0.1, min(1.0, float(v)))
    overlay.attributes("-alpha", val)
    config["alpha"] = val
    save_config(config)

tk.Scale(settings_frame, from_=0.4, to=1.0, resolution=0.01, variable=alpha_var,
         orient="horizontal", bg="#2a2418", fg="#e8d5a3", troughcolor="#3f2f1f",
         highlightthickness=0, command=live_alpha_update).pack(fill="x", pady=(2, 12))

# Color
tk.Label(settings_frame, text="Text Color", bg="#1c1810", fg="#e8d5a3",
         font=("Segoe UI", 10)).pack(anchor="w")
color_btn = tk.Button(settings_frame, text=config["color"], bg=config["color"],
                      fg="#111", relief="flat", command=lambda: pick_color())
color_btn.pack(fill="x", ipady=8, pady=(2, 12))

def pick_color():
    result = colorchooser.askcolor(color=config["color"])
    c = result[1] if result else None
    if c:
        config["color"] = c
        color_btn.config(bg=c, text=c)
        for w in (icon_lbl, time_lbl, skull_lbl, pop_lbl):
            w.config(fg=c)
        save_config(config)

# Population toggle
pop_var = tk.BooleanVar(value=config["show_population"])

def toggle_population():
    show = pop_var.get()
    config["show_population"] = show
    save_config(config)
    if show:
        skull_lbl.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(2, 0))
        pop_lbl.grid(row=1, column=1, sticky="w", pady=(2, 0))
    else:
        skull_lbl.grid_remove()
        pop_lbl.grid_remove()

tk.Checkbutton(settings_frame, text="Show server population on overlay",
               variable=pop_var, bg="#1c1810", fg="#e8d5a3", selectcolor="#3f2f1f",
               activebackground="#1c1810", font=("Segoe UI", 10),
               command=toggle_population).pack(anchor="w", pady=(0, 4))

# ── Tracked players ────────────────────────────────────────────────────────────
tracked_var = tk.BooleanVar(value=config.get("show_tracked", True))

def toggle_tracked():
    config["show_tracked"] = tracked_var.get()
    save_config(config)

tk.Checkbutton(settings_frame, text="Track players by Steam ID (via BattleMetrics)",
               variable=tracked_var, bg="#1c1810", fg="#e8d5a3", selectcolor="#3f2f1f",
               activebackground="#1c1810", font=("Segoe UI", 10),
               command=toggle_tracked).pack(anchor="w", pady=(8, 2))

tracked_entry_frame = tk.Frame(settings_frame, bg="#1c1810")
tracked_entry_frame.pack(fill="x", pady=(0, 4))

tk.Label(tracked_entry_frame, text="Player names or Steam IDs (one per line):",
         bg="#1c1810", fg="#887050", font=("Segoe UI", 8)).pack(anchor="w")

tracked_text = tk.Text(tracked_entry_frame, height=3, bg="#2a2418", fg="#e8d5a3",
                       insertbackground="#e8d5a3", relief="flat",
                       font=("Segoe UI", 9), wrap="none")
tracked_text.pack(fill="x", pady=(2, 0))
tracked_text.insert("1.0", "\n".join(config.get("tracked_players", [])))

def save_tracked():
    raw = tracked_text.get("1.0", "end").strip()
    ids = [x.strip() for x in raw.splitlines() if x.strip()]
    config["tracked_players"] = ids
    save_config(config)
    _reset_bm()
    _ensure_bm_running()
    _rebuild_tracked_labels()

btn_row = tk.Frame(tracked_entry_frame, bg="#1c1810")
btn_row.pack(fill="x", pady=(4, 0))

bm_status_lbl = tk.Label(btn_row, text="", bg="#1c1810", fg="#887050",
                          font=("Segoe UI", 8), anchor="w")
bm_status_lbl.pack(side="left", fill="x", expand=True)

tk.Button(btn_row, text="Save", bg="#3f2f1f", fg="#e8d5a3",
          font=("Segoe UI", 9), relief="flat", command=save_tracked).pack(side="right")

def _refresh_bm_status():
    try:
        txt = _bm_status["text"]
        last = _bm_status["last_ok"]
        if txt == "Querying…":
            bm_status_lbl.config(text="⟳ Querying BattleMetrics…", fg="#ffaa00")
        elif txt == "idle" and last is not None:
            ago = int(_time.monotonic() - last)
            if ago < 60:
                bm_status_lbl.config(text=f"✓ Updated {ago}s ago", fg="#5cb85c")
            else:
                m = ago // 60
                bm_status_lbl.config(text=f"✓ Updated {m}m ago", fg="#5cb85c")
        elif txt == "idle":
            bm_status_lbl.config(text="", fg="#887050")
        else:
            bm_status_lbl.config(text=txt, fg="#cc4444")
        settings_frame.after(2000, _refresh_bm_status)
    except tk.TclError:
        pass

_refresh_bm_status()

# ── Crosshair settings ────────────────────────────────────────────────────────
ch_sep = tk.Frame(settings_frame, bg="#3f2f1f", height=1)
ch_sep.pack(fill="x", pady=(16, 12))

tk.Label(settings_frame, text="Crosshair", bg="#1c1810", fg="#e8d5a3",
         font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 4))

# ── Preview (always visible at top of crosshair section) ─────────────────────
ch_preview_frame = tk.Frame(settings_frame, bg="#333333", relief="sunken", bd=1)
ch_preview_frame.pack(fill="x", pady=(0, 8))

ch_preview_canvas = tk.Canvas(ch_preview_frame, width=140, height=140,
                               bg="#333333", highlightthickness=0)
ch_preview_canvas.pack(pady=4)

ch_preset_label = tk.Label(ch_preview_frame, text="", bg="#333333", fg="#aaa",
                            font=("Segoe UI", 8))
ch_preset_label.pack(pady=(0, 4))

def _redraw_preview():
    _ch_draw(ch_preview_canvas, config, 70, 70)
    active = config.get("crosshair_active_preset", "")
    ch_preset_label.config(text=f"Preset: {active}" if active else "")

# Hook preview into every crosshair redraw
_orig_crosshair_redraw = crosshair.redraw
def _redraw_both():
    _orig_crosshair_redraw()
    _redraw_preview()
crosshair.redraw = _redraw_both
_redraw_preview()

# Helper: standard slider builder
_BG = "#1c1810"
_FG = "#e8d5a3"
_SBG = "#2a2418"
_TROUGH = "#3f2f1f"

def _label(parent, text):
    tk.Label(parent, text=text, bg=_BG, fg=_FG, font=("Segoe UI", 10)).pack(anchor="w")

def _slider(parent, var, from_, to_, cmd, res=1):
    tk.Scale(parent, from_=from_, to=to_, resolution=res, variable=var,
             orient="horizontal", bg=_SBG, fg=_FG, troughcolor=_TROUGH,
             highlightthickness=0, command=cmd).pack(fill="x", pady=(2, 8))

def _check(parent, text, var, cmd):
    tk.Checkbutton(parent, text=text, variable=var, bg=_BG, fg=_FG,
                   selectcolor=_TROUGH, activebackground=_BG,
                   font=("Segoe UI", 10), command=cmd).pack(anchor="w", pady=(0, 4))

def _color_btn(parent, key, label_text):
    _label(parent, label_text)
    btn = tk.Button(parent, text=config.get(key, "#00ff00"),
                    bg=config.get(key, "#00ff00"), fg="#111", relief="flat")
    btn.pack(fill="x", ipady=5, pady=(2, 8))
    def _pick():
        result = colorchooser.askcolor(color=config.get(key, "#00ff00"))
        c = result[1] if result else None
        if c:
            config[key] = c
            btn.config(bg=c, text=c)
            save_config(config)
            crosshair.redraw()
    btn.config(command=_pick)
    return btn

def _ch_save_redraw(v=None):
    save_config(config)
    crosshair.redraw()

# ── Enable toggle ─────────────────────────────────────────────────────────────
ch_enabled_var = tk.BooleanVar(value=config.get("crosshair_enabled", False))

def toggle_crosshair_enabled():
    config["crosshair_enabled"] = ch_enabled_var.get()
    save_config(config)
    if config["crosshair_enabled"]:
        crosshair.show()
    else:
        crosshair.hide()

_check(settings_frame, "Enable crosshair overlay", ch_enabled_var, toggle_crosshair_enabled)

# ── Style selector ────────────────────────────────────────────────────────────
_label(settings_frame, "Style")

ch_style_frame = tk.Frame(settings_frame, bg=_BG)
ch_style_frame.pack(fill="x", pady=(2, 4))

_CH_STYLES = [("Cross", "cross"), ("Dot", "dot"), ("Circle", "circle"),
              ("Cross+Dot", "cross_dot"), ("Chevron", "chevron"), ("T-Shape", "t_shape")]
ch_style_var = tk.StringVar(value=config.get("crosshair_style", "cross"))

def _on_style_change():
    config["crosshair_style"] = ch_style_var.get()
    _ch_save_redraw()

# Two rows of radio buttons (3 per row)
_style_row1 = tk.Frame(ch_style_frame, bg=_BG)
_style_row1.pack(fill="x")
_style_row2 = tk.Frame(ch_style_frame, bg=_BG)
_style_row2.pack(fill="x")

for i, (label, val) in enumerate(_CH_STYLES):
    parent = _style_row1 if i < 3 else _style_row2
    tk.Radiobutton(parent, text=label, variable=ch_style_var, value=val,
                   bg=_BG, fg=_FG, selectcolor=_TROUGH,
                   activebackground=_BG, font=("Segoe UI", 9),
                   command=_on_style_change).pack(side="left", padx=(0, 6))

# ── Lines section ─────────────────────────────────────────────────────────────
_color_btn(settings_frame, "crosshair_color", "Line Color")

_label(settings_frame, "Line Length")
ch_size_var = tk.IntVar(value=config.get("crosshair_size", 20))
def _on_size(v=None):
    config["crosshair_size"] = ch_size_var.get()
    _ch_save_redraw()
_slider(settings_frame, ch_size_var, 2, 80, _on_size)

_label(settings_frame, "Line Width")
ch_thick_var = tk.IntVar(value=config.get("crosshair_thickness", 2))
def _on_thick(v=None):
    config["crosshair_thickness"] = ch_thick_var.get()
    _ch_save_redraw()
_slider(settings_frame, ch_thick_var, 1, 10, _on_thick)

_label(settings_frame, "Center Gap")
ch_gap_var = tk.IntVar(value=config.get("crosshair_gap", 4))
def _on_gap(v=None):
    config["crosshair_gap"] = ch_gap_var.get()
    _ch_save_redraw()
_slider(settings_frame, ch_gap_var, 0, 40, _on_gap)

_label(settings_frame, "Opacity")
ch_opacity_var = tk.DoubleVar(value=config.get("crosshair_opacity", 1.0))
def _on_opacity(v=None):
    config["crosshair_opacity"] = max(0.1, min(1.0, float(v)))
    _ch_save_redraw()
_slider(settings_frame, ch_opacity_var, 0.1, 1.0, _on_opacity, res=0.05)

_label(settings_frame, "Rotation (degrees)")
ch_rot_var = tk.IntVar(value=int(config.get("crosshair_rotation", 0)))
def _on_rot(v=None):
    config["crosshair_rotation"] = ch_rot_var.get()
    _ch_save_redraw()
_slider(settings_frame, ch_rot_var, 0, 360, _on_rot)

# ── T-Shape option ────────────────────────────────────────────────────────────
_label(settings_frame, "T-Shape (remove top arm)")
ch_tshape_frame = tk.Frame(settings_frame, bg=_BG)
ch_tshape_frame.pack(fill="x", pady=(2, 8))
ch_tshape_var = tk.StringVar(value=config.get("crosshair_tshape", "never"))
def _on_tshape():
    config["crosshair_tshape"] = ch_tshape_var.get()
    _ch_save_redraw()
for label, val in [("Never", "never"), ("Always", "always")]:
    tk.Radiobutton(ch_tshape_frame, text=label, variable=ch_tshape_var, value=val,
                   bg=_BG, fg=_FG, selectcolor=_TROUGH,
                   activebackground=_BG, font=("Segoe UI", 9),
                   command=_on_tshape).pack(side="left", padx=(0, 10))

# ── Center Dot section ────────────────────────────────────────────────────────
tk.Frame(settings_frame, bg=_TROUGH, height=1).pack(fill="x", pady=(8, 8))
tk.Label(settings_frame, text="Center Dot", bg=_BG, fg=_FG,
         font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))

ch_dot_on_var = tk.BooleanVar(value=config.get("crosshair_dot_enabled", True))
def _toggle_dot():
    config["crosshair_dot_enabled"] = ch_dot_on_var.get()
    _ch_save_redraw()
_check(settings_frame, "Show center dot", ch_dot_on_var, _toggle_dot)

_label(settings_frame, "Dot Size")
ch_dot_var = tk.IntVar(value=config.get("crosshair_dot_size", 3))
def _on_dot(v=None):
    config["crosshair_dot_size"] = ch_dot_var.get()
    _ch_save_redraw()
_slider(settings_frame, ch_dot_var, 1, 20, _on_dot)

_color_btn(settings_frame, "crosshair_dot_color", "Dot Color")

# ── Outline section ───────────────────────────────────────────────────────────
tk.Frame(settings_frame, bg=_TROUGH, height=1).pack(fill="x", pady=(8, 8))
tk.Label(settings_frame, text="Outline", bg=_BG, fg=_FG,
         font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))

ch_outline_var = tk.BooleanVar(value=config.get("crosshair_outline", False))
def _toggle_outline():
    config["crosshair_outline"] = ch_outline_var.get()
    _ch_save_redraw()
_check(settings_frame, "Enable outline (visibility border)", ch_outline_var, _toggle_outline)

_color_btn(settings_frame, "crosshair_outline_color", "Outline Color")

_label(settings_frame, "Outline Thickness")
ch_out_thick_var = tk.IntVar(value=config.get("crosshair_outline_thickness", 2))
def _on_out_thick(v=None):
    config["crosshair_outline_thickness"] = ch_out_thick_var.get()
    _ch_save_redraw()
_slider(settings_frame, ch_out_thick_var, 1, 6, _on_out_thick)

# ── Position ──────────────────────────────────────────────────────────────────
tk.Frame(settings_frame, bg=_TROUGH, height=1).pack(fill="x", pady=(8, 8))
tk.Label(settings_frame, text="Position Offset", bg=_BG, fg=_FG,
         font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))

ch_pos_frame = tk.Frame(settings_frame, bg=_BG)
ch_pos_frame.pack(fill="x", pady=(0, 8))

tk.Label(ch_pos_frame, text="X:", bg=_BG, fg=_FG, font=("Segoe UI", 10)).pack(side="left")
ch_ox_var = tk.IntVar(value=config.get("crosshair_offset_x", 0))
ch_ox_spin = tk.Spinbox(ch_pos_frame, from_=-500, to=500, textvariable=ch_ox_var,
                         width=6, bg=_SBG, fg=_FG, buttonbackground=_TROUGH,
                         relief="flat", font=("Segoe UI", 10))
ch_ox_spin.pack(side="left", padx=(4, 16))

tk.Label(ch_pos_frame, text="Y:", bg=_BG, fg=_FG, font=("Segoe UI", 10)).pack(side="left")
ch_oy_var = tk.IntVar(value=config.get("crosshair_offset_y", 0))
ch_oy_spin = tk.Spinbox(ch_pos_frame, from_=-500, to=500, textvariable=ch_oy_var,
                         width=6, bg=_SBG, fg=_FG, buttonbackground=_TROUGH,
                         relief="flat", font=("Segoe UI", 10))
ch_oy_spin.pack(side="left", padx=(4, 10))

def _on_pos_change(*_):
    try:
        config["crosshair_offset_x"] = ch_ox_var.get()
        config["crosshair_offset_y"] = ch_oy_var.get()
        save_config(config)
        crosshair._centre()
    except (tk.TclError, ValueError):
        pass

ch_ox_var.trace_add("write", _on_pos_change)
ch_oy_var.trace_add("write", _on_pos_change)

tk.Button(ch_pos_frame, text="Reset", bg=_TROUGH, fg=_FG, font=("Segoe UI", 9),
          relief="flat", command=lambda: (ch_ox_var.set(0), ch_oy_var.set(0))).pack(side="left")

# ── Custom Image ──────────────────────────────────────────────────────────────
tk.Frame(settings_frame, bg=_TROUGH, height=1).pack(fill="x", pady=(8, 8))
tk.Label(settings_frame, text="Custom Image", bg=_BG, fg=_FG,
         font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))

ch_img_frame = tk.Frame(settings_frame, bg=_BG)
ch_img_frame.pack(fill="x", pady=(0, 4))

ch_img_path_var = tk.StringVar(value=config.get("crosshair_image_path", ""))
ch_img_entry = tk.Entry(ch_img_frame, textvariable=ch_img_path_var, bg=_SBG, fg=_FG,
                         insertbackground=_FG, relief="flat", font=("Segoe UI", 9))
ch_img_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))

def _browse_image():
    from tkinter import filedialog
    path = filedialog.askopenfilename(
        title="Select crosshair image",
        filetypes=[("Images", "*.png *.gif *.pgm *.ppm"), ("All files", "*.*")]
    )
    if path:
        ch_img_path_var.set(path)
        config["crosshair_image_path"] = path
        _ch_save_redraw()

def _clear_image():
    ch_img_path_var.set("")
    config["crosshair_image_path"] = ""
    _ch_save_redraw()

tk.Button(ch_img_frame, text="Browse", bg=_TROUGH, fg=_FG, font=("Segoe UI", 9),
          relief="flat", command=_browse_image).pack(side="left", padx=(0, 2))
tk.Button(ch_img_frame, text="Clear", bg=_TROUGH, fg=_FG, font=("Segoe UI", 9),
          relief="flat", command=_clear_image).pack(side="left")

_label(settings_frame, "Image Scale")
ch_img_scale_var = tk.DoubleVar(value=config.get("crosshair_image_scale", 1.0))
def _on_img_scale(v=None):
    config["crosshair_image_scale"] = max(0.1, float(v))
    _ch_save_redraw()
_slider(settings_frame, ch_img_scale_var, 0.1, 5.0, _on_img_scale, res=0.1)

# ── ADS Hide ──────────────────────────────────────────────────────────────────
tk.Frame(settings_frame, bg=_TROUGH, height=1).pack(fill="x", pady=(8, 8))
tk.Label(settings_frame, text="Behavior", bg=_BG, fg=_FG,
         font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))

ch_ads_var = tk.BooleanVar(value=config.get("crosshair_ads_hide", False))

def _toggle_ads():
    config["crosshair_ads_hide"] = ch_ads_var.get()
    save_config(config)
    if config["crosshair_ads_hide"]:
        _install_ads_hook(crosshair)

_check(settings_frame, "Hide on right-click (ADS)", ch_ads_var, _toggle_ads)
tk.Label(settings_frame, text="Hides crosshair while right mouse button is held (for ADS/scope)",
         bg=_BG, fg="#887050", font=("Segoe UI", 8), wraplength=440).pack(anchor="w", pady=(0, 8))

# ── Presets ───────────────────────────────────────────────────────────────────
tk.Frame(settings_frame, bg=_TROUGH, height=1).pack(fill="x", pady=(8, 8))
tk.Label(settings_frame, text="Presets", bg=_BG, fg=_FG,
         font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))

ch_preset_frame = tk.Frame(settings_frame, bg=_BG)
ch_preset_frame.pack(fill="x", pady=(0, 4))

ch_preset_name_var = tk.StringVar()
ch_preset_entry = tk.Entry(ch_preset_frame, textvariable=ch_preset_name_var,
                            bg=_SBG, fg=_FG, insertbackground=_FG, relief="flat",
                            font=("Segoe UI", 9), width=20)
ch_preset_entry.pack(side="left", padx=(0, 4))

def _do_preset_save():
    name = ch_preset_name_var.get().strip()
    if not name:
        return
    preset_save(name)
    _rebuild_preset_list()
    crosshair.redraw()

tk.Button(ch_preset_frame, text="Save", bg="#5a8a3a", fg="#fff", font=("Segoe UI", 9),
          relief="flat", command=_do_preset_save).pack(side="left", padx=(0, 4))

def _do_export_png():
    from tkinter import filedialog
    path = filedialog.asksaveasfilename(
        title="Export crosshair as PNG",
        defaultextension=".png",
        filetypes=[("PNG", "*.png")]
    )
    if path:
        ok = preset_export_png(ch_preview_canvas, path)
        if not ok:
            messagebox.showinfo("Export", "Export requires Pillow:\npip install Pillow")

tk.Button(ch_preset_frame, text="Export PNG", bg=_TROUGH, fg=_FG, font=("Segoe UI", 9),
          relief="flat", command=_do_export_png).pack(side="right")

# Preset list (dynamically rebuilt)
ch_preset_list_frame = tk.Frame(settings_frame, bg=_BG)
ch_preset_list_frame.pack(fill="x", pady=(4, 8))

def _rebuild_preset_list():
    for w in ch_preset_list_frame.winfo_children():
        w.destroy()
    names = preset_list()
    active = config.get("crosshair_active_preset", "")
    if not names:
        tk.Label(ch_preset_list_frame, text="No saved presets", bg=_BG, fg="#887050",
                 font=("Segoe UI", 9)).pack(anchor="w")
        return
    for name in names:
        row = tk.Frame(ch_preset_list_frame, bg=_SBG)
        row.pack(fill="x", pady=1)
        indicator = "▸ " if name == active else "   "
        tk.Label(row, text=f"{indicator}{name}", bg=_SBG, fg=_FG,
                 font=("Segoe UI", 9, "bold" if name == active else "normal"),
                 anchor="w").pack(side="left", padx=(6, 0), fill="x", expand=True)
        def _load(n=name):
            if preset_load(n):
                _sync_all_ch_vars()
                crosshair.redraw()
                _rebuild_preset_list()
        def _delete(n=name):
            preset_delete(n)
            _rebuild_preset_list()
            crosshair.redraw()
        tk.Button(row, text="Load", bg=_TROUGH, fg=_FG, font=("Segoe UI", 8),
                  relief="flat", command=_load).pack(side="right", padx=2, pady=2)
        tk.Button(row, text="Del", bg="#663333", fg="#fff", font=("Segoe UI", 8),
                  relief="flat", command=_delete).pack(side="right", padx=2, pady=2)

def _sync_all_ch_vars():
    """Sync all UI variables to current config after preset load."""
    ch_style_var.set(config.get("crosshair_style", "cross"))
    ch_size_var.set(config.get("crosshair_size", 20))
    ch_thick_var.set(config.get("crosshair_thickness", 2))
    ch_gap_var.set(config.get("crosshair_gap", 4))
    ch_opacity_var.set(config.get("crosshair_opacity", 1.0))
    ch_rot_var.set(int(config.get("crosshair_rotation", 0)))
    ch_dot_on_var.set(config.get("crosshair_dot_enabled", True))
    ch_dot_var.set(config.get("crosshair_dot_size", 3))
    ch_outline_var.set(config.get("crosshair_outline", False))
    ch_out_thick_var.set(config.get("crosshair_outline_thickness", 2))
    ch_tshape_var.set(config.get("crosshair_tshape", "never"))
    ch_ox_var.set(config.get("crosshair_offset_x", 0))
    ch_oy_var.set(config.get("crosshair_offset_y", 0))
    ch_ads_var.set(config.get("crosshair_ads_hide", False))
    ch_img_path_var.set(config.get("crosshair_image_path", ""))
    ch_img_scale_var.set(config.get("crosshair_image_scale", 1.0))
    ch_enabled_var.set(config.get("crosshair_enabled", False))

_rebuild_preset_list()

tips = tk.Frame(settings_frame, bg="#2a2418")
tips.pack(fill="x", pady=(12, 0))
tk.Label(tips, text="Controls", bg="#2a2418", fg="#e8d5a3",
         font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 4))
for tip in [
    ("Drag overlay",            "Reposition it on screen"),
    ("Scroll wheel on overlay", "Resize the font"),
    ("Double-click overlay",    "Open this settings panel"),
    ("Right-click overlay",     "Quick menu  (reconnect / exit)"),
    ("Change Server button",    "Re-run setup to pair a new server"),
    ("Ctrl+Shift+X",            "Toggle crosshair on/off"),
    ("Escape",                  "Hide this panel"),
]:
    row = tk.Frame(tips, bg="#2a2418")
    row.pack(fill="x", padx=10, pady=1)
    tk.Label(row, text=tip[0], bg="#2a2418", fg="#e8d5a3",
             font=("Segoe UI", 8, "bold"), width=24, anchor="w").pack(side="left")
    tk.Label(row, text=tip[1], bg="#2a2418", fg="#887050",
             font=("Segoe UI", 8), anchor="w").pack(side="left")
tk.Frame(tips, bg="#2a2418", height=8).pack()

# ── Quit — single clean exit path ─────────────────────────────────────────────
def do_quit():
    stop_connection()          # cancel async task (non-blocking)
    _loop.call_soon_threadsafe(_loop.stop)   # stop the event loop
    try:
        overlay.destroy()
    except Exception:
        pass
    sys.exit(0)

control_panel.protocol("WM_DELETE_WINDOW", do_quit)
control_panel.bind("<Escape>", lambda e: control_panel.withdraw())

# ── Crosshair hotkey (Ctrl+Shift+X) ──────────────────────────────────────────
def _toggle_crosshair_hotkey(e=None):
    crosshair.toggle()
    ch_enabled_var.set(crosshair.visible)

overlay.bind_all("<Control-Shift-x>", _toggle_crosshair_hotkey)
overlay.bind_all("<Control-Shift-X>", _toggle_crosshair_hotkey)

# ── Launch ────────────────────────────────────────────────────────────────────
overlay.deiconify()
control_panel.deiconify()

if not RUSTPLUS_OK:
    messagebox.showwarning(
        "Missing Dependency",
        "The rustplus library is not installed.\n\n"
        f"Open a terminal and run:\n"
        f"    \"{sys.executable}\" -m pip install rustplus\n\n"
        "Then restart Rust Time Overlay."
    )

if is_configured():
    show_settings()
    start_connection()
    _ensure_bm_running()
else:
    show_setup()

control_panel.mainloop()
