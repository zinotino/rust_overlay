import tkinter as tk
from tkinter import ttk, colorchooser, messagebox
import json, os, asyncio, threading, subprocess, pathlib, time, webbrowser, atexit, sys

__version__ = "3.8.0"

try:
    from rustplus import RustSocket, ServerDetails
    RUSTPLUS_OK = True
except ImportError:
    RUSTPLUS_OK = False

CONFIG_FILE = str(pathlib.Path(__file__).parent / "rust_overlay_config.json")

DEFAULTS = {
    "ip": "", "port": 28082, "steamid": 0, "token": 0,
    "x": 1680, "y": 60, "font_size": 28, "alpha": 0.92,
    "color": "#e8d5a3", "show_population": True,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return {**DEFAULTS, **json.load(f)}
        except:
            pass
    return dict(DEFAULTS)

def save_config(c):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(c, f, indent=2)
    except:
        pass

config = load_config()

state = {"time": "--:--", "is_day": True, "connected": False, "population": 0}
_stop = threading.Event()
sock = None

def is_configured():
    return bool(config.get("ip") and config.get("steamid") and config.get("token"))

def node_available():
    try:
        subprocess.check_output("node --version", shell=True, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def steam_linked():
    return os.path.exists(pathlib.Path.home() / "Documents" / "rustplus" / "rustplus.config.json")

async def connection_loop():
    global sock
    while not _stop.is_set():
        if not is_configured():
            await asyncio.sleep(3)
            continue
        try:
            details = ServerDetails(config["ip"], config["port"], config["steamid"], config["token"])
            sock = RustSocket(details)
            await sock.connect()
            state["connected"] = True
            while not _stop.is_set():
                try:
                    t_obj = await sock.get_time()
                    t_str = getattr(t_obj, 'time', None)
                    if t_str and ':' in str(t_str):
                        state["time"] = str(t_str)[:5]
                        hour = int(state["time"].split(':')[0])
                        state["is_day"] = 6 <= hour <= 19
                    if config.get("show_population"):
                        try:
                            info = await sock.get_info()
                            pop = (getattr(info, "players", None)
                                   or getattr(info, "current_players", None)
                                   or getattr(info, "playerCount", 0) or 0)
                            state["population"] = int(pop)
                        except:
                            state["population"] = 0
                except Exception:
                    state["connected"] = False
                    break
                await asyncio.sleep(12)
        except Exception:
            state["connected"] = False
        finally:
            if sock:
                try:
                    await sock.disconnect()
                except:
                    pass
            sock = None
        await asyncio.sleep(15)

def start_connection():
    _stop.clear()
    threading.Thread(target=lambda: asyncio.run(connection_loop()), daemon=True).start()

def restart_connection():
    _stop.set()
    threading.Thread(target=lambda: (time.sleep(1.5), start_connection()), daemon=True).start()

def cleanup():
    _stop.set()
    if sock:
        try:
            asyncio.run(sock.disconnect())
        except:
            pass
    try: overlay.destroy()
    except: pass
    try: control_panel.destroy()
    except: pass
    sys.exit(0)

atexit.register(cleanup)

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

def update_overlay():
    icon_lbl.config(text="☀️" if state["is_day"] else "🌙", fg=config["color"])
    time_lbl.config(text=state["time"], fg=config["color"])
    if config.get("show_population"):
        skull_lbl.config(fg=config["color"])
        pop_lbl.config(text=str(state["population"]) if state["population"] else "", fg=config["color"])
        skull_lbl.grid()
        pop_lbl.grid()
    else:
        skull_lbl.grid_remove()
        pop_lbl.grid_remove()
    overlay.after(600, update_overlay)

update_overlay()

def drag_start(e): overlay._x, overlay._y = e.x, e.y
def drag(e):
    config["x"] = overlay.winfo_x() - overlay._x + e.x
    config["y"] = overlay.winfo_y() - overlay._y + e.y
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

for w in (ovl_frame, icon_lbl, time_lbl, skull_lbl, pop_lbl):
    w.bind("<Button-1>", drag_start)
    w.bind("<B1-Motion>", drag)
    w.bind("<MouseWheel>", resize)
    w.bind("<Double-Button-1>", lambda e: control_panel.deiconify())
    w.bind("<Button-3>", lambda e: show_menu(e))

def show_menu(e):
    m = tk.Menu(overlay, tearoff=0, bg="#1c1810", fg="#e8d5a3")
    m.add_command(label="  ⚙  Open Settings", command=lambda: control_panel.deiconify())
    m.add_command(label="  ⟳  Reconnect",     command=restart_connection)
    m.add_separator()
    m.add_command(label="  ✕  Exit",           command=cleanup)
    m.tk_popup(e.x_root, e.y_root)

# ── Control panel ──────────────────────────────────────────────────────────────
control_panel = tk.Toplevel(overlay)
control_panel.title("Rust Time Overlay")
control_panel.configure(bg="#1c1810")
control_panel.resizable(False, False)

# Set taskbar / window icon
_icon_path = pathlib.Path(__file__).parent / "icon.ico"
if _icon_path.exists():
    try:
        control_panel.iconbitmap(str(_icon_path))
        overlay.iconbitmap(str(_icon_path))
    except Exception:
        pass

style = ttk.Style()
style.theme_use('clam')
style.configure('.', background="#1c1810", foreground="#e8d5a3")

# Header (always visible)
hdr = tk.Frame(control_panel, bg="#2a2418")
hdr.pack(fill="x")
tk.Label(hdr, text="☢", bg="#2a2418", fg="#e8c070",
         font=("Segoe UI Emoji", 32)).pack(side="left", padx=24, pady=10)
tk.Label(hdr, text="Rust Time Overlay", bg="#2a2418", fg="#e8d5a3",
         font=("Segoe UI", 18, "bold")).pack(side="left", pady=10)
tk.Label(hdr, text=f"v{__version__}", bg="#2a2418", fg="#887050",
         font=("Segoe UI", 9)).pack(side="right", padx=24, pady=10)

# Body — swapped between setup_frame and settings_frame
body = tk.Frame(control_panel, bg="#1c1810")
body.pack(fill="both", expand=True, padx=24, pady=16)

setup_frame    = tk.Frame(body, bg="#1c1810")
settings_frame = tk.Frame(body, bg="#1c1810")

def show_setup():
    settings_frame.pack_forget()
    setup_frame.pack(fill="both", expand=True)
    rebuild_setup()
    control_panel.geometry("500x480")

def show_settings():
    setup_frame.pack_forget()
    settings_frame.pack(fill="both", expand=True)
    control_panel.geometry("500x480")

# ── Setup frame ────────────────────────────────────────────────────────────────
tk.Label(setup_frame, text="Get Started",
         font=("Segoe UI", 13, "bold"), bg="#1c1810", fg="#e8d5a3").pack(anchor="w", pady=(0, 12))

# Step indicators — rebuilt each refresh
steps_frame = tk.Frame(setup_frame, bg="#2a2418")
steps_frame.pack(fill="x", pady=(0, 12))

setup_status = tk.Label(setup_frame, text="", font=("Segoe UI", 10),
                         bg="#1c1810", fg="#e8d5a3", wraplength=440, justify="left")
setup_status.pack(anchor="w", pady=(0, 6))

action_frame = tk.Frame(setup_frame, bg="#1c1810")
action_frame.pack(fill="x")

def set_status(msg, color="#e8d5a3"):
    setup_status.config(text=msg, fg=color)

def rebuild_setup():
    """Redraw step indicators and the single context-sensitive action button."""
    for w in steps_frame.winfo_children():
        w.destroy()
    for w in action_frame.winfo_children():
        w.destroy()

    node_ok  = node_available()
    steam_ok = steam_linked()

    steps = [
        (node_ok,  "Node.js installed"),
        (steam_ok, "Steam account linked"),
        (False,    "Pair with your Rust server"),
    ]
    for ok, label in steps:
        row = tk.Frame(steps_frame, bg="#2a2418")
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text="✓" if ok else "○", bg="#2a2418",
                 fg="#5cb85c" if ok else "#555", font=("Segoe UI", 12)).pack(side="left", padx=(0, 10))
        tk.Label(row, text=label, bg="#2a2418",
                 fg="#e8d5a3" if ok else "#887050", font=("Segoe UI", 11)).pack(side="left")

    if not node_ok:
        set_status("Node.js is required for the automated pairing process.", "#ffaa00")
        tk.Button(action_frame, text="Install Node.js  →  nodejs.org",
                  bg="#3f2f1f", fg="#e8d5a3", font=("Segoe UI", 11, "bold"), relief="flat",
                  command=lambda: webbrowser.open("https://nodejs.org")
                  ).pack(fill="x", ipady=12, pady=(0, 6))
        tk.Button(action_frame, text="I've installed it — Check Again",
                  bg="#2a2418", fg="#887050", font=("Segoe UI", 10), relief="flat",
                  command=rebuild_setup).pack(fill="x", ipady=8)

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

def do_link_steam():
    set_status("Opening browser — sign in to Steam, then come back here.", "#ffaa00")
    def run():
        subprocess.call("npx @liamcottle/rustplus.js fcm-register", shell=True)
        overlay.after(0, rebuild_setup)
        overlay.after(0, lambda: set_status("Steam linked! Now click 'Start Listening for Pair'.", "#5cb85c"))
    threading.Thread(target=run, daemon=True).start()

def do_pair_server():
    set_status("Listening… In Rust: Menu → alarm clock icon → Pair. Waiting…", "#ffaa00")
    threading.Thread(target=start_listen, daemon=True).start()

def start_listen():
    proc = subprocess.Popen("npx @liamcottle/rustplus.js fcm-listen",
                            shell=True, stdout=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if "playerToken" in line:
            try:
                s = line.find('{')
                body = json.loads(line[s:])
                config["ip"]      = body["ip"]
                config["port"]    = int(body["port"])
                config["steamid"] = int(body["playerId"])
                config["token"]   = int(body["playerToken"])
                save_config(config)
                restart_connection()
                overlay.after(0, show_settings)
                break
            except:
                pass

rebuild_setup()

# ── Settings frame ─────────────────────────────────────────────────────────────
# Connection status strip
conn_strip = tk.Frame(settings_frame, bg="#2a2418")
conn_strip.pack(fill="x", pady=(0, 16))

conn_dot = tk.Label(conn_strip, text="●", bg="#2a2418", fg="#ffaa00", font=("Segoe UI", 12))
conn_dot.pack(side="left", padx=(12, 6), pady=8)
conn_lbl = tk.Label(conn_strip, text="Connecting…", bg="#2a2418", fg="#e8d5a3", font=("Segoe UI", 10))
conn_lbl.pack(side="left", pady=8)
tk.Button(conn_strip, text="Reconnect", bg="#3f2f1f", fg="#e8d5a3",
          font=("Segoe UI", 9), relief="flat", padx=8,
          command=restart_connection).pack(side="right", padx=12, pady=6)
tk.Button(conn_strip, text="Change Server", bg="#3f2f1f", fg="#887050",
          font=("Segoe UI", 9), relief="flat", padx=8,
          command=show_setup).pack(side="right", padx=(0, 4), pady=6)

def refresh_conn_status():
    if state["connected"]:
        conn_dot.config(fg="#5cb85c")
        conn_lbl.config(text=f"Connected  —  {config.get('ip','')}:{config.get('port','')}")
    else:
        conn_dot.config(fg="#ffaa00")
        conn_lbl.config(text="Connecting…" if is_configured() else "Not configured")
    settings_frame.after(2000, refresh_conn_status)

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
tk.Scale(settings_frame, from_=0.4, to=1.0, resolution=0.01, variable=alpha_var,
         orient="horizontal", bg="#2a2418", fg="#e8d5a3", troughcolor="#3f2f1f",
         highlightthickness=0,
         command=lambda v: (overlay.attributes("-alpha", float(v)),
                            config.__setitem__("alpha", float(v)),
                            save_config(config))).pack(fill="x", pady=(2, 12))

# Color
tk.Label(settings_frame, text="Text Color", bg="#1c1810", fg="#e8d5a3",
         font=("Segoe UI", 10)).pack(anchor="w")
color_btn = tk.Button(settings_frame, text=config["color"], bg=config["color"],
                      fg="#111", relief="flat", command=lambda: pick_color())
color_btn.pack(fill="x", ipady=8, pady=(2, 12))

def pick_color():
    c = colorchooser.askcolor(color=config["color"])[1]
    if c:
        config["color"] = c
        color_btn.config(bg=c, text=c)
        for w in (icon_lbl, time_lbl, skull_lbl, pop_lbl):
            w.config(fg=c)
        save_config(config)

# Population toggle
pop_var = tk.BooleanVar(value=config["show_population"])
tk.Checkbutton(settings_frame, text="Show server population on overlay",
               variable=pop_var, bg="#1c1810", fg="#e8d5a3", selectcolor="#3f2f1f",
               activebackground="#1c1810", font=("Segoe UI", 10),
               command=lambda: (
                   config.__setitem__("show_population", pop_var.get()),
                   save_config(config),
                   (skull_lbl.grid(), pop_lbl.grid()) if pop_var.get()
                   else (skull_lbl.grid_remove(), pop_lbl.grid_remove())
               )).pack(anchor="w", pady=(0, 4))

tk.Label(settings_frame,
         text="Tip: scroll wheel on the overlay resizes it. Drag to reposition.",
         bg="#1c1810", fg="#887050", font=("Segoe UI", 8)).pack(anchor="w", pady=(8, 0))

# ── Footer (always visible) ────────────────────────────────────────────────────
foot = tk.Frame(control_panel, bg="#1c1810")
foot.pack(fill="x", padx=24, pady=(0, 16))

tk.Button(foot, text="Hide  (double-click overlay to reopen)", bg="#3f2f1f", fg="#e8d5a3",
          relief="flat", command=control_panel.withdraw).pack(fill="x", ipady=8, pady=(0, 6))
tk.Button(foot, text="Quit", bg="#cc4444", fg="#ffffff",
          relief="flat", command=cleanup).pack(fill="x", ipady=8)

# ── Cleanup ────────────────────────────────────────────────────────────────────
def cleanup():
    _stop.set()
    if sock:
        try: asyncio.run(sock.disconnect())
        except: pass
    try: overlay.destroy()
    except: pass
    try: control_panel.destroy()
    except: pass
    sys.exit(0)

atexit.register(cleanup)
control_panel.protocol("WM_DELETE_WINDOW", cleanup)
control_panel.bind("<Escape>", lambda e: control_panel.withdraw())

# ── Launch ─────────────────────────────────────────────────────────────────────
overlay.deiconify()
control_panel.deiconify()

if not RUSTPLUS_OK:
    messagebox.showwarning(
        "Missing Dependency",
        "The rustplus library is not installed.\n\n"
        "Open a terminal and run:\n"
        "    pip install rustplus\n\n"
        "Then restart Rust Time Overlay."
    )

if is_configured():
    show_settings()
    start_connection()
else:
    show_setup()

control_panel.mainloop()
