"""Smart traffic-light controller for the ShinKong B3 floor -- UI version.

The six IP cameras (A-F) post their detections to this PC over HTTP; the
decisions are made by smart_B3_engine.py (keep both files in one folder) and
sent to the four lights through the ETH-to-RS485 once a second, exactly like
V22 sends its fixed cycle.

    Camera messages   HTTP server on port HTTP_PORT of this PC (192.168.7.170):
                      each camera POSTs e.g. "Box-1_triggered." to /IP-CAM-A.
                      A message is timed by this PC's clock when it arrives;
                      any time the camera writes into the text is ignored.
    Lights            DEFAULT_IP:DEFAULT_PORT (ETH-to-RS485), same packet as V22:
                      55 AA | quantity | (address*8 + colour, number) x 4 | XOR.
                      The lights do not latch, so a packet goes out every
                      second, plus one at once when a car starts or stops
                      holding the lights; a countdown that starts then sets the
                      beat, so each number shows a whole second.  Number 0
                      shows no digits.
    Fixed cycle       If the southbound entry cannot be seen (cameras A and B
                      both failing), the camera server is down, or no camera
                      has sent anything for a long time in the daytime, the
                      greens count down and the V22 cycle takes over until it
                      is safe again.  The operator can also choose it.

Auto run (AUTO_RUN = True), for an unattended PC:
    At program start the camera server starts, the UI connects
    DEFAULT_IP:DEFAULT_PORT and starts smart control by itself, retrying every
    RETRY_SECONDS.  If the link drops it reconnects and carries on.  Stop or
    Disconnect pauses auto run until Start is pressed again.  Only one
    program at a time can drive DEFAULT_IP (V22 and this one exclude each
    other), and only one program can own port HTTP_PORT (stop HTTP_Server.py).
    To launch the program when Windows starts:
        powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Script traffic_light_smart_B3.py
    Windows Firewall must let Python receive on TCP port HTTP_PORT.

UI
    "Smart Control"  connection, Start / Stop, the four lights as they are
                     sent, the cars in the lane with their confidence, the
                     camera status (OK / SUSPECT / OFFLINE) and recent decisions.
    "Settings"       every timing and confidence value; Apply saves them to
                     SETTINGS_FILE next to this file and uses them at once.
    "System Log"     every camera message (RX), packet change (TX) and decision;
                     the newest LOG_MAX_LINES lines.
Daily files (Settings, on by default) in LOG_DIR next to this file:
    B3_log_YYYY-MM-DD.txt        camera messages in HTTP_Server.py's format, so
                                 the B3 log analysis keeps working
    B3_decisions_YYYY-MM-DD.txt  every decision, warning and light change

Run:  python traffic_light_smart_B3.py      (pythonw.exe hides the console)
Test without lights or cameras:
      python smart_B3_engine.py --replay B3_log_1024.txt
"""

import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from collections import deque
from dataclasses import fields
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from smart_B3_engine import (CAMERAS, NAME, S, N, Engine, Settings, fixed_program, label,
                             parse_setting, zone_of_text)

# ==========================================
# Core configuration
# ==========================================
DEFAULT_IP = "192.168.7.161"     # ETH-to-RS485 of the B3 lights
DEFAULT_PORT = 1111
QUANTITY = 4                     # 0x00, 0x01, 0x02, 0x03
HTTP_HOST = ""                   # "" = every address of this PC, including 192.168.7.170
HTTP_PORT = 8000
PC_ADDRESS = "192.168.7.170"     # where the cameras send; only checked, for a warning

WARM_KEEPALIVE = True            # True: all lights flash red 88 / dark while stopped
AUTO_RUN = True                  # connect and start by itself, reconnect after a link loss
RETRY_SECONDS = 5                # wait between automatic connection / server attempts
INSTANCE_MUTEX = "ShinKongTrafficLight"   # + "_" + DEFAULT_IP: one program per ETH-to-RS485

PING_SECONDS = 10                # ping every camera this often
PING_FAILS = 3                   # failed pings in a row = camera offline

HERE = Path(__file__).resolve().parent
SETTINGS_FILE = HERE / "traffic_light_smart_B3_settings.json"
LOG_DIR = HERE / "logs"
LOG_MAX_LINES = 3000
DECISION_LINES = 300             # lines kept in the "recent decisions" box

HEAD = bytes([0x55, 0xAA])
COLOR_CODES = {"green": 1, "yellow": 2, "red": 3, "dark": 4}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ==========================================
# UI configuration
# ==========================================
COLOR_BG = "#1e1e1e"
COLOR_FG = "#e0e0e0"
COLOR_ACCENT = "#007acc"
COLOR_ACCENT_HOVER = "#0098ff"
COLOR_SUCCESS = "#4caf50"
COLOR_WARNING = "#ff9800"
COLOR_ERROR = "#f44336"
COLOR_PANEL = "#2d2d2d"
COLOR_INPUT = "#3e3e3e"
COLOR_TITLE = "#00ccff"
COLOR_LIGHT = {"red": "#ff3232", "green": "#1bff1b", "yellow": "#ffd400", "dark": "#3a3a3a"}
COLOR_SOUTH = "#ffb74d"          # southbound cars in the table
COLOR_NORTH = "#4dd0e1"          # northbound cars
FONT_UI = ("Microsoft JhengHei", 10)
FONT_SMALL = ("Microsoft JhengHei", 9)
FONT_TITLE = ("Microsoft JhengHei", 12)
FONT_BIG = ("Consolas", 22, "bold")
FONT_MONO = ("Consolas", 10)

LEVEL_COLORS = {"INFO": "white", "ERROR": "red", "SUCCESS": COLOR_SUCCESS, "WARN": "yellow",
                "TX": "cyan", "RX": "#9e9e9e", "EVENT": COLOR_SOUTH, "LIGHT": "#80ff80",
                "CORE": "#ff80ff"}


