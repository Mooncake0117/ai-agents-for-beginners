"""Traffic-light controller for the ShinKong parking lot -- UI version.

One file: the RS485 packet layer, the lighting cycle and a Tkinter
front-end.

Packet:  55 AA | quantity | (color number) x quantity | checksum
    quantity    3rd byte, number of addresses = QUANTITY below (max 32)
    color byte  address * 8 + code  (green=1, yellow=2, red=3, dark=4)
    number byte plain hexadecimal countdown value (15 -> 0x0F), not BCD
    checksum    XOR of the quantity byte and every payload byte
    length      2 * quantity + 4 bytes (4 addresses -> 12 bytes)
The lights LATCH the last packet and keep counting down by themselves.

Lighting cycle, five phases (defaults 2 + 11 + 2 + 2 + 11 = 28 s):

    phase        CLEARANCE  TRAFFIC  ADJUST   CLEARANCE  TRAFFIC
    0x00         red        red      red*     red        green
    0x01         red        green    green*   red        red
    0x02, 0x03   red        green    red*     red        red
    * default; the ADJUST colour of every row is picked red or green in the UI

Every light counts down the seconds left in its current colour, across
phase borders and around the end of the cycle.  With the defaults 0x00
shows red 17..1 then green 11..1, 0x01 red 15..1 then green 13..1, and
0x02 / 0x03 red 17..1 then green 11..1.

UI, "Network Control" tab:
    Target IP / Port -> Connect ETH-to-RS485 / Disconnect.  While
    connected and no sequence runs, the warm flash sends red 88 one
    second and dark the next (WARM_KEEPALIVE).
    Countdown Seconds Setting
        Traffic Light Seconds         -> TRAFFIC   (default DEFAULT_TRAFFIC)
        Red Light Seconds for safety  -> CLEARANCE (default CLEARANCE_SECONDS)
        Seconds for adjustment        -> ADJUST    (default ADJUST_SECONDS)
    Start sends one packet per second, beginning with the all-red
    CLEARANCE; Stop returns to the warm flash.  The three settings are
    locked while a sequence runs and take effect at the next Start.
    Cycle diagram: click a red / green dot (or the ADJUST bar) inside the
    yellow box to pick that row's ADJUST colour.  While a sequence runs
    the pick takes effect at the start of the next cycle, so no countdown
    on the street ever jumps.
UI, "System Log" tab: everything that used to go to the console (also
written to Logs/TrafficLight_<timestamp>.log).

Run:  python traffic_light_cli_V21_modified_for_ShinKong.py
      (pythonw.exe hides the console; all output is in the log tab)
"""

import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk

# ==========================================
# Core configuration
# ==========================================
QUANTITY = 4       # addresses on the bus (1-32), edit here if additional traffic lights have been installed

# Lighting cycle CLEARANCE -> TRAFFIC -> ADJUST -> CLEARANCE -> TRAFFIC.
# These are the defaults shown in the UI; Start uses the entered values.
CLEARANCE_SECONDS = 2   # every light red, for safety, before each traffic phase
DEFAULT_TRAFFIC = 11    # main red / green phase
ADJUST_SECONDS = 2      # extra phase, red or green per row as picked in the UI
MAX_COUNTDOWN = 99      # every displayed number must fit 2 digits

WARM_KEEPALIVE = True         # True: all lights flash red 88 / dark while no sequence is running

HEAD = bytes([0x55, 0xAA])
COLOR_CODES = {"green": 1, "yellow": 2, "red": 3, "dark": 4}

# ==========================================
# UI configuration
# ==========================================
DEFAULT_IP = "192.168.7.161"
DEFAULT_PORT = 1111

SETTINGS_WIDTH = 440                              # left column width in px
LOG_MAX_LINES = 3000          # on-screen log is trimmed; the log file keeps everything

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
COLOR_NOTE = "#fff200"                            # ADJUST box and its note
COLOR_LIGHT = {"red": "#ff3232", "green": "#1bff1b"}
FONT_UI = ("Microsoft JhengHei", 10)
FONT_SMALL = ("Microsoft JhengHei", 9)
FONT_TITLE = ("Microsoft JhengHei", 12)
FONT_MONO = ("Consolas", 10)


def console_log(msg, level="INFO"):
    """Fallback logger when no UI is attached."""
    print(f"[{level}] {msg}")


# ----------------------------------------------------------- packet layer

def build_packet(settings):
    """settings[addr] = (color, number) for every address 0..QUANTITY-1."""
    body = bytearray([len(settings)])
    for addr, (color, number) in enumerate(settings):
        body.append((addr << 3) | COLOR_CODES[color])
        body.append(number)
    checksum = 0
    for byte in body:
        checksum ^= byte
    return HEAD + bytes(body) + bytes([checksum])


