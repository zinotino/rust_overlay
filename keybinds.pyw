"""
Keybind Manager — Rust-specific community command bindings.

Separate process, own config file. Focused on in-game Rust commands (chat,
team, console) and safe combat macros — not generic Windows shortcuts.

Provides:
  - Custom keybind creation with live key recorder
  - Rust chat/team-chat/console command dispatcher (auto-types into game)
  - Database of popular community Rust commands (vanilla + modded) for one-click copy
  - Safe combat macros (heal, med syringe, bandage, hotbar swap) — no recoil/rapid-fire
  - Import/export keybind profiles

Safety: No memory reading, no DLL injection, no rapid-fire / recoil control.
All inputs are standard user-level keystrokes that a player could type by hand.

Usage:
  python keybinds.pyw                   # standalone
  python keybinds.pyw --embedded        # launched from main overlay
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json, os, sys, pathlib, subprocess, threading, time

# ── Paths ─────────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    _base = pathlib.Path(sys.executable).parent
else:
    _base = pathlib.Path(__file__).parent

CONFIG_FILE = str(_base / "keybinds_config.json")

# ── Theme constants ───────────────────────────────────────────────────────────
_BG      = "#1c1810"
_BG2     = "#2a2418"
_FG      = "#e8d5a3"
_FG_DIM  = "#887050"
_TROUGH  = "#3f2f1f"
_GREEN   = "#5a8a3a"
_RED     = "#cc4444"
_ACCENT  = "#e8c070"

# ── Virtual key code tables ───────────────────────────────────────────────────
# Maps Windows VK codes → readable names and back.

VK_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift", 0x11: "Ctrl",
    0x12: "Alt", 0x13: "Pause", 0x14: "CapsLock", 0x1B: "Esc",
    0x20: "Space", 0x21: "PgUp", 0x22: "PgDn", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2C: "PrintScreen", 0x2D: "Insert", 0x2E: "Delete",
    0x5B: "LWin", 0x5C: "RWin",
    0x60: "Num0", 0x61: "Num1", 0x62: "Num2", 0x63: "Num3", 0x64: "Num4",
    0x65: "Num5", 0x66: "Num6", 0x67: "Num7", 0x68: "Num8", 0x69: "Num9",
    0x6A: "Num*", 0x6B: "Num+", 0x6D: "Num-", 0x6E: "Num.", 0x6F: "Num/",
    0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4", 0x74: "F5", 0x75: "F6",
    0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10", 0x7A: "F11", 0x7B: "F12",
    0x90: "NumLock", 0x91: "ScrollLock",
    0xA0: "LShift", 0xA1: "RShift", 0xA2: "LCtrl", 0xA3: "RCtrl",
    0xA4: "LAlt", 0xA5: "RAlt",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
    0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
    # Mouse
    0x01: "LMB", 0x02: "RMB", 0x04: "MMB", 0x05: "Mouse4", 0x06: "Mouse5",
}
# Add A-Z (0x41-0x5A) and 0-9 (0x30-0x39)
for _c in range(0x41, 0x5B):
    VK_NAMES[_c] = chr(_c)
for _c in range(0x30, 0x3A):
    VK_NAMES[_c] = str(_c - 0x30)

NAME_TO_VK = {v: k for k, v in VK_NAMES.items()}

# ── Action types ──────────────────────────────────────────────────────────────
# Focus: installing popular Rust client-side binds via the F1 console.
# A "bind" in Rust is a persistent mapping — once you run
# `bind <key> "<command>"` in F1, Rust remembers it across sessions.
#
# This tool's job: press a hotkey → it opens F1 and types the bind command
# for you, so you can one-click install community-favorite binds like
# autorun, head-lerp toggle, gesture binds, autocraft, fov swap, etc.
#
# param keys:
#   rust_key   = the in-game key to bind (e.g. "n", "mouse4", "f7")
#   command    = the Rust command(s) to bind (e.g. "forward;sprint")
#   console    = raw F1 console command (for run-once things like kill)

ACTION_TYPES = {
    "rust_bind":         {"label": "Install Rust Bind",      "desc": "Run bind <key> \"<cmd>\" in F1 console",    "type": "press"},
    "rust_console":      {"label": "Rust Console Command",   "desc": "Run a one-shot F1 console command",         "type": "press"},
    "toggle_crosshair":  {"label": "Toggle Crosshair",       "desc": "Show/hide crosshair overlay",               "type": "toggle"},
    "toggle_overlay":    {"label": "Toggle Info Overlay",    "desc": "Show/hide time/population overlay",         "type": "toggle"},
    "cycle_preset":      {"label": "Cycle Crosshair Preset", "desc": "Switch to next crosshair preset",           "type": "press"},
    "open_settings":     {"label": "Open Settings Panel",    "desc": "Show the settings window",                  "type": "press"},
    "none":              {"label": "No Action",              "desc": "Keybind placeholder (disabled)",            "type": "press"},
}

# ── Popular keybind database ─────────────────────────────────────────────────
# The client-side binds the Rust community actually uses. Each entry installs
# a persistent `bind <key> "<cmd>"` into Rust via the F1 console — you run it
# once and Rust remembers the bind.
#
# Hotkey column = the key you press in THIS app to trigger install.
# rust_key      = the in-game key that gets bound inside Rust.

POPULAR_BINDS = {
    "Movement": [
        {"name": "Auto-Run (toggle)",       "key": "Ctrl+Alt+1", "action": "rust_bind",
         "params": {"rust_key": "n",      "command": "forward;sprint"}},
        {"name": "Auto-Walk",               "key": "Ctrl+Alt+2", "action": "rust_bind",
         "params": {"rust_key": "mouse4", "command": "forward"}},
        {"name": "Auto-Crouch (hold sprint)", "key": "Ctrl+Alt+3", "action": "rust_bind",
         "params": {"rust_key": "capslock", "command": "+duck"}},
    ],
    "Combat & Aim": [
        {"name": "Head-Lerp Toggle",        "key": "Ctrl+Alt+4", "action": "rust_bind",
         "params": {"rust_key": "f2",     "command": "client.camerabobscale 0;client.camerabobkneesenabled false"}},
        {"name": "ADS FOV 70 (hold)",       "key": "Ctrl+Alt+5", "action": "rust_bind",
         "params": {"rust_key": "mouse2", "command": "+attack2;graphics.fov 70"}},
        {"name": "FOV 90 Reset",            "key": "Ctrl+Alt+6", "action": "rust_bind",
         "params": {"rust_key": "f3",     "command": "graphics.fov 90"}},
        {"name": "Combat Log",              "key": "Ctrl+Alt+7", "action": "rust_bind",
         "params": {"rust_key": "f4",     "command": "combatlog"}},
    ],
    "Crafting (single press)": [
        {"name": "Craft Bandage",           "key": "Ctrl+Alt+Q", "action": "rust_bind",
         "params": {"rust_key": "keypad1", "command": "craft.add -2072273936 1"}},
        {"name": "Craft Syringe",           "key": "Ctrl+Alt+W", "action": "rust_bind",
         "params": {"rust_key": "keypad2", "command": "craft.add 1livestock 1"}},
        {"name": "Craft Wood Arrow x10",    "key": "Ctrl+Alt+E", "action": "rust_bind",
         "params": {"rust_key": "keypad3", "command": "craft.add -1234735557 10"}},
        {"name": "Craft Building Plan",     "key": "Ctrl+Alt+R", "action": "rust_bind",
         "params": {"rust_key": "keypad4", "command": "craft.add 1525520776 1"}},
        {"name": "Craft Hammer",            "key": "Ctrl+Alt+T", "action": "rust_bind",
         "params": {"rust_key": "keypad5", "command": "craft.add -975723312 1"}},
        {"name": "Craft Sleeping Bag",      "key": "Ctrl+Alt+Y", "action": "rust_bind",
         "params": {"rust_key": "keypad6", "command": "craft.add -2036743378 1"}},
    ],
    "Gestures & Emotes": [
        {"name": "Wave",                    "key": "Ctrl+Alt+Z", "action": "rust_bind",
         "params": {"rust_key": "keypad7", "command": "gesture wave"}},
        {"name": "Thumbs Up",               "key": "Ctrl+Alt+X", "action": "rust_bind",
         "params": {"rust_key": "keypad8", "command": "gesture thumbsup"}},
        {"name": "Shrug",                   "key": "Ctrl+Alt+C", "action": "rust_bind",
         "params": {"rust_key": "keypad9", "command": "gesture shrug"}},
        {"name": "Point",                   "key": "Ctrl+Alt+V", "action": "rust_bind",
         "params": {"rust_key": "z",       "command": "gesture point"}},
        {"name": "Chicken",                 "key": "Ctrl+Alt+B", "action": "rust_bind",
         "params": {"rust_key": "x",       "command": "gesture chicken"}},
    ],
    "Graphics Presets": [
        {"name": "Potato Mode (quality 0)", "key": "Ctrl+Alt+8", "action": "rust_bind",
         "params": {"rust_key": "f5", "command": "graphics.quality 0;grass.displace false;gfx.ssaa false"}},
        {"name": "Balanced (quality 3)",    "key": "Ctrl+Alt+9", "action": "rust_bind",
         "params": {"rust_key": "f6", "command": "graphics.quality 3"}},
        {"name": "Ultra (quality 5)",       "key": "Ctrl+Alt+0", "action": "rust_bind",
         "params": {"rust_key": "f7", "command": "graphics.quality 5;gfx.ssaa true"}},
    ],
    "Utility": [
        {"name": "Suicide",                 "key": "Ctrl+Alt+K", "action": "rust_bind",
         "params": {"rust_key": "end",      "command": "kill"}},
        {"name": "Respawn",                 "key": "Ctrl+Alt+H", "action": "rust_bind",
         "params": {"rust_key": "home",     "command": "respawn"}},
        {"name": "Disconnect",              "key": "Ctrl+Alt+D", "action": "rust_bind",
         "params": {"rust_key": "pagedown", "command": "disconnect"}},
    ],
    "Overlay": [
        {"name": "Toggle Crosshair",        "key": "Ctrl+Shift+X", "action": "toggle_crosshair"},
        {"name": "Cycle Preset",            "key": "Ctrl+Shift+C", "action": "cycle_preset"},
        {"name": "Toggle Info Overlay",     "key": "Ctrl+Shift+O", "action": "toggle_overlay"},
        {"name": "Open Settings",           "key": "Ctrl+Shift+S", "action": "open_settings"},
    ],
}

# ── Config persistence ────────────────────────────────────────────────────────

def _load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "binds" in data:
                return data
        except Exception:
            pass
    return {"binds": [], "enabled": True, "profiles": {}}

def _save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

cfg = _load_config()

# ── Key string parsing ────────────────────────────────────────────────────────

def parse_key_string(s):
    """Parse 'Ctrl+Shift+X' → set of modifier names + main key name."""
    parts = [p.strip() for p in s.split("+")]
    mods = set()
    main = None
    for p in parts:
        low = p.lower()
        if low in ("ctrl", "lctrl", "rctrl", "control"):
            mods.add("Ctrl")
        elif low in ("shift", "lshift", "rshift"):
            mods.add("Shift")
        elif low in ("alt", "lalt", "ralt"):
            mods.add("Alt")
        else:
            main = p
    return mods, main

def key_string_from_parts(mods, main):
    """Build display string from modifiers + main key."""
    parts = sorted(mods) + ([main] if main else [])
    return "+".join(parts)

# ── Action executor ───────────────────────────────────────────────────────────

def execute_action(bind):
    """Run the action for a keybind dict. Rust actions run in a background
    thread so the keyboard hook returns fast and input timing stays clean."""
    action = bind.get("action", "none")
    params = bind.get("params", {})

    if action == "none":
        return

    if action == "rust_bind":
        rust_key = params.get("rust_key", "").strip()
        command  = params.get("command", "").strip()
        if rust_key and command:
            # Build the F1 console line:  bind <key> "<command>"
            # Embedded quotes in the command get escaped.
            safe_cmd = command.replace('"', '\\"')
            console_line = f'bind {rust_key} "{safe_cmd}"'
            threading.Thread(target=_rust_send_console, args=(console_line,),
                             daemon=True).start()

    elif action == "rust_console":
        cmd = params.get("console", "")
        threading.Thread(target=_rust_send_console, args=(cmd,),
                         daemon=True).start()

    elif action in ("toggle_crosshair", "toggle_overlay", "cycle_preset", "open_settings"):
        # Handled by the main overlay via IPC
        _signal_overlay(action)

# ── Low-level input helpers (Windows SendInput / keybd_event) ────────────────

def _simulate_key(key_name, hold_ms=0):
    """Press and release a single key by our name (e.g. '1', 'Enter', 'F1', 'LMB')."""
    try:
        import ctypes
        user32 = ctypes.windll.user32

        # Mouse buttons
        MOUSE_EVENTS = {
            "LMB": (0x0002, 0x0004),   # LEFTDOWN, LEFTUP
            "RMB": (0x0008, 0x0010),   # RIGHTDOWN, RIGHTUP
            "MMB": (0x0020, 0x0040),   # MIDDLEDOWN, MIDDLEUP
        }
        if key_name in MOUSE_EVENTS:
            down, up = MOUSE_EVENTS[key_name]
            user32.mouse_event(down, 0, 0, 0, 0)
            if hold_ms > 0:
                time.sleep(hold_ms / 1000.0)
            user32.mouse_event(up, 0, 0, 0, 0)
            return

        vk = NAME_TO_VK.get(key_name)
        if vk is None and len(key_name) == 1:
            vk = ord(key_name.upper())
        if vk:
            user32.keybd_event(vk, 0, 0, 0)
            if hold_ms > 0:
                time.sleep(hold_ms / 1000.0)
            user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
    except Exception:
        pass

def _type_string(text):
    """Type a literal string into the focused window using SendInput-style
    Unicode keystrokes. Uses KEYEVENTF_UNICODE so any character works without
    worrying about keyboard layout or shift state."""
    try:
        import ctypes
        from ctypes import wintypes

        KEYEVENTF_KEYUP    = 0x0002
        KEYEVENTF_UNICODE  = 0x0004
        INPUT_KEYBOARD     = 1

        # Minimal INPUT structure
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk",         wintypes.WORD),
                        ("wScan",       wintypes.WORD),
                        ("dwFlags",     wintypes.DWORD),
                        ("time",        wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class _INPUT_UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

        user32 = ctypes.windll.user32
        extra = ctypes.c_ulong(0)

        for ch in text:
            code = ord(ch)
            for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                inp = INPUT()
                inp.type = INPUT_KEYBOARD
                inp.u.ki = KEYBDINPUT(0, code, flags, 0, ctypes.pointer(extra))
                user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    except Exception:
        pass

def _rust_send_console(cmd):
    """Open F1 console, run a command, close console."""
    if not cmd:
        return
    try:
        # Small delay so hotkey modifiers release before we press F1
        time.sleep(0.06)
        _simulate_key("F1")
        time.sleep(0.18)
        _type_string(cmd)
        time.sleep(0.04)
        _simulate_key("Enter")
        time.sleep(0.08)
        _simulate_key("F1")
    except Exception:
        pass

def _signal_overlay(action):
    """Write an action signal to a temp file the main overlay polls."""
    sig_path = str(_base / ".keybind_signal")
    try:
        with open(sig_path, "w") as f:
            f.write(action)
    except Exception:
        pass

# ── Global keyboard hook ─────────────────────────────────────────────────────

_hook_handle = None
_hook_proc_ref = None  # prevent GC
_active_binds = {}     # {frozenset(vk_codes): bind_dict}
_held_keys = set()     # currently pressed VK codes

def _rebuild_active_binds():
    """Rebuild the lookup table from config."""
    global _active_binds
    _active_binds = {}
    if not cfg.get("enabled", True):
        return
    for bind in cfg.get("binds", []):
        if not bind.get("enabled", True):
            continue
        key_str = bind.get("key", "")
        if not key_str:
            continue
        mods, main = parse_key_string(key_str)
        vk_set = set()
        for m in mods:
            vk = NAME_TO_VK.get(m)
            if vk:
                vk_set.add(vk)
        if main:
            vk = NAME_TO_VK.get(main)
            if vk is None and len(main) == 1:
                vk = ord(main.upper())
            if vk:
                vk_set.add(vk)
        if vk_set:
            _active_binds[frozenset(vk_set)] = bind

def _install_keyboard_hook():
    """Install a Windows low-level keyboard hook."""
    global _hook_handle, _hook_proc_ref
    if _hook_handle is not None:
        return
    try:
        import ctypes
        import ctypes.wintypes as wt

        user32 = ctypes.windll.user32
        WH_KEYBOARD_LL = 13
        WM_KEYDOWN    = 0x0100
        WM_KEYUP      = 0x0101
        WM_SYSKEYDOWN = 0x0104
        WM_SYSKEYUP   = 0x0105

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wt.DWORD),
                ("scanCode", wt.DWORD),
                ("flags", wt.DWORD),
                ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        @ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wt.WPARAM, wt.LPARAM)
        def _kb_proc(nCode, wParam, lParam):
            if nCode >= 0:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = kb.vkCode

                if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    _held_keys.add(vk)
                    # Normalize: map L/R variants to generic
                    check = set(_held_keys)
                    for generic, specifics in [(0x10, (0xA0, 0xA1)),
                                               (0x11, (0xA2, 0xA3)),
                                               (0x12, (0xA4, 0xA5))]:
                        if check & set(specifics):
                            check.add(generic)
                    frozen = frozenset(check)
                    for combo, bind in _active_binds.items():
                        if combo <= frozen:
                            try:
                                root.after(0, lambda b=bind: execute_action(b))
                            except Exception:
                                pass
                            break

                elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                    _held_keys.discard(vk)

            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        _hook_proc_ref = _kb_proc
        _hook_handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _kb_proc, None, 0)

        def _pump():
            msg = wt.MSG()
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            try:
                root.after(16, _pump)
            except tk.TclError:
                pass
        _pump()

    except Exception:
        pass

# ── UI ────────────────────────────────────────────────────────────────────────

root = tk.Tk()
root.title("Keybind Manager")
root.configure(bg=_BG)
root.resizable(False, False)

icon_path = _base / "icon.ico"
if icon_path.exists():
    try:
        root.iconbitmap(str(icon_path))
    except Exception:
        pass

# Header
hdr = tk.Frame(root, bg=_BG2)
hdr.pack(fill="x")
tk.Label(hdr, text="Keybind Manager", bg=_BG2, fg=_FG,
         font=("Segoe UI", 16, "bold")).pack(side="left", padx=20, pady=12)

master_var = tk.BooleanVar(value=cfg.get("enabled", True))
def _toggle_master():
    cfg["enabled"] = master_var.get()
    _save_config(cfg)
    _rebuild_active_binds()

tk.Checkbutton(hdr, text="Enabled", variable=master_var, bg=_BG2, fg=_FG,
               selectcolor=_TROUGH, activebackground=_BG2, font=("Segoe UI", 10),
               command=_toggle_master).pack(side="right", padx=20)

# ── Notebook (tabs) ───────────────────────────────────────────────────────────

style = ttk.Style()
style.theme_use("clam")
style.configure("TNotebook", background=_BG, borderwidth=0)
style.configure("TNotebook.Tab", background=_BG2, foreground=_FG,
                padding=[14, 6], font=("Segoe UI", 10))
style.map("TNotebook.Tab",
          background=[("selected", _TROUGH)],
          foreground=[("selected", _ACCENT)])

nb = ttk.Notebook(root)
nb.pack(fill="both", expand=True, padx=0, pady=0)

# ── Tab 1: My Keybinds ───────────────────────────────────────────────────────

binds_tab = tk.Frame(nb, bg=_BG)
nb.add(binds_tab, text="  My Keybinds  ")

# Toolbar
tb = tk.Frame(binds_tab, bg=_BG)
tb.pack(fill="x", padx=16, pady=(12, 6))

def _add_new_bind():
    _open_bind_editor(None)

tk.Button(tb, text="+ New Keybind", bg=_GREEN, fg="#fff", font=("Segoe UI", 10, "bold"),
          relief="flat", padx=12, command=_add_new_bind).pack(side="left")

def _import_profile():
    path = filedialog.askopenfilename(
        title="Import keybind profile",
        filetypes=[("JSON", "*.json"), ("All", "*.*")]
    )
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            cfg["binds"] = data
        elif isinstance(data, dict) and "binds" in data:
            cfg["binds"] = data["binds"]
        _save_config(cfg)
        _rebuild_bind_list()
        _rebuild_active_binds()
    except Exception as e:
        messagebox.showerror("Import Error", str(e))

def _export_profile():
    path = filedialog.asksaveasfilename(
        title="Export keybind profile",
        defaultextension=".json",
        filetypes=[("JSON", "*.json")]
    )
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"binds": cfg["binds"]}, f, indent=2)
    except Exception as e:
        messagebox.showerror("Export Error", str(e))

tk.Button(tb, text="Import", bg=_TROUGH, fg=_FG, font=("Segoe UI", 9),
          relief="flat", padx=8, command=_import_profile).pack(side="right", padx=(4, 0))
tk.Button(tb, text="Export", bg=_TROUGH, fg=_FG, font=("Segoe UI", 9),
          relief="flat", padx=8, command=_export_profile).pack(side="right")

# Bind list (scrollable)
list_container = tk.Frame(binds_tab, bg=_BG)
list_container.pack(fill="both", expand=True, padx=16, pady=(0, 12))

list_canvas = tk.Canvas(list_container, bg=_BG, highlightthickness=0, bd=0)
list_vsb = tk.Scrollbar(list_container, orient="vertical", command=list_canvas.yview)
list_inner = tk.Frame(list_canvas, bg=_BG)
list_inner.bind("<Configure>",
    lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
list_canvas.create_window((0, 0), window=list_inner, anchor="nw", tags="inner")
list_canvas.configure(yscrollcommand=list_vsb.set)

list_vsb.pack(side="right", fill="y")
list_canvas.pack(side="left", fill="both", expand=True)

def _on_list_resize(e):
    list_canvas.itemconfig("inner", width=e.width)
list_canvas.bind("<Configure>", _on_list_resize)

def _on_list_scroll(e):
    list_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
list_canvas.bind("<Enter>", lambda e: list_canvas.bind_all("<MouseWheel>", _on_list_scroll))
list_canvas.bind("<Leave>", lambda e: list_canvas.unbind_all("<MouseWheel>"))

def _rebuild_bind_list():
    for w in list_inner.winfo_children():
        w.destroy()

    binds = cfg.get("binds", [])
    if not binds:
        tk.Label(list_inner, text="No keybinds configured.\nClick '+ New Keybind' or browse Popular Binds.",
                 bg=_BG, fg=_FG_DIM, font=("Segoe UI", 10), justify="center").pack(pady=40)
        return

    for i, bind in enumerate(binds):
        row = tk.Frame(list_inner, bg=_BG2, relief="flat", bd=0)
        row.pack(fill="x", pady=2)

        enabled = bind.get("enabled", True)

        # Enable checkbox
        ev = tk.BooleanVar(value=enabled)
        def _toggle_en(idx=i, var=ev):
            cfg["binds"][idx]["enabled"] = var.get()
            _save_config(cfg)
            _rebuild_active_binds()
        tk.Checkbutton(row, variable=ev, bg=_BG2, selectcolor=_TROUGH,
                       activebackground=_BG2, command=_toggle_en).pack(side="left", padx=(8, 0))

        # Key badge
        key_text = bind.get("key", "???")
        tk.Label(row, text=f" {key_text} ", bg=_TROUGH, fg=_ACCENT,
                 font=("Consolas", 10, "bold"), relief="ridge", bd=1).pack(side="left", padx=(4, 8), pady=6)

        # Name + action
        name = bind.get("name", "Unnamed")
        action_id = bind.get("action", "none")
        action_label = ACTION_TYPES.get(action_id, {}).get("label", action_id)
        info_frame = tk.Frame(row, bg=_BG2)
        info_frame.pack(side="left", fill="x", expand=True, pady=6)
        tk.Label(info_frame, text=name, bg=_BG2, fg=_FG,
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(anchor="w")
        tk.Label(info_frame, text=action_label, bg=_BG2, fg=_FG_DIM,
                 font=("Segoe UI", 8), anchor="w").pack(anchor="w")

        # Edit / Delete buttons
        def _edit(idx=i):
            _open_bind_editor(idx)
        def _delete(idx=i):
            cfg["binds"].pop(idx)
            _save_config(cfg)
            _rebuild_bind_list()
            _rebuild_active_binds()
        def _move_up(idx=i):
            if idx > 0:
                cfg["binds"][idx], cfg["binds"][idx - 1] = cfg["binds"][idx - 1], cfg["binds"][idx]
                _save_config(cfg)
                _rebuild_bind_list()
        def _move_down(idx=i):
            if idx < len(cfg["binds"]) - 1:
                cfg["binds"][idx], cfg["binds"][idx + 1] = cfg["binds"][idx + 1], cfg["binds"][idx]
                _save_config(cfg)
                _rebuild_bind_list()

        tk.Button(row, text="Del", bg=_RED, fg="#fff", font=("Segoe UI", 8),
                  relief="flat", command=_delete).pack(side="right", padx=(2, 8), pady=6)
        tk.Button(row, text="Edit", bg=_TROUGH, fg=_FG, font=("Segoe UI", 8),
                  relief="flat", command=_edit).pack(side="right", padx=2, pady=6)
        tk.Button(row, text="v", bg=_TROUGH, fg=_FG, font=("Segoe UI", 8),
                  relief="flat", width=2, command=_move_down).pack(side="right", padx=1, pady=6)
        tk.Button(row, text="^", bg=_TROUGH, fg=_FG, font=("Segoe UI", 8),
                  relief="flat", width=2, command=_move_up).pack(side="right", padx=1, pady=6)

_rebuild_bind_list()

# ── Tab 2: Popular Binds ─────────────────────────────────────────────────────

pop_tab = tk.Frame(nb, bg=_BG)
nb.add(pop_tab, text="  Popular Binds  ")

pop_scroll_canvas = tk.Canvas(pop_tab, bg=_BG, highlightthickness=0, bd=0)
pop_vsb = tk.Scrollbar(pop_tab, orient="vertical", command=pop_scroll_canvas.yview)
pop_inner = tk.Frame(pop_scroll_canvas, bg=_BG)
pop_inner.bind("<Configure>",
    lambda e: pop_scroll_canvas.configure(scrollregion=pop_scroll_canvas.bbox("all")))
pop_scroll_canvas.create_window((0, 0), window=pop_inner, anchor="nw", tags="pop_inner")
pop_scroll_canvas.configure(yscrollcommand=pop_vsb.set)

pop_vsb.pack(side="right", fill="y")
pop_scroll_canvas.pack(side="left", fill="both", expand=True)

def _on_pop_resize(e):
    pop_scroll_canvas.itemconfig("pop_inner", width=e.width)
pop_scroll_canvas.bind("<Configure>", _on_pop_resize)

def _on_pop_scroll(e):
    pop_scroll_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
pop_scroll_canvas.bind("<Enter>", lambda e: pop_scroll_canvas.bind_all("<MouseWheel>", _on_pop_scroll))
pop_scroll_canvas.bind("<Leave>", lambda e: pop_scroll_canvas.unbind_all("<MouseWheel>"))

tk.Label(pop_inner, text="Click '+' to add a popular keybind to your list.\nAll binds are fully editable after adding.",
         bg=_BG, fg=_FG_DIM, font=("Segoe UI", 9), justify="center").pack(pady=(12, 8))

for category, binds in POPULAR_BINDS.items():
    # Category header
    cat_frame = tk.Frame(pop_inner, bg=_BG)
    cat_frame.pack(fill="x", padx=16, pady=(10, 2))
    tk.Label(cat_frame, text=category, bg=_BG, fg=_ACCENT,
             font=("Segoe UI", 11, "bold")).pack(anchor="w")

    for bind in binds:
        row = tk.Frame(pop_inner, bg=_BG2)
        row.pack(fill="x", padx=16, pady=1)

        tk.Label(row, text=f" {bind['key']} ", bg=_TROUGH, fg=_ACCENT,
                 font=("Consolas", 10, "bold"), relief="ridge", bd=1).pack(side="left", padx=(8, 8), pady=6)

        info = tk.Frame(row, bg=_BG2)
        info.pack(side="left", fill="x", expand=True, pady=6)
        tk.Label(info, text=bind["name"], bg=_BG2, fg=_FG,
                 font=("Segoe UI", 10), anchor="w").pack(anchor="w")
        action_label = ACTION_TYPES.get(bind.get("action", "none"), {}).get("desc", "")
        tk.Label(info, text=action_label, bg=_BG2, fg=_FG_DIM,
                 font=("Segoe UI", 8), anchor="w").pack(anchor="w")

        def _add_popular(b=bind):
            new_bind = {
                "name": b["name"],
                "key": b["key"],
                "action": b["action"],
                "enabled": True,
            }
            if "params" in b:
                new_bind["params"] = dict(b["params"])
            cfg["binds"].append(new_bind)
            _save_config(cfg)
            _rebuild_bind_list()
            _rebuild_active_binds()
            nb.select(0)  # switch to My Keybinds tab

        tk.Button(row, text="+", bg=_GREEN, fg="#fff", font=("Segoe UI", 10, "bold"),
                  relief="flat", width=3, command=_add_popular).pack(side="right", padx=8, pady=6)

# ── Tab 3: Reference ─────────────────────────────────────────────────────────

ref_tab = tk.Frame(nb, bg=_BG)
nb.add(ref_tab, text="  Reference  ")

ref_scroll_canvas = tk.Canvas(ref_tab, bg=_BG, highlightthickness=0, bd=0)
ref_vsb = tk.Scrollbar(ref_tab, orient="vertical", command=ref_scroll_canvas.yview)
ref_inner = tk.Frame(ref_scroll_canvas, bg=_BG)
ref_inner.bind("<Configure>",
    lambda e: ref_scroll_canvas.configure(scrollregion=ref_scroll_canvas.bbox("all")))
ref_scroll_canvas.create_window((0, 0), window=ref_inner, anchor="nw", tags="ref_inner")
ref_scroll_canvas.configure(yscrollcommand=ref_vsb.set)

ref_vsb.pack(side="right", fill="y")
ref_scroll_canvas.pack(side="left", fill="both", expand=True)

def _on_ref_resize(e):
    ref_scroll_canvas.itemconfig("ref_inner", width=e.width)
ref_scroll_canvas.bind("<Configure>", _on_ref_resize)

def _on_ref_scroll(e):
    ref_scroll_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
ref_scroll_canvas.bind("<Enter>", lambda e: ref_scroll_canvas.bind_all("<MouseWheel>", _on_ref_scroll))
ref_scroll_canvas.bind("<Leave>", lambda e: ref_scroll_canvas.unbind_all("<MouseWheel>"))

tk.Label(ref_inner, text="Available Actions", bg=_BG, fg=_FG,
         font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=16, pady=(12, 8))

for action_id, info in ACTION_TYPES.items():
    if action_id == "none":
        continue
    row = tk.Frame(ref_inner, bg=_BG2)
    row.pack(fill="x", padx=16, pady=1)
    tk.Label(row, text=info["label"], bg=_BG2, fg=_FG,
             font=("Segoe UI", 10, "bold"), anchor="w").pack(side="left", padx=(10, 8), pady=6)
    tk.Label(row, text=f"[{info['type']}]", bg=_BG2, fg=_FG_DIM,
             font=("Segoe UI", 8), anchor="w").pack(side="left", pady=6)
    tk.Label(row, text=info["desc"], bg=_BG2, fg=_FG_DIM,
             font=("Segoe UI", 9), anchor="e").pack(side="right", padx=10, pady=6)

tk.Label(ref_inner, text="\nKey Names", bg=_BG, fg=_FG,
         font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=16, pady=(12, 4))

# Show all known key names in a compact grid
key_grid = tk.Frame(ref_inner, bg=_BG)
key_grid.pack(fill="x", padx=16, pady=(0, 16))

all_keys = sorted(set(VK_NAMES.values()))
cols = 6
for idx, kn in enumerate(all_keys):
    r, c = divmod(idx, cols)
    tk.Label(key_grid, text=kn, bg=_BG2, fg=_FG, font=("Consolas", 8),
             relief="flat", padx=4, pady=1).grid(row=r, column=c, sticky="ew", padx=1, pady=1)
for c in range(cols):
    key_grid.grid_columnconfigure(c, weight=1)

# ── Bind editor dialog ────────────────────────────────────────────────────────

def _open_bind_editor(index):
    """Open a modal dialog to create or edit a keybind.
    index=None for new, integer for edit."""
    is_new = index is None
    bind = {} if is_new else dict(cfg["binds"][index])

    dlg = tk.Toplevel(root)
    dlg.title("New Keybind" if is_new else "Edit Keybind")
    dlg.configure(bg=_BG)
    dlg.resizable(False, False)
    dlg.geometry("420x480")
    dlg.transient(root)
    dlg.grab_set()

    if icon_path.exists():
        try:
            dlg.iconbitmap(str(icon_path))
        except Exception:
            pass

    pad = tk.Frame(dlg, bg=_BG)
    pad.pack(fill="both", expand=True, padx=20, pady=16)

    # Name
    tk.Label(pad, text="Name", bg=_BG, fg=_FG, font=("Segoe UI", 10)).pack(anchor="w")
    name_var = tk.StringVar(value=bind.get("name", ""))
    tk.Entry(pad, textvariable=name_var, bg=_BG2, fg=_FG, insertbackground=_FG,
             relief="flat", font=("Segoe UI", 10)).pack(fill="x", pady=(2, 10))

    # Key (with recorder)
    tk.Label(pad, text="Key Combination", bg=_BG, fg=_FG, font=("Segoe UI", 10)).pack(anchor="w")

    key_frame = tk.Frame(pad, bg=_BG)
    key_frame.pack(fill="x", pady=(2, 10))

    key_var = tk.StringVar(value=bind.get("key", ""))
    key_entry = tk.Entry(key_frame, textvariable=key_var, bg=_BG2, fg=_ACCENT,
                         insertbackground=_FG, relief="flat", font=("Consolas", 11))
    key_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

    _recording = {"active": False}

    def _start_record():
        _recording["active"] = True
        rec_btn.config(text="Press keys...", bg=_RED)
        key_var.set("")

        _rec_mods = set()
        _rec_main = [None]

        def _on_key(event):
            name = event.keysym
            # Map to our naming
            mapped = {
                "Control_L": "Ctrl", "Control_R": "Ctrl",
                "Shift_L": "Shift", "Shift_R": "Shift",
                "Alt_L": "Alt", "Alt_R": "Alt",
            }
            if name in mapped:
                _rec_mods.add(mapped[name])
                key_var.set(key_string_from_parts(_rec_mods, _rec_main[0]))
            else:
                display = name.upper() if len(name) == 1 else name
                # Convert keysym names to our key names
                keysym_map = {
                    "space": "Space", "Return": "Enter", "Escape": "Esc",
                    "BackSpace": "Backspace", "Delete": "Delete", "Insert": "Insert",
                    "Home": "Home", "End": "End", "Prior": "PgUp", "Next": "PgDn",
                    "Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right",
                    "Tab": "Tab", "Caps_Lock": "CapsLock", "Print": "PrintScreen",
                    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4",
                    "F5": "F5", "F6": "F6", "F7": "F7", "F8": "F8",
                    "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
                }
                display = keysym_map.get(name, display)
                _rec_main[0] = display
                key_var.set(key_string_from_parts(_rec_mods, _rec_main[0]))

        def _on_key_up(event):
            if _rec_main[0]:
                _recording["active"] = False
                rec_btn.config(text="Record", bg=_TROUGH)
                dlg.unbind("<KeyPress>")
                dlg.unbind("<KeyRelease>")

        dlg.bind("<KeyPress>", _on_key)
        dlg.bind("<KeyRelease>", _on_key_up)

    rec_btn = tk.Button(key_frame, text="Record", bg=_TROUGH, fg=_FG,
                        font=("Segoe UI", 9), relief="flat", command=_start_record)
    rec_btn.pack(side="right")

    # Action
    tk.Label(pad, text="Action", bg=_BG, fg=_FG, font=("Segoe UI", 10)).pack(anchor="w")
    action_var = tk.StringVar(value=bind.get("action", "none"))
    action_combo = ttk.Combobox(pad, textvariable=action_var, state="readonly",
                                 values=[f"{v['label']}  ({k})" for k, v in ACTION_TYPES.items()])
    # Set current value
    current_action = bind.get("action", "none")
    for idx_a, (k, v) in enumerate(ACTION_TYPES.items()):
        if k == current_action:
            action_combo.current(idx_a)
            break
    action_combo.pack(fill="x", pady=(2, 10))

    style.configure("TCombobox", fieldbackground=_BG2, background=_BG2,
                     foreground=_FG, selectbackground=_TROUGH)

    # Params — two fields, shown/hidden based on action:
    #   rust_bind    → rust_key (in-game key) + command (bind payload)
    #   rust_console → command only (as rust_console one-shot)
    params_frame = tk.Frame(pad, bg=_BG)
    params_frame.pack(fill="x", pady=(2, 10))

    existing_params = bind.get("params", {})

    # Field 1: rust in-game key (for rust_bind only)
    field1_lbl = tk.Label(params_frame, text="In-Game Key (Rust)", bg=_BG, fg=_FG,
                          font=("Segoe UI", 10))
    field1_hint = tk.Label(params_frame, text="", bg=_BG, fg=_FG_DIM,
                           font=("Segoe UI", 8), anchor="w", justify="left")
    rust_key_var = tk.StringVar(value=existing_params.get("rust_key", ""))
    field1_entry = tk.Entry(params_frame, textvariable=rust_key_var, bg=_BG2, fg=_FG,
                            insertbackground=_FG, relief="flat", font=("Consolas", 10))

    # Field 2: command / console text
    field2_lbl = tk.Label(params_frame, text="Command", bg=_BG, fg=_FG,
                          font=("Segoe UI", 10))
    field2_hint = tk.Label(params_frame, text="", bg=_BG, fg=_FG_DIM,
                           font=("Segoe UI", 8), anchor="w", justify="left")
    cmd_var = tk.StringVar(value=(existing_params.get("command")
                                  or existing_params.get("console") or ""))
    field2_entry = tk.Entry(params_frame, textvariable=cmd_var, bg=_BG2, fg=_FG,
                            insertbackground=_FG, relief="flat", font=("Consolas", 10))

    def _layout_params(aid):
        for w in (field1_lbl, field1_hint, field1_entry,
                  field2_lbl, field2_hint, field2_entry):
            w.pack_forget()

        if aid == "rust_bind":
            field1_lbl.pack(anchor="w")
            field1_hint.config(text="Rust key name, e.g. n, mouse4, f5, keypad1, capslock")
            field1_hint.pack(anchor="w")
            field1_entry.pack(fill="x", pady=(0, 8))
            field2_lbl.config(text="Rust Command")
            field2_lbl.pack(anchor="w")
            field2_hint.config(text="Console command(s), e.g. forward;sprint  or  gesture wave")
            field2_hint.pack(anchor="w")
            field2_entry.pack(fill="x")

        elif aid == "rust_console":
            field2_lbl.config(text="Console Command")
            field2_lbl.pack(anchor="w")
            field2_hint.config(text="One-shot F1 command, e.g. kill, respawn, combatlog")
            field2_hint.pack(anchor="w")
            field2_entry.pack(fill="x")

        # overlay actions: no params

    def _update_params(*_):
        txt = action_var.get()
        aid = "none"
        for k, v in ACTION_TYPES.items():
            if txt.startswith(v["label"]):
                aid = k
                break
        _layout_params(aid)
    action_var.trace_add("write", _update_params)
    _update_params()

    # Save / Cancel
    btn_frame = tk.Frame(pad, bg=_BG)
    btn_frame.pack(fill="x", pady=(16, 0))

    def _do_save():
        action_text = action_var.get()
        # Extract action id from "Label  (id)" format
        aid = "none"
        for k, v in ACTION_TYPES.items():
            if action_text.startswith(v["label"]):
                aid = k
                break

        new_bind = {
            "name": name_var.get().strip() or "Unnamed",
            "key": key_var.get().strip(),
            "action": aid,
            "enabled": bind.get("enabled", True),
        }

        # Build params based on action type
        if aid == "rust_bind":
            rk = rust_key_var.get().strip()
            cv = cmd_var.get().strip()
            if rk and cv:
                new_bind["params"] = {"rust_key": rk, "command": cv}
        elif aid == "rust_console":
            cv = cmd_var.get().strip()
            if cv:
                new_bind["params"] = {"console": cv}

        if is_new:
            cfg["binds"].append(new_bind)
        else:
            cfg["binds"][index] = new_bind

        _save_config(cfg)
        _rebuild_bind_list()
        _rebuild_active_binds()
        dlg.destroy()

    tk.Button(btn_frame, text="Save", bg=_GREEN, fg="#fff", font=("Segoe UI", 10, "bold"),
              relief="flat", padx=20, command=_do_save).pack(side="left", padx=(0, 8))
    tk.Button(btn_frame, text="Cancel", bg=_TROUGH, fg=_FG, font=("Segoe UI", 10),
              relief="flat", padx=16, command=dlg.destroy).pack(side="left")

# ── Window sizing ─────────────────────────────────────────────────────────────
root.geometry("520x600")
root.minsize(420, 400)

# ── Start hook and run ────────────────────────────────────────────────────────
_rebuild_active_binds()
_install_keyboard_hook()

root.mainloop()