# ----------------------------------------------------------- packet layer

def build_packet(settings):
    """settings[addr] = (color, number) for every address 0..QUANTITY-1."""
    body = bytearray([len(settings)])
    for addr, (color, number) in enumerate(settings):
        body.append((addr << 3) | COLOR_CODES[color])
        body.append(number & 0xFF)
    checksum = 0
    for byte in body:
        checksum ^= byte
    return HEAD + bytes(body) + bytes([checksum])


WARM_PACKET = build_packet([("red", 88)] * QUANTITY)
DARK_PACKET = build_packet([("dark", 0)] * QUANTITY)


def packet_text(settings):
    return "  ".join(f"0x{a:02X}:{c[0].upper()}{n:2d}" for a, (c, n) in enumerate(settings))


# --------------------------------------------------------- camera server

class CameraHandler(BaseHTTPRequestHandler):
    """Answers every camera POST with 200 at once and queues the message with
    this PC's receive time."""

    server_version = "B3Smart/1.0"

    def do_POST(self):
        received = (time.monotonic(), datetime.now())
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 4096)
        except ValueError:
            length = 0
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"OK")
        self.server.inbox.put(("msg", received, self.client_address[0], self.path, body))

    def do_GET(self):
        text = "ShinKong B3 smart traffic light: camera server running\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(text)))
        self.end_headers()
        self.wfile.write(text)

    def log_message(self, fmt, *args):
        pass                        # every message is logged by the controller instead


class CameraServer(threading.Thread):
    """The HTTP server for the cameras; retries the port until it is free."""

    def __init__(self, inbox, log):
        super().__init__(daemon=True)
        self.inbox, self.log = inbox, log
        self.httpd = None
        self.ok = False
        self._stop_event = threading.Event()

    def run(self):
        warned = False
        while not self._stop_event.is_set():
            try:
                httpd = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), CameraHandler)
            except OSError as exc:
                if not warned:
                    self.log(f"Camera server cannot use port {HTTP_PORT}: {exc}. Is "
                             f"HTTP_Server.py still running? Retrying every {RETRY_SECONDS} s", "ERROR")
                    warned = True
                self._stop_event.wait(RETRY_SECONDS)
                continue
            httpd.daemon_threads = True
            httpd.inbox = self.inbox
            self.httpd = httpd
            self.ok = True
            self.log(f"Camera server listening on port {HTTP_PORT}", "SUCCESS")
            try:
                httpd.serve_forever(poll_interval=0.5)
            except Exception as exc:           # noqa: BLE001 - keep the controller alive
                self.log(f"Camera server stopped: {exc}", "ERROR")
            finally:
                self.ok = False
                httpd.server_close()
            warned = False

    def stop(self):
        self._stop_event.set()
        if self.httpd is not None:
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()


# ----------------------------------------------------------- camera ping

class Pinger(threading.Thread):
    """Pings every camera; PING_FAILS failures in a row = offline."""

    def __init__(self, log):
        super().__init__(daemon=True)
        self.log = log
        self.offline = frozenset()
        self._fails = {cam: 0 for cam in CAMERAS}
        self._stop_event = threading.Event()
        self.available = True

    def _ping(self, ip):
        if sys.platform == "win32":
            cmd = ["ping", "-n", "1", "-w", "1000", ip]
            flags = 0x08000000                  # CREATE_NO_WINDOW: no console under pythonw
        else:
            cmd, flags = ["ping", "-c", "1", "-W", "1", ip], 0
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=5, creationflags=flags)
        return result.returncode == 0

    def run(self):
        while not self._stop_event.is_set():
            for cam, ip in CAMERAS.items():
                try:
                    ok = self._ping(ip)
                except FileNotFoundError:
                    self.available = False
                    self.log("No ping command on this PC; cameras are judged by their "
                             "messages only", "WARN")
                    return
                except (OSError, subprocess.SubprocessError):
                    ok = False
                if ok:
                    if self._fails[cam] >= PING_FAILS:
                        self.log(f"Camera {cam} ({ip}) answers ping again", "INFO")
                    self._fails[cam] = 0
                else:
                    self._fails[cam] += 1
                    if self._fails[cam] == PING_FAILS:
                        self.log(f"Camera {cam} ({ip}) does not answer ping", "WARN")
            self.offline = frozenset(c for c, n in self._fails.items() if n >= PING_FAILS)
            self._stop_event.wait(PING_SECONDS)

    def stop(self):
        self._stop_event.set()


# ------------------------------------------------------------ daily files

class DailyFiles:
    """Camera messages (HTTP_Server.py format) and decisions, one file per day."""

    def __init__(self):
        self.enabled = True
        self._lock = threading.Lock()
        self._open = {}                     # kind -> (date, file)

    def _file(self, kind, now):
        day = now.strftime("%Y-%m-%d")
        current = self._open.get(kind)
        if current and current[0] == day:
            return current[1]
        if current:
            current[1].close()
        LOG_DIR.mkdir(exist_ok=True)
        f = open(LOG_DIR / f"B3_{kind}_{day}.txt", "a", encoding="utf-8", buffering=1)
        self._open[kind] = (day, f)
        return f

    def message(self, now, ip, path, body):
        if not self.enabled:
            return
        stamp = f"{now.day:02d}/{MONTHS[now.month - 1]}/{now.year} {now:%H:%M:%S}"
        text = " ".join(body.split()) or "-"
        with self._lock:
            try:
                self._file("log", now).write(f"[Received POST text]: {text}\n"
                                             f'{ip} - - [{stamp}] "POST {path} HTTP/1.1" 200 -\n\n')
            except OSError:
                pass

    def decision(self, now, level, msg):
        if not self.enabled:
            return
        with self._lock:
            try:
                self._file("decisions", now).write(f"{now:%Y-%m-%d %H:%M:%S} [{level}] {msg}\n")
            except OSError:
                pass

    def close(self):
        with self._lock:
            for _, f in self._open.values():
                f.close()
            self._open = {}