WARM_PACKET = build_packet([("red", 88)] * QUANTITY)
DARK_PACKET = build_packet([("dark", 0)] * QUANTITY)


# ------------------------------------------------------------ cycle layer

PHASES = ("CLEARANCE", "TRAFFIC", "ADJUST", "CLEARANCE", "TRAFFIC")
ADJUST_PHASE = PHASES.index("ADJUST")


def opposite(color):
    return "green" if color == "red" else "red"


@dataclass(frozen=True)
class Timing:
    """Phase lengths in seconds, as entered in the UI."""
    traffic: int = DEFAULT_TRAFFIC
    clearance: int = CLEARANCE_SECONDS
    adjust: int = ADJUST_SECONDS

    def phase_seconds(self):
        """Seconds of every phase, in PHASES order."""
        return (self.clearance, self.traffic, self.adjust,
                self.clearance, self.traffic)

    @property
    def period(self):
        return sum(self.phase_seconds())


@dataclass(frozen=True)
class LightGroup:
    """Addresses that always show the same light -- one diagram row."""
    label: str
    addresses: tuple
    traffic: tuple          # colours of the first and the second TRAFFIC phase
    default_adjust: str


def light_groups(quantity):
    """0x00 crosses 0x01; every address from 0x02 on runs the 0x01 cycle
    with an ADJUST colour of its own (one shared row, "0x02-03")."""
    twins = tuple(range(2, quantity))
    twins_label = "0x02" if len(twins) == 1 else f"0x02-{quantity - 1:02X}"
    groups = [LightGroup("0x00", (0,), ("red", "green"), "red"),
              LightGroup("0x01", (1,), ("green", "red"), "green"),
              LightGroup(twins_label, twins, ("green", "red"), "red")]
    return [group for group in groups
            if group.addresses and group.addresses[-1] < quantity]


LIGHT_GROUPS = light_groups(QUANTITY)


def cycle_phases(group, timing, adjust_color):
    """[(seconds, color)] of the five PHASES of one row."""
    first, second = group.traffic
    colors = ("red", first, adjust_color, "red", second)
    return list(zip(timing.phase_seconds(), colors))


def countdown_cycle(phases):
    """Per-second (color, number) list over one cycle.  The number is the
    seconds left until the colour changes, so it runs on across phase
    borders and around the end of the cycle (the cycle repeats forever)."""
    colors = [color for seconds, color in phases for _ in range(seconds)]
    cycle = []
    for t, color in enumerate(colors):
        left = 1
        while left < len(colors) and colors[(t + left) % len(colors)] == color:
            left += 1
        cycle.append((color, left))
    return cycle


def build_program(timing, adjust_colors):
    """One settings list -- (color, number) per address -- for every second
    of the cycle.  adjust_colors holds the ADJUST colour of each
    LIGHT_GROUPS row."""
    per_address = [None] * QUANTITY
    for group, adjust_color in zip(LIGHT_GROUPS, adjust_colors):
        cycle = countdown_cycle(cycle_phases(group, timing, adjust_color))
        for addr in group.addresses:
            per_address[addr] = cycle
    return [[cycle[second] for cycle in per_address]
            for second in range(timing.period)]


def phase_at(timing, second):
    """Index into PHASES of the given second of the cycle."""
    for phase, seconds in enumerate(timing.phase_seconds()):
        if second < seconds:
            return phase
        second -= seconds
    return len(PHASES) - 1


def color_runs(phases):
    """Neighbouring phases of one colour merged into runs, around the end
    of the cycle too: [(color, [seconds, ...]), ...] starting with the
    longest red run."""
    runs = []
    for seconds, color in phases:
        if seconds == 0:
            continue
        if runs and runs[-1][0] == color:
            runs[-1][1].append(seconds)
        else:
            runs.append((color, [seconds]))
    if len(runs) > 1 and runs[0][0] == runs[-1][0]:
        color, tail = runs.pop()
        runs[0] = (color, tail + runs[0][1])
    reds = [i for i, (color, _) in enumerate(runs) if color == "red"]
    if reds:
        first = max(reds, key=lambda i: sum(runs[i][1]))
        runs = runs[first:] + runs[:first]
    return runs


def countdown_text(length):
    """17 -> "17, 16...2, 1"."""
    if length > 4:
        return f"{length}, {length - 1}...2, 1"
    return ", ".join(str(n) for n in range(length, 0, -1))


def describe_row(phases):
    """The two caption lines under one diagram row."""
    runs = color_runs(phases)
    red = runs[0][1]                  # every row has a red TRAFFIC phase
    formula = " + ".join(str(seconds) for seconds in red)
    if len(red) > 1:
        formula += f" = {sum(red)}"
    shows = ", then ".join(f"{color.title()} {countdown_text(sum(parts))}"
                           for color, parts in runs)
    return (f"→ Maximum consecutive Red Light Seconds = {formula} secs;",
            f"Light shows {shows}")


def green_conflicts(timing, adjust_colors):
    """Labels of the rows that show green at the same time as 0x00."""
    lead = cycle_phases(LIGHT_GROUPS[0], timing, adjust_colors[0])
    conflicts = []
    for group, adjust_color in zip(LIGHT_GROUPS[1:], adjust_colors[1:]):
        phases = cycle_phases(group, timing, adjust_color)
        if any(seconds and a == b == "green"
               for (seconds, a), (_, b) in zip(lead, phases)):
            conflicts.append(group.label)
    return conflicts


# --------------------------------------------------------- warm keep-alive

class WarmSender(threading.Thread):
    """All lights flash red 88 whenever resumed (no sequence running):
    alternates a red-88 packet and a dark packet, one per second.  The
    lights latch the last packet, so the dark half must be commanded."""

    def __init__(self, sock, lock):
        super().__init__(daemon=True)
        self._sock = sock
        self._lock = lock
        self._enabled = threading.Event()
        self._stopped = threading.Event()

    def run(self):
        show = False
        while not self._stopped.wait(1.0):
            show = not show
            with self._lock:
                if self._enabled.is_set():
                    try:
                        self._sock.sendall(WARM_PACKET if show else DARK_PACKET)
                    except OSError:
                        pass  # the sequence / UI reports connection errors

    def resume(self):
        self._enabled.set()

    def pause(self):
        # Taking the lock guarantees no warm packet can land inside a
        # running sequence after pause() returns.
        with self._lock:
            self._enabled.clear()

    def stop(self):
        self._stopped.set()


# ------------------------------------------------------- sequence sender

class SequenceRunner(threading.Thread):
    """Sends one packet per second on a drift-free schedule until stop().

    `program` holds one settings list per second of the cycle (see
    build_program).  A program handed to replace() takes over when the
    cycle starts again, so the countdowns already shown stay true.
    `position` = (second in cycle, settings) of the last packet sent; the
    UI polls it.
    """

    def __init__(self, sock, sock_lock, program, log, on_error):
        super().__init__(daemon=True)
        self._sock = sock
        self._sock_lock = sock_lock
        self._program = program
        self._next_program = None
        self._program_lock = threading.Lock()
        self._log = log
        self._on_error = on_error
        self._stop_event = threading.Event()
        self.position = None

    def replace(self, program):
        with self._program_lock:
            self._next_program = program

    @property
    def change_pending(self):
        with self._program_lock:
            return self._next_program is not None

    def run(self):
        program = self._program
        start = time.monotonic()
        tick = 0
        second = 0
        try:
            while not self._stop_event.is_set():
                if second == 0:
                    with self._program_lock:
                        if self._next_program is not None:
                            program, self._next_program = self._next_program, None
                            self._log("New adjustment colours take effect "
                                      "from this cycle", "CORE")
                settings = program[second]
                packet = build_packet(settings)
                with self._sock_lock:
                    self._sock.sendall(packet)
                self.position = (second, settings)
                shown = "  ".join(f"0x{a:02X}:{c[0].upper()}{n:2d}"
                                  for a, (c, n) in enumerate(settings))
                self._log(f"[{tick:6d}] {shown}  ->  "
                          f"{packet.hex(' ').upper()}", "TX")
                second = (second + 1) % len(program)
                tick += 1
                delay = start + tick - time.monotonic()
                if delay > 0:
                    self._stop_event.wait(delay)   # interruptible sleep
        except OSError as exc:
            self._on_error(exc)

    def stop(self):
        self._stop_event.set()


# ------------------------------------------------------------------- UI

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


class ModernButton(tk.Button):
    def __init__(self, master, **kwargs):
        bg_color = kwargs.pop("bg", COLOR_ACCENT)
        fg_color = kwargs.pop("fg", "white")
        super().__init__(master, **kwargs)
        self.configure(bg=bg_color, fg=fg_color, relief=tk.FLAT,
                       font=FONT_UI, activebackground=COLOR_ACCENT_HOVER,
                       activeforeground="white", disabledforeground="#888888",
                       cursor="hand2", padx=14, pady=6)