# ------------------------------------------------------------- controller

class Controller(threading.Thread):
    """Owns the engine: takes the camera messages in order of arrival, sends a
    packet every second (and one at once when a car starts or stops holding the
    lights) and leaves a snapshot for the screen.  Nothing else touches the
    engine, so camera messages and packets never race each other."""

    def __init__(self, app, settings):
        super().__init__(daemon=True)
        self.app = app
        self.inbox = queue.Queue()
        self.engine = Engine(settings, self._engine_log)
        self.engine.started = time.monotonic()
        self.snapshot = None
        self.running = False                # Start pressed: send the engine's lights
        self._stop_event = threading.Event()
        self._recent = {cam: deque() for cam in CAMERAS}   # receive times, last 60 s
        self._warned = set()
        self._last_tx = None
        self._warm = False
        self.show_packets = False
        self._failsafe = None               # second of the V22 cycle after an engine error
        self._countdown = []                # greens counting down before that cycle

    def _engine_log(self, msg, level="INFO"):
        self.app.log(msg, level, decision=True)

    # -------------------------------------------------------------- loop
    def run(self):
        next_tick = time.monotonic() + 1.0
        while not self._stop_event.is_set():
            due = self.engine.next_deadline()
            wake = next_tick if due is None else min(next_tick, due)
            try:
                item = self.inbox.get(timeout=max(0.0, wake - time.monotonic()))
            except queue.Empty:
                item = None
            if item is not None:
                try:
                    started = self._handle(item)
                    if started is not None:     # each number of the countdown shows a whole second
                        next_tick = started + 1.0
                except Exception:               # noqa: BLE001 - never stop sending
                    self.app.log(traceback.format_exc(), "ERROR")
                continue
            now = time.monotonic()
            if now >= next_tick:
                self._send(extra=False)
                next_tick += 1.0
                if next_tick < now:             # the PC stalled: do not burst packets
                    next_tick = now + 1.0
            elif due is not None and now >= due:
                self._send(extra=True)          # a countdown ends between two seconds

    def _handle(self, item):
        """Process one inbox item; returns the start time of a countdown that this
        message started (the once-a-second packets then follow that countdown)."""
        kind = item[0]
        if kind == "msg":
            _, (mono, wall), ip, path, body = item
            self._message(mono, wall, ip, path, body)
            if self.engine.demand_changed():
                counting = self._counting()
                self._send(extra=True)
                if self._counting() - counting:
                    return self.engine.now
        elif kind == "settings":
            self.engine.settings = item[1]
            self.app.log("Settings applied", "INFO", decision=True)
        elif kind == "fixed":
            self.engine.forced_fixed = item[1]
            self.app.log("Fixed cycle chosen by the operator" if item[1]
                         else "Smart control chosen by the operator", "WARN", decision=True)

    def _counting(self):
        lights = self.engine.lights
        if lights.mode != "smart" or self._failsafe is not None:
            return set()
        return {name for name, (st, _) in (("south", lights.south), ("north", lights.north))
                if st == "count"}

    def _message(self, mono, wall, ip, path, body):
        cam = next((c for c, cip in CAMERAS.items() if cip == ip), None)
        if cam is None:
            m = re.search(r"IP-CAM-([A-Z])", path)
            cam = m.group(1) if m and m.group(1) in CAMERAS else None
        zone = zone_of_text(body)
        self.app.files.message(wall, ip, path, body)
        if cam is None or zone is None:
            key = (ip, path, body[:40])
            if key not in self._warned:
                self._warned.add(key)
                self.app.log(f"Ignored a message from {ip} {path}: {body[:60]!r}", "WARN")
            return
        recent = self._recent[cam]
        recent.append(mono)
        while recent and mono - recent[0] > 60:
            recent.popleft()
        self.app.log(f"{label((cam, zone))}", "RX")
        self.engine.message(mono, cam, zone)

    def _lights(self, extra):
        """The engine's lights.  If the engine fails, the greens count down and
        the V22 cycle runs (fail safe); when it works again it carries on with
        that cycle and returns to smart control after the all-red clearance."""
        engine = self.engine
        try:
            settings = engine.tick(time.monotonic(), datetime.now(), offline=self.app.pinger.offline,
                                   server_ok=self.app.server.ok, extra=extra)
        except Exception:                       # noqa: BLE001 - lights must never go dark
            if extra:
                return None
            if self._failsafe is None:
                self.app.log("Engine error, running the fixed cycle:\n" + traceback.format_exc(),
                             "ERROR", decision=True)
                shown = engine.lights.shown or [("green", 0), ("red", 0), ("green", 0), ("green", 0)]
                self._countdown = [(n if 0 < n < 3 else 3) if c == "green" else 0 for c, n in shown]
                self._failsafe = 0
            if any(self._countdown):
                blank = engine.settings.blank_number
                settings = [("green", n) if n else ("red", blank) for n in self._countdown]
                self._countdown = [max(0, n - 1) for n in self._countdown]
                return settings
            program = fixed_program(engine.settings)
            settings = program[self._failsafe % len(program)]
            self._failsafe += 1
            return settings
        if self._failsafe is not None:          # works again: continue the same cycle
            lights = engine.lights
            if any(self._countdown):
                lights.mode, lights.transition = "to_fixed", list(self._countdown)
            else:
                lights.program = fixed_program(engine.settings)
                lights.mode, lights.second = "fixed", self._failsafe % len(lights.program)
            lights.south, lights.north = ("hold", None), ("allred", None)
            self._failsafe = None
            self.app.log("Engine works again; smart control returns after the fixed cycle's "
                         "all-red clearance", "WARN", decision=True)
            settings = lights.step(False, False, 0, 0, bool(engine.fixed_reason))
        return settings

    def _send(self, extra):
        app = self.app
        mono = time.monotonic()
        settings = self._lights(extra)
        if settings is None:
            return
        sock = app.sock
        packet = None
        if sock is not None:
            if self.running:
                packet = build_packet(settings)
                text = packet_text(settings)
                if self.show_packets or text != self._last_tx:
                    app.log(f"{text}  ->  {packet.hex(' ').upper()}", "TX")
                self._last_tx = text
            elif WARM_KEEPALIVE and not extra:
                self._warm = not self._warm
                packet = WARM_PACKET if self._warm else DARK_PACKET
        if packet is not None:
            try:
                with app.sock_lock:
                    sock.sendall(packet)
            except OSError as exc:
                app.after_safe(app.on_link_error, exc)
        try:
            self._snapshot(settings, mono)
        except Exception:                       # noqa: BLE001 - the screen is not essential
            self.app.log(traceback.format_exc(), "ERROR")

    def _snapshot(self, settings, mono):
        e = self.engine
        offline = self.app.pinger.offline
        cams = {}
        for cam, (status, detail) in e.camera_status(offline).items():
            last = e.last_cam.get(cam)
            cams[cam] = {"status": status, "detail": detail,
                         "ago": None if last is None else mono - last,
                         "rate": len([t for t in self._recent[cam] if mono - t <= 60])}
        self.snapshot = {
            "lights": settings, "south": e.lights.south, "north": e.lights.north,
            "mode": e.lights.mode, "fixed_reason": e.fixed_reason, "cars": e.vehicles_view(),
            "cameras": cams, "holders": {d: e.holders(d) for d in (S, N)},
            "red_since": {d: (None if t is None else mono - t)
                          for d, t in e.lights.red_since.items()},
            "running": self.running, "connected": self.app.sock is not None,
        }

    def stop(self):
        self._stop_event.set()


# ------------------------------------------------------------------- UI

class ModernButton(tk.Button):
    def __init__(self, master, **kwargs):
        bg_color = kwargs.pop("bg", COLOR_ACCENT)
        fg_color = kwargs.pop("fg", "white")
        super().__init__(master, **kwargs)
        self.configure(bg=bg_color, fg=fg_color, relief=tk.FLAT, font=FONT_UI,
                       activebackground=COLOR_ACCENT_HOVER, activeforeground="white",
                       disabledforeground="#888888", cursor="hand2", padx=14, pady=6)


class LightsView(tk.Canvas):
    """The lights as they are sent: one row per light group."""

    ROWS = [("0x00", "HuoShih arterial", 0), ("0x01", "Lane exit to HuoShih", 1),
            ("0x02 / 0x03", "GuiLan main lanes", 2)]

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=COLOR_BG, highlightthickness=0, width=420, height=330, **kwargs)
        self.lights = None
        self.notes = ["", "", ""]
        self.sent = False

    def show(self, lights, notes, sent):
        if (lights, notes, sent) == (self.lights, self.notes, self.sent):
            return
        self.lights, self.notes, self.sent = lights, notes, sent
        self.delete("all")
        self.create_text(10, 10, anchor="nw", text="Lights" + ("" if sent else "   (not sent)"),
                         fill=COLOR_TITLE, font=FONT_TITLE)
        for row, (name, where, addr) in enumerate(self.ROWS):
            y = 50 + row * 92
            color, number = lights[addr] if lights else ("dark", 0)
            fill = COLOR_LIGHT.get(color, COLOR_LIGHT["dark"])
            self.create_oval(14, y, 84, y + 70, fill=fill, outline="#cccccc", width=2)
            if number and color != "dark":
                self.create_text(49, y + 35, text=str(number), fill="black", font=FONT_BIG)
            self.create_text(100, y + 8, anchor="nw", text=f"{name}  {where}", fill=COLOR_FG,
                             font=FONT_TITLE)
            self.create_text(100, y + 34, anchor="nw", text=notes[row], fill="#b0b0b0",
                             font=FONT_UI, width=310)


class SmartApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LED Control System Ultimate - Smart Traffic Lights B3 (ShinKong)")
        self.geometry("1600x900")
        self.configure(bg=COLOR_BG)
        self._setup_style()

        self._log_queue = queue.Queue()
        self._decisions = queue.Queue()
        self.sock = None
        self.sock_lock = threading.Lock()
        self.keep_running = AUTO_RUN
        self._retry_job = None
        self.files = DailyFiles()

        settings, app_opts = self._load_settings()
        self.files.enabled = app_opts.get("save_files", True)

        self.setup_ui(settings, app_opts)
        self._drain_log_queue()

        self._stdout, self._stderr = sys.stdout, sys.stderr
        sys.stdout = LogRedirector(self.log, "CORE")
        sys.stderr = LogRedirector(self.log, "ERROR")

        self.controller = Controller(self, settings)
        self.controller.show_packets = app_opts.get("show_packets", False)
        self.server = CameraServer(self.controller.inbox, self.log)
        self.pinger = Pinger(self.log)
        self.server.start()
        self.pinger.start()
        self.controller.start()
        self._check_address()
        self.log(f"Started (AUTO_RUN={AUTO_RUN}, lights {DEFAULT_IP}:{DEFAULT_PORT}, "
                 f"cameras on port {HTTP_PORT})")
        self._refresh_view()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.keep_running:
            self._retry_job = self.after(1000, self._auto_connect)

    # ------------------------------------------------------------ style
    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=COLOR_PANEL, foreground="lightgray",
                        padding=[15, 5], font=FONT_UI)
        style.map("TNotebook.Tab", background=[("selected", COLOR_ACCENT)],
                  foreground=[("selected", "white")])
        style.configure("TFrame", background=COLOR_BG)
        style.configure("Treeview", background=COLOR_PANEL, fieldbackground=COLOR_PANEL,
                        foreground=COLOR_FG, font=FONT_UI, rowheight=24)
        style.configure("Treeview.Heading", background=COLOR_INPUT, foreground=COLOR_FG,
                        font=FONT_UI)
        style.configure("TCombobox", fieldbackground=COLOR_INPUT, background=COLOR_INPUT,
                        foreground=COLOR_FG, arrowcolor=COLOR_FG)
        style.map("TCombobox", fieldbackground=[("readonly", COLOR_INPUT)],
                  foreground=[("readonly", COLOR_FG)], selectbackground=[("readonly", COLOR_INPUT)],
                  selectforeground=[("readonly", COLOR_FG)])

    # -------------------------------------------------------------- log
    def log(self, msg, level="INFO", decision=False):
        """Thread-safe: callable from any thread."""
        now = datetime.now()
        line = f"[{now:%H:%M:%S}] [{level}] {msg}"
        self._log_queue.put((line, level))
        if decision or level in ("WARN", "ERROR", "SUCCESS"):
            self._decisions.put((f"{now:%H:%M:%S}  {msg}", level))
        if level not in ("RX", "TX"):
            self.files.decision(now, level, msg)

    def after_safe(self, fn, *args):
        """Run fn on the UI thread (from any thread)."""
        try:
            self.after(0, fn, *args)
        except (RuntimeError, tk.TclError):
            pass                                # window closing

    def _drain_log_queue(self):
        for widget, q, limit in ((self.log_display, self._log_queue, LOG_MAX_LINES),
                                 (self.decision_box, self._decisions, DECISION_LINES)):
            lines = []
            try:
                while True:
                    lines.append(q.get_nowait())
            except queue.Empty:
                pass
            if lines:
                widget.config(state=tk.NORMAL)
                for text, level in lines:
                    widget.insert(tk.END, text + "\n", level)
                total = int(widget.index("end-1c").split(".")[0])
                if total > limit:
                    widget.delete("1.0", f"{total - limit}.0")
                widget.see(tk.END)
                if widget is self.decision_box:
                    widget.config(state=tk.DISABLED)
        self.after(100, self._drain_log_queue)

    # --------------------------------------------------------------- ui
    def setup_ui(self, settings, app_opts):
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tab_main = ttk.Frame(self.tabs)
        self.tabs.add(tab_main, text="🚦 Smart Control")
        self.setup_main_tab(tab_main)
        tab_set = ttk.Frame(self.tabs)
        self.tabs.add(tab_set, text="⚙ Settings")
        self.setup_settings_tab(tab_set, settings, app_opts)
        tab_log = ttk.Frame(self.tabs)
        self.tabs.add(tab_log, text="📜 System Log")
        self.log_display = self._text_box(tab_log, ("Consolas", 9))
        self.log_display.pack(fill=tk.BOTH, expand=True)

    def _text_box(self, parent, font):
        box = scrolledtext.ScrolledText(parent, bg="#000000", fg="white", font=font)
        for level, color in LEVEL_COLORS.items():
            box.tag_config(level, foreground=color)
        return box

    def _entry(self, parent, default, width=18):
        entry = tk.Entry(parent, bg=COLOR_INPUT, fg=COLOR_FG, font=FONT_MONO, width=width,
                         insertbackground=COLOR_FG, disabledbackground=COLOR_PANEL,
                         disabledforeground="gray")
        entry.insert(0, str(default))
        return entry

    def _label(self, parent, text, fg=COLOR_FG, font=FONT_UI, bg=COLOR_BG, **kw):
        return tk.Label(parent, text=text, bg=bg, fg=fg, font=font, **kw)

    def setup_main_tab(self, parent):
        # --- top bar: lights connection, camera server, mode, Start / Stop
        top = tk.Frame(parent, bg=COLOR_BG)
        top.pack(fill=tk.X, padx=10, pady=(10, 4))
        self._label(top, "Lights IP:", fg=COLOR_ACCENT_HOVER).grid(row=0, column=0, sticky="e")
        self.ip_entry = self._entry(top, DEFAULT_IP, width=15)
        self.ip_entry.grid(row=0, column=1, padx=5)
        self._label(top, "Port:").grid(row=0, column=2, sticky="e")
        self.port_entry = self._entry(top, DEFAULT_PORT, width=6)
        self.port_entry.grid(row=0, column=3, padx=5)
        self.btn_connect = ModernButton(top, text="Connect ETH-to-RS485", command=self.net_connect,
                                        bg=COLOR_SUCCESS)
        self.btn_connect.grid(row=0, column=4, padx=5)
        self.btn_disconnect = ModernButton(top, text="Disconnect", command=self.net_disconnect,
                                           bg=COLOR_ERROR, state=tk.DISABLED)
        self.btn_disconnect.grid(row=0, column=5, padx=5)
        self.net_status_var = tk.StringVar(value="Disconnected")
        self.net_status_label = self._label(top, "", fg=COLOR_ERROR, width=16, anchor="w")
        self.net_status_label.config(textvariable=self.net_status_var)
        self.net_status_label.grid(row=0, column=6, padx=8)
        self.btn_start = ModernButton(top, text="Start", command=self.start_control,
                                      bg=COLOR_WARNING, state=tk.DISABLED)
        self.btn_start.grid(row=0, column=7, padx=(20, 5))
        self.btn_stop = ModernButton(top, text="Stop", command=self.stop_control,
                                     bg=COLOR_WARNING, state=tk.DISABLED)
        self.btn_stop.grid(row=0, column=8, padx=5)
        self.fixed_var = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Run the fixed cycle (V22) instead", variable=self.fixed_var,
                       command=self._on_fixed_toggled, bg=COLOR_BG, fg=COLOR_FG,
                       selectcolor=COLOR_INPUT, activebackground=COLOR_BG,
                       activeforeground=COLOR_FG, font=FONT_UI).grid(row=0, column=9, padx=15)

        status = tk.Frame(parent, bg=COLOR_BG)
        status.pack(fill=tk.X, padx=10, pady=(4, 8))
        self.mode_var = tk.StringVar(value="Starting ...")
        self.mode_label = self._label(status, "", fg=COLOR_TITLE, font=FONT_TITLE)
        self.mode_label.config(textvariable=self.mode_var)
        self.mode_label.pack(side=tk.LEFT)
        self.server_var = tk.StringVar(value="")
        server_label = self._label(status, "", fg="#b0b0b0")
        server_label.config(textvariable=self.server_var)
        server_label.pack(side=tk.RIGHT)

        # --- middle: lights | cars | cameras
        mid = tk.Frame(parent, bg=COLOR_BG)
        mid.pack(fill=tk.BOTH, expand=True, padx=10)
        self.lights_view = LightsView(mid)
        self.lights_view.pack(side=tk.LEFT, anchor=tk.N)

        cars = tk.Frame(mid, bg=COLOR_BG)
        cars.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        self._label(cars, "Cars", fg=COLOR_TITLE, font=FONT_TITLE).pack(anchor=tk.W)
        cols = ("id", "dir", "score", "where", "state", "age", "quiet")
        self.car_table = ttk.Treeview(cars, columns=cols, show="headings", height=10)
        for col, text, width in (("id", "#", 45), ("dir", "Direction", 95),
                                 ("score", "Confidence", 85), ("where", "Where", 130),
                                 ("state", "State", 120), ("age", "Age s", 55),
                                 ("quiet", "Silent s", 65)):
            self.car_table.heading(col, text=text)
            self.car_table.column(col, width=width, anchor=tk.W if col in ("where", "state", "dir")
                                  else tk.CENTER)
        self.car_table.tag_configure(S, foreground=COLOR_SOUTH)
        self.car_table.tag_configure(N, foreground=COLOR_NORTH)
        self.car_table.tag_configure("candidate", foreground="#8a8a8a")
        self.car_table.pack(fill=tk.BOTH, expand=True)

        cams = tk.Frame(mid, bg=COLOR_BG)
        cams.pack(side=tk.LEFT, fill=tk.Y, anchor=tk.N)
        self._label(cams, "Cameras", fg=COLOR_TITLE, font=FONT_TITLE).pack(anchor=tk.W)
        self.cam_table = ttk.Treeview(cams, columns=("cam", "ip", "status", "last", "rate",
                                                     "detail"), show="headings", height=6)
        for col, text, width in (("cam", "Cam", 45), ("ip", "IP", 118), ("status", "Status", 75),
                                 ("last", "Last msg", 75), ("rate", "Msg/min", 65),
                                 ("detail", "Suspect zones", 130)):
            self.cam_table.heading(col, text=text)
            self.cam_table.column(col, width=width, anchor=tk.W)
        for status, color in (("OK", COLOR_SUCCESS), ("SUSPECT", COLOR_WARNING),
                              ("OFFLINE", COLOR_ERROR)):
            self.cam_table.tag_configure(status, foreground=color)
        for cam, ip in CAMERAS.items():
            self.cam_table.insert("", tk.END, iid=cam, values=(cam, ip, "-", "-", "0", ""))
        self.cam_table.pack(anchor=tk.N)

        # --- bottom: recent decisions
        self._label(parent, "Recent decisions", fg=COLOR_TITLE, font=FONT_TITLE).pack(
            anchor=tk.W, padx=10, pady=(8, 0))
        self.decision_box = self._text_box(parent, FONT_MONO)
        self.decision_box.config(height=12, state=tk.DISABLED)
        self.decision_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 10))

    def setup_settings_tab(self, parent, settings, app_opts):
        canvas = tk.Canvas(parent, bg=COLOR_BG, highlightthickness=0)
        bar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        inner = tk.Frame(canvas, bg=COLOR_BG)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bar.pack(side=tk.RIGHT, fill=tk.Y)

        self.setting_widgets = {}
        defaults = Settings()
        groups = {}
        for f in fields(Settings):
            groups.setdefault(f.metadata["group"], []).append(f)
        col = 0
        for group, flist in groups.items():
            box = tk.Frame(inner, bg=COLOR_BG)
            box.grid(row=0 if col < 2 else 1, column=col % 2, sticky="nw", padx=15, pady=10)
            col += 1
            self._label(box, group, fg=COLOR_TITLE, font=FONT_TITLE).grid(
                row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
            for r, f in enumerate(flist, start=1):
                meta = f.metadata
                self._label(box, meta["label"], anchor="w").grid(row=r, column=0, sticky="w")
                value = getattr(settings, f.name)
                if meta["choices"]:
                    var = tk.StringVar(value=value)
                    widget = ttk.Combobox(box, textvariable=var, values=list(meta["choices"]),
                                          width=10, state="readonly")
                    widget.var = var
                else:
                    widget = self._entry(box, _show(value), width=8)
                    widget.config(justify=tk.CENTER)
                widget.grid(row=r, column=1, padx=8, pady=2)
                self._label(box, f"default {_show(getattr(defaults, f.name))}", fg="#808080",
                            font=FONT_SMALL).grid(row=r, column=2, sticky="w")
                self.setting_widgets[f.name] = widget

        opts = tk.Frame(inner, bg=COLOR_BG)
        opts.grid(row=2, column=0, columnspan=2, sticky="w", padx=15, pady=10)
        self.save_files_var = tk.BooleanVar(value=app_opts.get("save_files", True))
        self.show_packets_var = tk.BooleanVar(value=app_opts.get("show_packets", False))
        for text, var in ((f"Save daily files in {LOG_DIR} (camera messages for the log "
                           f"analysis, and every decision)", self.save_files_var),
                          ("Show every packet in the System Log (otherwise only changes)",
                           self.show_packets_var)):
            tk.Checkbutton(opts, text=text, variable=var, bg=COLOR_BG, fg=COLOR_FG,
                           selectcolor=COLOR_INPUT, activebackground=COLOR_BG,
                           activeforeground=COLOR_FG, font=FONT_UI).pack(anchor=tk.W)
        buttons = tk.Frame(opts, bg=COLOR_BG)
        buttons.pack(anchor=tk.W, pady=(10, 0))
        ModernButton(buttons, text="Apply and save", command=self.apply_settings,
                     bg=COLOR_SUCCESS).pack(side=tk.LEFT, padx=(0, 10))
        ModernButton(buttons, text="Back to defaults", command=self.reset_settings,
                     bg=COLOR_INPUT).pack(side=tk.LEFT)
        self.settings_msg = tk.StringVar()
        msg = self._label(opts, "", fg=COLOR_WARNING, justify=tk.LEFT, wraplength=900)
        msg.config(textvariable=self.settings_msg)
        msg.pack(anchor=tk.W, pady=(8, 0))

    # ------------------------------------------------------- settings
    def _load_settings(self):
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Settings(), {}
        settings = Settings.from_dict(data.get("settings", {}))
        if settings.problems():
            return Settings(), data.get("app", {})
        return settings, data.get("app", {})

    def _read_widgets(self):
        values, errors = {}, []
        for name, widget in self.setting_widgets.items():
            text = widget.var.get() if hasattr(widget, "var") else widget.get()
            try:
                values[name] = parse_setting(name, text)
            except ValueError:
                meta = next(f.metadata for f in fields(Settings) if f.name == name)
                errors.append(f"{meta['label']}: not a number")
        settings = Settings(**values) if not errors else None
        if settings is not None:
            errors += settings.problems()
        return settings, errors

    def apply_settings(self):
        settings, errors = self._read_widgets()
        if errors:
            self.settings_msg.set("⚠ " + "\n⚠ ".join(errors))
            return
        app_opts = {"save_files": self.save_files_var.get(),
                    "show_packets": self.show_packets_var.get()}
        self.files.enabled = app_opts["save_files"]
        self.controller.show_packets = app_opts["show_packets"]
        self.controller.inbox.put(("settings", settings))
        try:
            SETTINGS_FILE.write_text(json.dumps({"settings": settings.to_dict(), "app": app_opts},
                                                indent=2), encoding="utf-8")
            self.settings_msg.set(f"Saved to {SETTINGS_FILE.name} and in use now.")
        except OSError as exc:
            self.settings_msg.set(f"In use now, but could not be saved: {exc}")

    def reset_settings(self):
        defaults = Settings()
        for name, widget in self.setting_widgets.items():
            value = _show(getattr(defaults, name))
            if hasattr(widget, "var"):
                widget.var.set(value)
            else:
                widget.delete(0, tk.END)
                widget.insert(0, value)
        self.settings_msg.set("Defaults filled in; press Apply and save to use them.")

    def _on_fixed_toggled(self):
        self.controller.inbox.put(("fixed", self.fixed_var.get()))

    # ----------------------------------------------------------- view
    def _refresh_view(self):
        snap = self.controller.snapshot
        if snap is not None:
            self._show_lights(snap)
            self._show_cars(snap["cars"])
            self._show_cameras(snap["cameras"])
            mode = snap["mode"]
            if not snap["running"]:
                text, color = "Stopped" + (" -- warm flash red 88 / dark" if snap["connected"]
                                           else ""), COLOR_FG
            elif mode == "smart":
                text, color = "SMART CONTROL", COLOR_SUCCESS
            else:
                text = f"FIXED CYCLE (V22): {snap['fixed_reason'] or 'returning to smart control'}"
                color = COLOR_WARNING
            if not snap["connected"]:
                text += "   |   lights not connected"
            self.mode_var.set(text)
            self.mode_label.config(fg=color)
        server = self.server
        rate = sum(c["rate"] for c in snap["cameras"].values()) if snap else 0
        self.server_var.set((f"Camera server: port {HTTP_PORT}, {rate} messages in the last minute"
                             if server.ok else f"Camera server: NOT RUNNING (port {HTTP_PORT})")
                            + ("" if self.pinger.available else "   |   no ping"))
        self.after(250, self._refresh_view)

    def _show_lights(self, snap):
        lights = snap["lights"]
        notes = []
        mode = snap["mode"]
        if mode != "smart":
            notes = ["fixed cycle"] * 3
        else:
            nt, n = snap["north"]
            st, m = snap["south"]
            north = snap["holders"][N]
            south = snap["holders"][S]
            notes.append({"idle": "green: no northbound car",
                          "count": f"green countdown for {north}",
                          "allred": "red: 0x01 turns green next",
                          "go": f"red: northbound {north}",
                          "end": "red: last northbound car left",
                          "clear": "red: green next"}[nt])
            notes.append({"go": f"green for {north}", "end": "green countdown: car left"}
                         .get(nt, "red"))
            notes.append({"idle": "green: no southbound car",
                          "count": f"green countdown for {south}",
                          "hold": f"red: southbound {south}",
                          "clear": "red: last southbound car left"}[st])
            for i, d in ((0, N), (2, S)):
                held = snap["red_since"][d]
                if held is not None and held >= 1:
                    notes[i] += f"  ({held:.0f} s red)"
        self.lights_view.show(lights, notes, snap["running"] and snap["connected"])

    def _show_cars(self, cars):
        table = self.car_table
        want = {str(c["id"]): c for c in cars}
        for iid in table.get_children():
            if iid not in want:
                table.delete(iid)
        for iid, c in want.items():
            values = (c["id"], c["dir"], f"{c['score']:.0f}%", c["where"], c["state"],
                      f"{c['age']:.0f}", f"{c['quiet']:.0f}")
            tag = (S if c["dir"] == NAME[S] else N) if c["holding"] else "candidate"
            if table.exists(iid):
                table.item(iid, values=values, tags=(tag,))
            else:
                table.insert("", 0, iid=iid, values=values, tags=(tag,))

    def _show_cameras(self, cams):
        for cam, c in cams.items():
            ago = "-" if c["ago"] is None else (f"{c['ago']:.0f} s" if c["ago"] < 120
                                                else f"{c['ago'] / 60:.0f} min")
            self.cam_table.item(cam, values=(cam, CAMERAS[cam], c["status"], ago, c["rate"],
                                             c["detail"]), tags=(c["status"],))

    def _check_address(self):
        try:
            addresses = socket.gethostbyname_ex(socket.gethostname())[2]
        except OSError:
            return
        if sys.platform == "win32" and PC_ADDRESS not in addresses:
            self.log(f"This PC's addresses are {', '.join(addresses)}; the cameras send to "
                     f"{PC_ADDRESS}:{HTTP_PORT}", "WARN")

    # ------------------------------------------------------ connection
    def net_connect(self):
        if self.sock is not None:
            self.log("Already connected.", "WARN")
            return
        self._cancel_retry()
        ip = self.ip_entry.get().strip() or DEFAULT_IP
        try:
            port = int(self.port_entry.get().strip() or DEFAULT_PORT)
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid port", "Port must be 1-65535.")
            return
        self.btn_connect.config(state=tk.DISABLED)
        self.net_status_var.set("Connecting ...")
        self.net_status_label.config(fg=COLOR_WARNING)
        threading.Thread(target=self._connect_task, args=(ip, port), daemon=True).start()

    def _connect_task(self, ip, port):
        self.log(f"Connecting to {ip}:{port} ...")
        try:
            sock = socket.create_connection((ip, port), timeout=5)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            self.log(f"Connection to {ip}:{port} failed: {exc}", "ERROR")
            self.after_safe(self._set_connected, False, "Connection Failed")
            return
        self.sock = sock
        self.log(f"Connected to {ip}:{port}", "SUCCESS")
        self.after_safe(self._set_connected, True, "Connected")

    def _close_link(self):
        sock, self.sock = self.sock, None
        if sock is None:
            return
        try:
            with self.sock_lock:
                sock.close()
        except OSError:
            pass
        self.log("Disconnected from ETH-to-RS485")

    def net_disconnect(self):
        self._pause_auto_run()
        self.controller.running = False
        self._close_link()
        self._set_connected(False, "Disconnected")

    def _set_connected(self, connected, text):
        self.net_status_var.set(text)
        self.net_status_label.config(fg=COLOR_SUCCESS if connected else COLOR_ERROR)
        self.btn_connect.config(state=tk.DISABLED if connected else tk.NORMAL)
        self.btn_disconnect.config(state=tk.NORMAL if connected else tk.DISABLED)
        running = self.controller.running and connected
        self.btn_start.config(state=tk.DISABLED if running or not connected else tk.NORMAL)
        self.btn_stop.config(state=tk.NORMAL if running else tk.DISABLED)
        if self.keep_running:
            if connected:
                self.start_control()
            else:
                self._schedule_retry()

    def on_link_error(self, exc):
        if self.sock is None:
            return
        self.log(f"Connection lost while sending: {exc}", "ERROR")
        self._close_link()
        self._set_connected(False, "Connection Lost")

    # -------------------------------------------------------- auto run
    def _auto_connect(self):
        self._retry_job = None
        if self.keep_running and self.sock is None:
            self.net_connect()

    def _schedule_retry(self):
        if self._retry_job is None:
            self.log(f"Auto run: next connection attempt in {RETRY_SECONDS} s")
            self._retry_job = self.after(RETRY_SECONDS * 1000, self._auto_connect)
        self.btn_disconnect.config(state=tk.NORMAL)   # lets the operator cancel the retries

    def _cancel_retry(self):
        if self._retry_job is not None:
            self.after_cancel(self._retry_job)
            self._retry_job = None

    def _pause_auto_run(self):
        self._cancel_retry()
        if self.keep_running:
            self.keep_running = False
            self.log("Auto run paused by the operator; Start resumes it")

    # ----------------------------------------------------------- control
    def start_control(self):
        if self.sock is None:
            messagebox.showwarning("Not connected", "Connect the ETH-to-RS485 first.")
            return
        if not self.controller.running:
            self.controller.running = True
            self.log("Smart control started: a packet every second", "SUCCESS")
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.keep_running = AUTO_RUN

    def stop_control(self):
        if not self.controller.running:
            self.log("Smart control is not running.", "WARN")
            return
        self.controller.running = False
        self._pause_auto_run()
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.log("Smart control stopped; warm keep-alive (red 88 / dark)")

    # ----------------------------------------------------------- close
    def on_close(self):
        self.keep_running = False
        self._cancel_retry()
        self.controller.running = False
        self.controller.stop()
        self.server.stop()
        self.pinger.stop()
        self._close_link()
        self.files.close()
        sys.stdout, sys.stderr = self._stdout, self._stderr
        self.destroy()


def _show(value):
    """Setting value as typed on screen: 5, 2.5, red."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class LogRedirector:
    """File-like stdout/stderr replacement so stray prints and thread
    tracebacks land in the System Log instead of a hidden console."""

    def __init__(self, log_fn, level):
        self._log = log_fn
        self._level = level
        self._buffer = ""

    def write(self, text):
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._log(line.rstrip(), self._level)

    def flush(self):
        if self._buffer.strip():
            self._log(self._buffer.rstrip(), self._level)
        self._buffer = ""


def another_copy_running():
    """True if a program (this one or V22) already drives DEFAULT_IP in this
    Windows session.  Any failure here lets the program start, so an
    unattended boot is never blocked."""
    if sys.platform != "win32":
        return False
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, f"{INSTANCE_MUTEX}_{DEFAULT_IP}")
    return ctypes.get_last_error() == 183          # ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    os.chdir(HERE)
    if another_copy_running():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("LED Control System Ultimate",
                            f"A traffic-light controller for {DEFAULT_IP} is already running.")
        sys.exit()
    SmartApp().mainloop()