class TimingDiagram(tk.Canvas):
    """One cycle per LIGHT_GROUPS row as pill bars, CLEARANCE -> TRAFFIC ->
    ADJUST -> CLEARANCE -> TRAFFIC, with captions computed from the
    entered seconds.  The yellow box holds a red / green picker above each
    ADJUST bar; clicking a dot (or the bar itself) calls
    on_adjust(row, color).  The phase being sent gets a white rim."""

    BAR_H = 28
    GAP = 10
    SHORT_W = 72                       # CLEARANCE and ADJUST bars
    MIN_LONG_W = 120                   # TRAFFIC bars share the rest
    MARGIN_L, MARGIN_R = 68, 13
    ROW_TOP, ROW_STEP = 37, 76         # top of the first bar, row pitch
    GREY, DIM = "#b0b0b0", "#808080"

    def __init__(self, master, on_adjust, **kwargs):
        super().__init__(master, bg=COLOR_BG, highlightthickness=0, **kwargs)
        self._on_adjust = on_adjust
        self._timing = Timing()
        self._adjust = [group.default_adjust for group in LIGHT_GROUPS]
        self._active = None
        for row in range(len(LIGHT_GROUPS)):
            self.tag_bind(f"adjust{row}", "<Button-1>",
                          lambda _e, r=row: self._on_adjust(r, opposite(self._adjust[r])))
            for color in ("red", "green"):
                self.tag_bind(f"dot{row}{color}", "<Button-1>",
                              lambda _e, r=row, c=color: self._on_adjust(r, c))
        self.tag_bind("pick", "<Enter>", lambda _e: self.config(cursor="hand2"))
        self.tag_bind("pick", "<Leave>", lambda _e: self.config(cursor=""))
        self.bind("<Configure>", lambda _e: self.redraw())   # resize / first map

    def update_cycle(self, timing, adjust_colors):
        self._timing, self._adjust = timing, list(adjust_colors)
        self.redraw()

    def set_active_phase(self, phase):
        if phase != self._active:
            self._active = phase
            self.redraw()

    def _bar(self, x0, y0, x1, y1, color, tags=()):
        """Pill-shaped bar (two discs + a rectangle)."""
        r = (y1 - y0) / 2
        if x1 - x0 < 1:
            return
        if x1 - x0 <= 2 * r:
            self.create_oval(x0, y0, x1, y1, fill=color, outline=color, tags=tags)
            return
        self.create_oval(x0, y0, x0 + 2 * r, y1, fill=color, outline=color, tags=tags)
        self.create_oval(x1 - 2 * r, y0, x1, y1, fill=color, outline=color, tags=tags)
        self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=color, outline=color,
                              tags=tags)

    def redraw(self):
        self.delete("all")
        width = self.winfo_width()
        if width < 300:
            return                      # not laid out yet; <Configure> will call again
        long_w = max(self.MIN_LONG_W, (width - self.MARGIN_L - self.MARGIN_R
                                       - 3 * self.SHORT_W - 4 * self.GAP) / 2)
        spans, x = [], self.MARGIN_L
        for phase in PHASES:
            bar_w = long_w if phase == "TRAFFIC" else self.SHORT_W
            spans.append((x, x + bar_w))
            x += bar_w + self.GAP
        ax0, ax1 = spans[ADJUST_PHASE]
        axm = (ax0 + ax1) / 2

        for row, (group, adjust) in enumerate(zip(LIGHT_GROUPS, self._adjust)):
            y0 = self.ROW_TOP + row * self.ROW_STEP
            y1 = y0 + self.BAR_H
            ym = (y0 + y1) / 2
            self.create_text(self.MARGIN_L - 14, ym, anchor="e", text=group.label,
                             fill=self.GREY, font=FONT_SMALL)
            phases = cycle_phases(group, self._timing, adjust)
            for phase, ((seconds, color), (x0, x1)) in enumerate(zip(phases, spans)):
                tags = (f"adjust{row}", "pick") if phase == ADJUST_PHASE else ()
                if phase == self._active:
                    self._bar(x0 - 3, y0 - 3, x1 + 3, y1 + 3, "white")
                self._bar(x0, y0, x1, y1, COLOR_LIGHT[color], tags)
                self.create_text((x0 + x1) / 2, ym, text=f"{seconds} s",
                                 fill="black", font=FONT_SMALL, tags=tags)
            for dx, color in ((-12, "red"), (12, "green")):
                fill = COLOR_LIGHT[color]
                self.create_oval(axm + dx - 6, y0 - 17, axm + dx + 6, y0 - 5,
                                 fill=fill, outline=fill,
                                 tags=(f"dot{row}{color}", "pick"))
            maximum, shows = describe_row(phases)
            self.create_text(spans[0][0], y1 + 9, anchor="nw", text=maximum,
                             fill=self.DIM, font=FONT_UI,
                             width=ax0 - 8 - spans[0][0])
            shows_x = spans[3][0] + 28
            self.create_text(shows_x, y1 + 9, anchor="nw", text=shows,
                             fill=self.DIM, font=FONT_UI,
                             width=width - shows_x - self.MARGIN_R)

        # yellow box around the ADJUST bars and its note
        top = self.ROW_TOP - 25
        bottom = (self.ROW_TOP + (len(LIGHT_GROUPS) - 1) * self.ROW_STEP
                  + self.BAR_H + 15)
        self.create_rectangle(ax0 - 5, top, ax1 + 5, bottom, outline=COLOR_NOTE,
                              width=2)
        self.create_line(axm, bottom, axm, bottom + 6, fill=COLOR_NOTE, width=2)
        self.create_text(axm, bottom + 8, anchor="n", justify=tk.LEFT,
                         text="Can choose Red or\nGreen for adjustment",
                         fill=COLOR_NOTE, font=FONT_UI)

        conflicts = green_conflicts(self._timing, self._adjust)
        if conflicts:
            self.create_text(spans[0][0], bottom + 60, anchor="nw",
                             fill=COLOR_WARNING, font=FONT_UI,
                             text=f"⚠ 0x00 shows green together with "
                                  f"{', '.join(conflicts)} -- crossing traffic!")


class TrafficLightApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LED Control System Ultimate - Traffic Lights (ShinKong)")
        self.geometry("1600x850")
        self.configure(bg=COLOR_BG)
        self._setup_style()

        os.makedirs("Logs", exist_ok=True)
        self.log_file = (f"Logs/TrafficLight_"
                         f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self._log_queue = queue.Queue()

        self.sock = None
        self.sock_lock = threading.Lock()
        self.warmer = None
        self.runner = None
        self.timing = Timing()            # last valid settings; locked while running
        self.adjust_colors = [group.default_adjust for group in LIGHT_GROUPS]
        self._shown_position = None

        self.setup_ui()
        self._drain_log_queue()
        self._refresh_running_view()

        self._stdout, self._stderr = sys.stdout, sys.stderr
        sys.stdout = LogRedirector(self.log, "CORE")
        sys.stderr = LogRedirector(self.log, "ERROR")

        self.log(f"Started (QUANTITY={QUANTITY}, WARM_KEEPALIVE={WARM_KEEPALIVE})")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------ style
    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=COLOR_PANEL,
                        foreground="lightgray", padding=[15, 5], font=FONT_UI)
        style.map("TNotebook.Tab", background=[("selected", COLOR_ACCENT)],
                  foreground=[("selected", "white")])
        style.configure("TFrame", background=COLOR_BG)

    # -------------------------------------------------------------- log
    def log(self, msg, level="INFO"):
        """Thread-safe: callable from any thread."""
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log_queue.put((f"[{stamp}] [{level}] {msg}", level))

    def _drain_log_queue(self):
        lines = []
        try:
            while True:
                lines.append(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        if lines:
            for text, level in lines:
                self.log_display.insert(tk.END, text + "\n", level)
            total = int(self.log_display.index("end-1c").split(".")[0])
            if total > LOG_MAX_LINES:
                self.log_display.delete("1.0", f"{total - LOG_MAX_LINES}.0")
            self.log_display.see(tk.END)
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write("".join(text + "\n" for text, _ in lines))
            except OSError:
                pass
        self.after(100, self._drain_log_queue)

    # --------------------------------------------------------------- ui
    def setup_ui(self):
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.tab_net = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_net, text="🌐 Network Control")
        self.setup_network_tab(self.tab_net)
        self.tab_log = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_log, text="📜 System Log")
        self.setup_log_tab(self.tab_log)

    def _entry(self, parent, default, width=18):
        entry = tk.Entry(parent, bg=COLOR_INPUT, fg=COLOR_FG, font=FONT_MONO,
                         width=width, insertbackground=COLOR_FG,
                         disabledbackground=COLOR_PANEL,
                         disabledforeground="gray")
        entry.insert(0, str(default))
        return entry

    def setup_network_tab(self, parent):
        # 1-2. Target IP / Port rows, status, Connect / Disconnect
        net = tk.Frame(parent, bg=COLOR_BG)
        net.pack(fill=tk.X, padx=10, pady=(10, 5))
        net.columnconfigure(2, minsize=125)   # status text changes; buttons stay put

        ip_label = tk.Frame(net, bg=COLOR_BG)
        ip_label.grid(row=0, column=0, sticky="e", pady=4)
        tk.Label(ip_label, text="Target ", bg=COLOR_BG, fg=COLOR_FG,
                 font=FONT_UI).pack(side=tk.LEFT)
        tk.Label(ip_label, text="IP:", bg=COLOR_BG, fg=COLOR_ACCENT_HOVER,
                 font=FONT_UI).pack(side=tk.LEFT)
        self.ip_entry = self._entry(net, DEFAULT_IP)
        self.ip_entry.grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(net, text="Port:", bg=COLOR_BG, fg=COLOR_FG,
                 font=FONT_UI).grid(row=1, column=0, sticky="e", pady=4)
        self.port_entry = self._entry(net, DEFAULT_PORT)
        self.port_entry.grid(row=1, column=1, sticky="w", padx=5)

        self.net_status_var = tk.StringVar(value="Disconnected")
        self.net_status_label = tk.Label(
            net, textvariable=self.net_status_var, bg=COLOR_BG,
            fg=COLOR_ERROR, font=FONT_UI)
        self.net_status_label.grid(row=1, column=2, sticky="w", padx=10)

        btn_frame = tk.Frame(net, bg=COLOR_BG)
        btn_frame.grid(row=1, column=3, sticky="w", padx=(10, 0))
        self.btn_connect = ModernButton(btn_frame, text="Connect ETH-to-RS485",
                                        command=self.net_connect,
                                        bg=COLOR_SUCCESS)
        self.btn_connect.pack(side=tk.LEFT, padx=5)
        self.btn_disconnect = ModernButton(btn_frame, text="Disconnect",
                                           command=self.net_disconnect,
                                           bg=COLOR_ERROR, state=tk.DISABLED)
        self.btn_disconnect.pack(side=tk.LEFT, padx=5)

        # 3-4. Countdown Seconds Setting (left column) + cycle diagram
        body = tk.Frame(parent, bg=COLOR_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        left = tk.Frame(body, bg=COLOR_BG, width=SETTINGS_WIDTH)
        left.pack(side=tk.LEFT, fill=tk.Y, anchor=tk.N)
        left.pack_propagate(False)          # fixed-width settings column

        tk.Label(left, text="Countdown Seconds Setting", bg=COLOR_BG,
                 fg=COLOR_TITLE, font=FONT_TITLE).pack(anchor=tk.W, pady=(25, 5))
        self.traffic_entry = self._setting_row(
            left, "Traffic Light Seconds:", DEFAULT_TRAFFIC)
        self.clearance_entry = self._setting_row(
            left, "Red Light Seconds for safety :", CLEARANCE_SECONDS)
        self.adjust_entry = self._setting_row(
            left, "Seconds for adjustment :", ADJUST_SECONDS)
        self.settings_error_var = tk.StringVar()
        tk.Label(left, textvariable=self.settings_error_var, bg=COLOR_BG,
                 fg=COLOR_ERROR, font=FONT_UI, justify=tk.LEFT, anchor=tk.W,
                 wraplength=SETTINGS_WIDTH - 10).pack(anchor=tk.W, padx=5,
                                                      pady=(2, 0))

        run_frame = tk.Frame(left, bg=COLOR_BG)
        run_frame.pack(fill=tk.X, pady=(38, 5))
        self.btn_start = ModernButton(run_frame, text="Start",
                                      command=self.start_sequence,
                                      bg=COLOR_WARNING, state=tk.DISABLED)
        self.btn_start.pack(side=tk.LEFT, padx=(15, 10))
        self.btn_stop = ModernButton(run_frame, text="Stop",
                                     command=self.stop_sequence,
                                     bg=COLOR_WARNING, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=10)
        self.seq_status_var = tk.StringVar(value="Sequence: not connected")
        tk.Label(run_frame, textvariable=self.seq_status_var, bg=COLOR_BG,
                 fg=COLOR_FG, font=FONT_UI, justify=tk.LEFT, anchor=tk.W,
                 wraplength=SETTINGS_WIDTH - 200).pack(side=tk.LEFT, padx=10)

        right = tk.Frame(body, bg=COLOR_BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))
        self.diagram = TimingDiagram(right, self._on_adjust_picked, height=320)
        self.diagram.pack(fill=tk.X, anchor=tk.N, pady=(14, 0))

        for entry in (self.traffic_entry, self.clearance_entry, self.adjust_entry):
            entry.bind("<KeyRelease>", lambda _e: self._on_settings_changed())
        self._on_settings_changed()

    def _setting_row(self, parent, label, default):
        row = tk.Frame(parent, bg=COLOR_PANEL, highlightthickness=1,
                       highlightbackground="#646464")
        row.pack(fill=tk.X, padx=5, pady=4)
        tk.Label(row, text=label, bg=COLOR_PANEL, fg="white",
                 font=FONT_TITLE).pack(side=tk.LEFT, padx=(15, 5), pady=8)
        entry = self._entry(row, default, width=5)
        entry.config(justify=tk.CENTER)
        entry.pack(side=tk.LEFT, padx=5)
        return entry

    def setup_log_tab(self, parent):
        self.log_display = scrolledtext.ScrolledText(
            parent, bg="#000000", fg="white", font=("Consolas", 9))
        self.log_display.pack(fill=tk.BOTH, expand=True)
        for level, color in (("INFO", "white"), ("ERROR", "red"),
                             ("SUCCESS", COLOR_SUCCESS), ("WARN", "yellow"),
                             ("TX", "cyan"), ("CORE", "#ff80ff")):
            self.log_display.tag_config(level, foreground=color)

    # ------------------------------------------------------- settings
    def _read_settings(self):
        """Validated Timing from the entries; raises ValueError."""
        try:
            timing = Timing(traffic=int(self.traffic_entry.get().strip()),
                            clearance=int(self.clearance_entry.get().strip()),
                            adjust=int(self.adjust_entry.get().strip()))
        except ValueError:
            raise ValueError("Please enter whole numbers.")
        if timing.traffic < 1:
            raise ValueError("Traffic Light Seconds must be at least 1.")
        if timing.clearance < 0:
            raise ValueError("Red Light Seconds for safety cannot be negative.")
        if timing.adjust < 0:
            raise ValueError("Seconds for adjustment cannot be negative.")
        # the largest displayed countdown is the longest red run,
        # 2 x clearance + traffic + adjustment, and every number must fit 2 digits
        if 2 * timing.clearance + timing.traffic + timing.adjust > MAX_COUNTDOWN:
            raise ValueError(f"2 x Red-for-safety + Traffic + Adjustment must be "
                             f"<= {MAX_COUNTDOWN} (largest displayed countdown).")
        return timing

    def _on_settings_changed(self):
        if self.runner is not None:
            return                          # settings are locked while running
        try:
            self.timing = self._read_settings()
        except ValueError as exc:
            self.settings_error_var.set(f"⚠ {exc}")
            return
        self.settings_error_var.set("")
        self.diagram.update_cycle(self.timing, self.adjust_colors)

    def _set_settings_enabled(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        for entry in (self.traffic_entry, self.clearance_entry, self.adjust_entry):
            entry.config(state=state)

    def _on_adjust_picked(self, row, color):
        """Red / green dot (or ADJUST bar) clicked in the diagram."""
        if self.adjust_colors[row] == color:
            return
        self.adjust_colors[row] = color
        self.diagram.update_cycle(self.timing, self.adjust_colors)
        label = LIGHT_GROUPS[row].label
        if self.runner is not None:
            self.runner.replace(build_program(self.timing, self.adjust_colors))
            self.log(f"Adjustment colour of {label} set to {color}; takes effect "
                     f"at the start of the next cycle")
        else:
            self.log(f"Adjustment colour of {label} set to {color}")
        self._warn_conflicts()

    def _warn_conflicts(self):
        conflicts = green_conflicts(self.timing, self.adjust_colors)
        if conflicts:
            self.log(f"0x00 shows green together with {', '.join(conflicts)} "
                     f"during the adjustment phase", "WARN")

    # ------------------------------------------------------ connection
    def net_connect(self):
        if self.sock is not None:
            self.log("Already connected.", "WARN")
            return
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
        threading.Thread(target=self._connect_task, args=(ip, port),
                         daemon=True).start()

    def _connect_task(self, ip, port):
        self.log(f"Connecting to {ip}:{port} ...")
        try:
            sock = socket.create_connection((ip, port), timeout=5)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            self.log(f"Connection to {ip}:{port} failed: {exc}", "ERROR")
            self.after(0, self._set_connected, False, "Connection Failed")
            return
        self.sock = sock
        self.log(f"Connected to {ip}:{port}", "SUCCESS")
        if WARM_KEEPALIVE:
            self.warmer = WarmSender(self.sock, self.sock_lock)
            self.warmer.start()
            self.warmer.resume()
            self.log("Warm keep-alive running: all lights flash red 88 / dark")
        self.after(0, self._set_connected, True, "Connected")

    def _close_link(self):
        """Stop the warm flash and close the socket.  Safe to call when
        not connected."""
        if self.warmer is not None:
            self.warmer.stop()
            self.warmer = None
        if self.sock is None:
            return
        try:
            self.sock.close()
        except OSError:
            pass
        self.sock = None
        self.log("Disconnected from ETH-to-RS485")

    def net_disconnect(self):
        self._stop_runner()
        self._close_link()
        self._set_connected(False, "Disconnected")

    def _set_connected(self, connected, text):
        self.net_status_var.set(text)
        self.net_status_label.config(
            fg=COLOR_SUCCESS if connected else COLOR_ERROR)
        self.btn_connect.config(state=tk.DISABLED if connected else tk.NORMAL)
        self.btn_disconnect.config(state=tk.NORMAL if connected else tk.DISABLED)
        self.btn_start.config(state=tk.NORMAL if connected else tk.DISABLED)
        self.btn_stop.config(state=tk.DISABLED)
        self._set_settings_enabled(True)
        self.seq_status_var.set("Sequence: idle -- warm flash red 88 / dark"
                                if connected else "Sequence: not connected")

    # -------------------------------------------------------- sequence
    def start_sequence(self):
        if self.sock is None:
            messagebox.showwarning("Not connected",
                                   "Connect the ETH-to-RS485 first.")
            return
        if self.runner is not None and self.runner.is_alive():
            self.log("Sequence already running.", "WARN")
            return
        try:
            self.timing = self._read_settings()
        except ValueError as exc:
            messagebox.showerror("Invalid setting", str(exc))
            return
        program = build_program(self.timing, self.adjust_colors)
        self._set_settings_enabled(False)   # the cycle length must not change
        for group, adjust in zip(LIGHT_GROUPS, self.adjust_colors):
            phases = " -> ".join(f"{color.title()} {seconds}" for seconds, color
                                 in cycle_phases(group, self.timing, adjust))
            self.log(f"Address {group.label}: {phases} = {self.timing.period}s cycle")
        self._warn_conflicts()
        if self.warmer is not None:
            self.warmer.pause()             # hand the line to the sequence
        self.runner = SequenceRunner(
            self.sock, self.sock_lock, program, self.log,
            lambda exc: self.after(0, self._on_link_error, exc))
        self.runner.start()
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.seq_status_var.set("Sequence: RUNNING")
        self.log(f"Sequence started (packet length {2 * QUANTITY + 4} bytes, "
                 f"{QUANTITY} addresses)", "SUCCESS")

    def _refresh_running_view(self):
        """Mirror the packet being sent: white rim on the active phase and
        the current countdowns next to Start / Stop."""
        runner = self.runner
        position = runner.position if runner is not None else None
        if position != self._shown_position:
            self._shown_position = position
            if position is None:
                self.diagram.set_active_phase(None)
            else:
                second, settings = position
                self.diagram.set_active_phase(phase_at(self.timing, second))
                shown = "  ".join(
                    f"{group.label} {settings[group.addresses[0]][0][0].upper()}"
                    f"{settings[group.addresses[0]][1]}" for group in LIGHT_GROUPS)
                status = (f"Sequence: RUNNING  {second + 1}/{self.timing.period} s"
                          f"\n{shown}")
                if runner.change_pending:
                    status += "\nAdjustment: from next cycle"
                self.seq_status_var.set(status)
        self.after(200, self._refresh_running_view)

    def _stop_runner(self):
        if self.runner is None:
            return False
        self.runner.stop()
        self.runner.join(timeout=3)
        self.runner = None
        return True

    def stop_sequence(self):
        if not self._stop_runner():
            self.log("No sequence is running.", "WARN")
            return
        if self.warmer is not None:
            self.warmer.resume()            # back to the warm flash
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self._set_settings_enabled(True)
        self.seq_status_var.set("Sequence: idle -- warm flash red 88 / dark")
        self.log("Sequence stopped; warm keep-alive resumed")

    def _on_link_error(self, exc):
        self.log(f"Connection lost while sending: {exc}", "ERROR")
        self.runner = None
        self._close_link()
        self._set_connected(False, "Connection Lost")

    # ----------------------------------------------------------- close
    def on_close(self):
        self._stop_runner()
        self._close_link()
        sys.stdout, sys.stderr = self._stdout, self._stderr
        self.destroy()


if __name__ == "__main__":
    if not 1 <= QUANTITY <= 32:
        sys.exit("QUANTITY must be 1-32")
    TrafficLightApp().mainloop()
