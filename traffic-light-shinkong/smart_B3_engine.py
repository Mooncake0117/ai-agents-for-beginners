"""Smart traffic-light engine for ShinKong B3: camera messages in, light colours out.

No screen and no network: traffic_light_smart_B3.py receives the camera
messages over HTTP, hands them to Engine.message() and sends the colours that
Engine.tick() returns to the ETH-to-RS485 once a second, plus a packet at once
when a car starts or stops holding the lights and at the exact end of every
countdown (a countdown lasts exactly its seconds).  The same engine
replays a recorded log for testing, with no lights connected:

    python smart_B3_engine.py --replay B3_log_1024.txt > replay.txt
    python smart_B3_engine.py --replay B3_log_1024.txt --trace 09:13:00-09:14:00

Lights (B3 floor)
    0x00  HuoShih arterial            default green, no number
    0x01  lane exit to HuoShih        default red, no number
    0x02, 0x03  GuiLan main lanes     default green, no number
A plain colour is sent with number BLANK (0 shows no digits); a countdown shows
the seconds left.  The lights do not latch: a packet lasts about one second.

The lane as a row of spots, HuoShih end to GuiLan end
    spot 0  F Box-0                 HuoShih intersection         (outside)
    spot 1  A Box-1                 HuoShih mouth, turning area  (outside)
    spot 2  A Cross-Line-1 / -2     HuoShih entry line: CL1 moving in (south), CL2 out (north)
    spot 3  A Box-2 = B Box-0       one place, two cameras
    spot 4  B Box-1
    spot 5  B Cross-Line-1 / -2     CL1 south, CL2 north
    spot 6  B Box-2
    spot 7  C/D/E Box-2             GuiLan mouth
    spot 8  C/D Cross-Line-1 / -2   GuiLan entry line: CL1 out (south), CL2 in (north)
    spot 9  C/D/E Box-1             GuiLan intersection          (outside)
The HuoShih mouth (spots 1-3) is one car wide; from B Box-1 to the GuiLan end
(spots 4-8) the lane is two-way and cars going opposite ways pass each other.
A Box-0 (HuoShih arterial before 0x00) and C/D Box-0 (GuiLan arterial) only
choose the countdown length; F Box-1 (north branch) means a car at F Box-0
turned right.  Every message is timed by this PC when it arrives; anything the
camera writes into the message besides the zone name is ignored.

Every car is a vehicle event with a direction, a place (its front spot) and a
confidence score:
  * Each message goes to the car whose place it fits: the box that car is in,
    the next box (or the one after, if one was missed) in its direction, or the
    box just behind it that a long car still covers; never past another car
    that still sits in a box between them (cars cannot overtake).  A
    cross-line sends one message per car, so a line one car has crossed is
    crossed next by the car behind it.  C and D both report the GuiLan line:
    the second camera's report within 2 s belongs to the car that has just
    crossed (even if that car has already left), not to the car behind it.
    A box beyond the one in front of a car (one missed) goes to the car that
    has just left through there before it goes to the car behind.  Only a car
    going the same way, or any car in the HuoShih mouth, stands in the way;
    opposite cars pass each other in the two-way part.
  * Southbound: F Box-0 makes a candidate (10%).  A Box-1 after it makes it a
    southbound car (50%) and starts the 0x02/0x03 countdown at once, x1 = 3 s
    if C/D Box-0 saw a car in the last 2 s, else x2 = 2 s (setting south_start:
    or only at A Box-2 after A Box-1).  Without F Box-0 (a car that waited at
    the mouth, or F Box-0 missed), A Box-2 after A Box-1, A Cross-Line-1, B
    Cross-Line-1 or any later spot does the same.  A car seen only at the
    mouth (never past A Cross-Line-1 or at B Box-1) is dropped candidate_s
    after its last message: it nosed in.  0x02/0x03 turn green y s after the
    last southbound car has left.
  * Northbound: C/D/E Box-1 makes a candidate (5%).  C/D Cross-Line-2 (or B
    Cross-Line-2, or any spot from B Box-2 on) makes it a northbound car and
    starts the 0x00 countdown, z1 = 3 s if A Box-0 saw a car in the last 1 s,
    else z2 = 2 s; then 0x00 red, w s later 0x01 green.  When the last
    northbound car has left, 0x01 counts down u s, turns red, and 0x00 turns
    green v s later.
  * The end of a trip, the same both ways: the car has left once it has crossed
    its exit line (C/D Cross-Line-1 / A Cross-Line-2) and reached its last box
    (C/D/E Box-1 / A Box-1), in either order; if the box never comes, gone_s
    (3 s) after the line.  A northbound car at A Box-1 whose A Cross-Line-2 is
    missed has left once its boxes in the lane stay quiet for gone_s.  A
    southbound car at C/D/E Box-1 has not left before C/D Cross-Line-1: it may
    still wait at the mouth.
  * Standing still is not leaving: while a car's box keeps reporting (once a
    second), its score holds and the lights stay.  A car that goes silent keeps
    its score hold_s (5 s), then fades to cut_pct (15%) by fade_to_s (25 s) and
    ends.  A northbound car at B Box-1 or nearer HuoShih does not fade while
    0x01 is not green.  Candidates outside the lane drop after candidate_s.
  * A message for no car fits: an unexplained lane box waits a few seconds and
    joins the car a cross-line then reveals behind it.
  * Backing up is seen as a cross-line crossed against the car's direction, or
    its front box going quiet while a box behind it keeps reporting.  Inside the
    lane that only lowers the score; once the car is back outside its entry
    (A Box-1 / C/D/E Box-1) it stops holding the lights and is a candidate
    again, so the next forward message restarts its trip and countdown.
  * A cross-line for a direction that no car of that direction explains always
    starts a car of that direction: a missed car is the dangerous failure, a
    false one only costs a short red.
  * A car that makes no progress for max_red (60 s) stops holding the lights
    (a parked car or a box that keeps triggering) until it moves again.

Camera health: when a car's trip ends normally and no other car was in the
lane, every zone on its route that should have fired and did not counts a
miss; suspect_misses (3) in a row make the zone suspect, recover_hits (2) hits
in a row clear it.  Suspects are shown, not acted on, unless the southbound
entry cannot be seen at all (camera A and camera B both offline or suspect), the
HTTP server is down, or no camera has sent anything for silent_alarm_min (60)
outside the quiet hours (23:00-08:00; the silence counts from 08:00 at the
earliest, and once the alarm is on only a camera message ends it): then the
lights count down to all red and run the fixed V22 cycle until it is safe
again, returning to smart control after the all-red CLEARANCE_1.
"""

from __future__ import annotations

import argparse
import calendar
import math
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

# ----------------------------------------------------------- camera setup

CAMERAS = {"A": "192.168.7.164", "B": "192.168.7.165", "C": "192.168.7.162",
           "D": "192.168.7.167", "E": "192.168.7.163", "F": "192.168.7.166"}

S, N = "S", "N"                     # southbound (HuoShih -> GuiLan), northbound
SIGN = {S: 1, N: -1}                # spot numbers grow southbound
OUTSIDE = {S: 1, N: 9}              # S is outside the lane at spot <= 1, N at spot >= 9
EXIT_LINE = {S: 8, N: 2}            # crossing it in the car's direction = out of the lane
EXIT_LINE_NAME = {S: "C/D Cross-Line-1", N: "A Cross-Line-2"}
OUTER_BOX = {S: 9, N: 1}            # the car's last box, just outside the lane
OUTER_BOX_NAME = {S: "C/D/E Box-1", N: "A Box-1"}
END_NAME = {S: "GuiLan", N: "HuoShih"}
TWO_WAY = range(4, 9)               # B Box-1 .. C/D lines: wide, opposite cars pass each other;
                                    # the HuoShih mouth (A Box-1 .. A Box-2/B Box-0) is one car wide
NAME = {S: "southbound", N: "northbound"}

SPOT = {
    ("F", "B0"): 0,
    ("A", "B1"): 1,
    ("A", "CL1"): 2, ("A", "CL2"): 2,
    ("A", "B2"): 3, ("B", "B0"): 3,
    ("B", "B1"): 4,
    ("B", "CL1"): 5, ("B", "CL2"): 5,
    ("B", "B2"): 6,
    ("C", "B2"): 7, ("D", "B2"): 7, ("E", "B2"): 7,
    ("C", "CL1"): 8, ("D", "CL1"): 8, ("C", "CL2"): 8, ("D", "CL2"): 8,
    ("C", "B1"): 9, ("D", "B1"): 9, ("E", "B1"): 9,
}
SPOT_NAMES = ["F Box-0", "A Box-1", "A lines", "A Box-2/B Box-0", "B Box-1", "B lines",
              "B Box-2", "C/D/E Box-2", "C/D lines", "C/D/E Box-1"]
BOX_SPOTS = (0, 1, 3, 4, 6, 7, 9)   # boxes in lane order; lines sit between neighbours
BOX_INDEX = {spot: i for i, spot in enumerate(BOX_SPOTS)}
LINE_MOVES = {"CL1": S, "CL2": N}   # the direction a car crosses each line (cameras A-D)
MULTI_CAMERA_LINES = {8}            # C and D both report the GuiLan line for one car
HUOSHIH_ARTERIAL = {("A", "B0")}    # selects z1 / z2
GUILAN_ARTERIAL = {("C", "B0"), ("D", "B0")}   # selects x1 / x2
NORTH_BRANCH = {("F", "B1")}        # a car at F Box-0 turned right, not into the lane
OTHER_ZONES = {("E", "B0")}         # kept for the record only

# zones every clean trip should fire (camera health); a set = any one of them
HEALTH_ROUTE = {
    S: [("A", "B1"), ("A", "CL1"), ("A", "B2"), ("B", "B0"), ("B", "B1"), ("B", "CL1"),
        ("B", "B2"), frozenset({("C", "B2"), ("D", "B2"), ("E", "B2")}),
        ("C", "CL1"), ("D", "CL1")],
    N: [("C", "CL2"), ("D", "CL2"), frozenset({("C", "B2"), ("D", "B2"), ("E", "B2")}),
        ("B", "B2"), ("B", "CL2"), ("B", "B1"), ("B", "B0"), ("A", "B2"), ("A", "CL2"),
        ("A", "B1")],
}
SOUTH_ENTRY = {"A": [("A", "B1"), ("A", "CL1"), ("A", "B2")],
               "B": [("B", "B0"), ("B", "B1"), ("B", "CL1")]}

LINGER_S = 5.0          # a finished car still takes repeats of its own boxes this long
RETREAT_S = 3.0         # front box quiet this long while a box behind keeps reporting = moved back
MULTI_CAMERA_S = 2.0    # C and D report one GuiLan crossing within this
ORPHAN_S = 6.0          # a car first seen on a line adopts unexplained boxes this recent
COLORS = ("green", "red")
SOUTH_STARTS = ("A Box-1", "A Box-2")


def zone_name(zone):
    """'B1' -> 'Box-1', 'CL2' -> 'Cross-Line-2'."""
    if zone.startswith("CL"):
        return "Cross-Line" + (f"-{zone[2:]}" if zone[2:] else "")
    if zone.startswith("B"):
        return f"Box-{zone[1:]}"
    return zone


def label(key):
    return f"{key[0]} {zone_name(key[1])}"


def zone_of_text(text):
    """Zone named in a camera message: 'Box-1_triggered.' -> 'B1',
    'Cross-Line-2_triggered.' -> 'CL2', 'Cross-Line_triggered.' -> 'CL'.
    Anything else in the text (a camera time stamp, ...) is ignored."""
    m = re.search(r"Box-(\d+)", text)
    if m:
        return "B" + m.group(1)
    m = re.search(r"Cross-Line-?(\d*)", text)
    if m:
        return "CL" + m.group(1)
    return None


# ---------------------------------------------------------------- settings

def _f(default, label_, group, lo=0, hi=99, choices=None):
    return field(default=default, metadata={"label": label_, "group": group, "min": lo,
                                            "max": hi, "choices": choices})


@dataclass
class Settings:
    """Every value the operator can change on screen."""
    x1: int = _f(3, "0x02/0x03 countdown, car on GuiLan arterial (x1)", "Lights", 0, 30)
    x2: int = _f(2, "0x02/0x03 countdown, GuiLan arterial empty (x2)", "Lights", 0, 30)
    x_window: float = _f(2.0, "GuiLan arterial counts if C/D Box-0 seen within (s)", "Lights", 0, 10)
    y: int = _f(3, "0x02/0x03 red after the last southbound car left (y)", "Lights", 0, 30)
    z1: int = _f(3, "0x00 countdown, car on HuoShih arterial (z1)", "Lights", 0, 30)
    z2: int = _f(2, "0x00 countdown, HuoShih arterial empty (z2)", "Lights", 0, 30)
    z_window: float = _f(1.0, "HuoShih arterial counts if A Box-0 seen within (s)", "Lights", 0, 10)
    w: int = _f(2, "0x00 red -> 0x01 green (w)", "Lights", 0, 30)
    u: int = _f(2, "0x01 green countdown after the last northbound car left (u)", "Lights", 0, 30)
    v: int = _f(0, "0x01 red -> 0x00 green (v)", "Lights", 0, 30)
    south_start: str = _f("A Box-1", "Southbound countdown starts at A Box-1 (after F Box-0) or A Box-2",
                          "Lights", choices=("A Box-1", "A Box-2"))
    max_red: int = _f(60, "A car that does not move holds the lights at most (s)", "Lights", 10, 600)
    blank_number: int = _f(0, "Number byte for a plain colour (0 = no digits)", "Lights", 0, 255)

    candidate_s: float = _f(3.0, "Car seen only outside the lane or at the mouth: dropped after silence (s)",
                            "Confidence", 1, 30)
    gone_s: float = _f(3.0, "Exit line crossed but no C/D/E Box-1 / A Box-1 follows: car ends after (s)",
                       "Confidence", 0, 30)
    hold_s: float = _f(5.0, "Silent car in the lane keeps its score for (s)", "Confidence", 0, 60)
    fade_to_s: float = _f(25.0, "... and fades to the cut-off by (s)", "Confidence", 1, 300)
    cut_pct: float = _f(15.0, "Cut-off: a car below this no longer counts (%)", "Confidence", 0, 100)
    occupied_s: float = _f(2.5, "A box counts as occupied after its last message for (s)", "Confidence", 1, 10)
    score_candidate_s: float = _f(10.0, "Southbound candidate at F Box-0 (%)", "Confidence", 0, 100)
    score_candidate_n: float = _f(5.0, "Northbound candidate at C/D/E Box-1 (%)", "Confidence", 0, 100)
    score_active: float = _f(50.0, "Car confirmed in the lane, countdown starts (%)", "Confidence", 0, 200)
    score_box: float = _f(10.0, "Each new box along the route (+%)", "Confidence", 0, 100)
    score_line: float = _f(20.0, "Each cross-line along the route (+%)", "Confidence", 0, 100)
    score_back: float = _f(30.0, "Moving backwards (-%)", "Confidence", 0, 100)

    suspect_misses: int = _f(3, "Zone suspect after misses in a row", "Cameras", 1, 20)
    recover_hits: int = _f(2, "Suspect zone clears after hits in a row", "Cameras", 1, 20)
    silent_alarm_min: int = _f(60, "Fixed cycle if no camera sends anything for (min, daytime)", "Cameras", 1, 240)
    quiet_from: int = _f(23, "Quiet hours from (hour, no silence alarm)", "Cameras", 0, 23)
    quiet_to: int = _f(8, "Quiet hours to (hour)", "Cameras", 0, 23)

    clearance_1: int = _f(8, "Fixed cycle: CLEARANCE_1, all red (s)", "Fixed cycle (V22)", 1, 60)
    traffic: int = _f(15, "Fixed cycle: TRAFFIC (s)", "Fixed cycle (V22)", 1, 90)
    adjust: int = _f(5, "Fixed cycle: ADJUST (s)", "Fixed cycle (V22)", 0, 60)
    clearance_2: int = _f(3, "Fixed cycle: CLEARANCE_2, all red (s)", "Fixed cycle (V22)", 0, 60)
    adjust_00: str = _f("red", "Fixed cycle: 0x00 colour in ADJUST", "Fixed cycle (V22)", choices=COLORS)
    adjust_01: str = _f("green", "Fixed cycle: 0x01 colour in ADJUST", "Fixed cycle (V22)", choices=COLORS)
    adjust_23: str = _f("red", "Fixed cycle: 0x02/0x03 colour in ADJUST", "Fixed cycle (V22)", choices=COLORS)

    @classmethod
    def from_dict(cls, data):
        """Settings from saved values; unknown or invalid entries keep their default."""
        s = cls()
        for f in fields(cls):
            if f.name in data:
                try:
                    setattr(s, f.name, _convert(f, data[f.name]))
                except ValueError:
                    pass
        return s

    def problems(self):
        """Human-readable reasons these values cannot be used; empty = valid."""
        out = []
        for f in fields(self):
            meta, value = f.metadata, getattr(self, f.name)
            if meta["choices"]:
                if value not in meta["choices"]:
                    out.append(f"{meta['label']}: choose {' or '.join(meta['choices'])}")
            elif not meta["min"] <= value <= meta["max"]:
                out.append(f"{meta['label']}: must be {meta['min']}-{meta['max']}")
        if self.fade_to_s <= self.hold_s:
            out.append("The fade must end after the hold time")
        cycle = self.clearance_1 + self.traffic + self.adjust + self.clearance_2
        if cycle > 99:
            out.append("Fixed cycle: CLEARANCE_1 + TRAFFIC + ADJUST + CLEARANCE_2 must be <= 99")
        return out

    def to_dict(self):
        return asdict(self)


def _convert(f, raw):
    """One setting from text or JSON, as the field's type; raises ValueError."""
    if f.metadata["choices"]:
        for choice in f.metadata["choices"]:
            if str(raw).strip().lower() == choice.lower():
                return choice
        raise ValueError(raw)
    if f.type in ("int", int):
        return int(str(raw).strip())
    return float(str(raw).strip())


def parse_setting(name, text):
    """Typed value for one setting typed on screen; raises ValueError."""
    for f in fields(Settings):
        if f.name == name:
            return _convert(f, text)
    raise ValueError(name)


# ------------------------------------------------------------------ vehicles

@dataclass(eq=False)
class Vehicle:
    vid: int
    direction: str
    born: float
    front: int                 # furthest spot the car is believed to have reached
    base: float                # score when it was last seen; the shown score fades from it
    seen: float                # last message given to this car
    progress: float            # last step forward
    zones: dict = field(default_factory=dict)     # box -> time of its last message
    crossed: dict = field(default_factory=dict)   # line spot -> (time, camera)
    crossed_back: dict = field(default_factory=dict)   # line spot -> (time, camera), backwards
    visited: set = field(default_factory=set)     # every zone given to this car
    state: str = "candidate"   # candidate | active | leaving | ended | cancelled
    score: float = 0.0
    active_since: float | None = None
    exit_time: float | None = None   # crossed its exit line (C/D Cross-Line-1 / A Cross-Line-2)
    outer_time: float | None = None  # reached its last box (C/D/E Box-1 / A Box-1)
    end_time: float | None = None
    end_reason: str = ""
    entered: bool = False      # has held the lights at some time
    inside: bool = False       # seen past the entry line (not only at the mouth)
    backing: bool = False
    parked: bool = False
    unseen: bool = False       # only seen when it left the lane
    first: dict = field(default_factory=dict)     # spot -> first time the car reached it
    path: list = field(default_factory=list)      # [(time, zone label)]

    @property
    def live(self):
        return self.state in ("candidate", "active", "leaving")

    @property
    def in_lane(self):
        """Holds (or is about to hold) the lights: confirmed and not backed out."""
        return self.state in ("active", "leaving")

    @property
    def holding(self):
        """Does this car hold the lights now?"""
        return self.state in ("active", "leaving") and not self.parked

    @property
    def where(self):
        return SPOT_NAMES[self.front]


class Tracker:
    """Gives every message to a car and moves the cars along the lane."""

    def __init__(self, engine):
        self.e = engine
        self.vehicles = []
        self.next_id = 1
        self.last = {}                  # zone -> time of its last message
        self.active_spans = []          # (start, end) of every car that held the lights
        self.done = []                  # finished cars that were in the lane (newest last)
        self.orphans = []               # (time, zone) of lane boxes no car explained
        self.keep_done = 2000

    @property
    def s(self):
        return self.e.settings

    # ---------------------------------------------------------- messages
    def message(self, t, key):
        self.last[key] = t
        if key in HUOSHIH_ARTERIAL or key in GUILAN_ARTERIAL or key in OTHER_ZONES:
            return
        if key in NORTH_BRANCH:
            for v in self.vehicles:
                if v.state == "candidate" and v.direction == S and v.front == 0:
                    self.finish(v, t, "cancelled", "turned right at HuoShih")
            return
        spot = SPOT.get(key)
        if spot is None:
            self.e.unknown_zone(key)
            return
        move = LINE_MOVES.get(key[1]) if key[1].startswith("CL") else None
        if move:
            self._line(t, key, spot, move)
        else:
            self._box(t, key, spot)

    def _ahead(self, v, spot):
        """Spots from the car's front to spot, positive in its direction."""
        return (spot - v.front) * SIGN[v.direction]

    @staticmethod
    def _box_here(v):
        """Index (in BOX_SPOTS) of the last box the car's front has reached."""
        if v.direction == S:
            return max(i for i, sp in enumerate(BOX_SPOTS) if sp <= v.front)
        return min(i for i, sp in enumerate(BOX_SPOTS) if sp >= v.front)

    def _box_steps(self, v, spot):
        """Boxes from the car's place to the box at spot, positive in its direction."""
        return (BOX_INDEX[spot] - self._box_here(v)) * SIGN[v.direction]

    def _occupied(self, v, t):
        return any(t - last <= self.s.occupied_s for last in v.zones.values())

    def _blocked(self, v, spot, t):
        """Another car still sitting in a box between v and spot: a car going the
        same way (no overtaking), or any car in the one-car-wide HuoShih mouth.
        Cars going opposite ways pass each other from B Box-1 to the GuiLan end."""
        lo, hi = sorted((v.front, spot))
        return any(u is not v and u.live and lo < u.front < hi and self._occupied(u, t)
                   and (u.direction == v.direction or u.front not in TWO_WAY)
                   for u in self.vehicles)

    def _box(self, t, key, spot):
        best, best_rank, linger = None, None, None
        for v in self.vehicles:
            if spot == 0 and v.direction == N:
                continue                                # F Box-0 is past a northbound car's exit
            last = v.zones.get(key)
            if last is not None and t - last <= self.s.occupied_s:
                rank = (0, -last)                       # the box this car is in
            elif not v.live:
                if (v.state == "ended" and t - v.end_time <= LINGER_S
                        and (spot >= 7 if v.direction == S else spot <= 2)):
                    rank = (3, v.vid)                   # just left: its last boxes at the exit
                else:
                    continue
            else:
                b = self._box_steps(v, spot)
                reach = 2 if v.inside and v.in_lane else 1   # in the lane: one missed box allowed
                if 0 <= b <= reach and not self._blocked(v, spot, t):
                    rank = (1, not v.in_lane, b, -v.seen)    # ahead; cars in the lane first
                elif b == -1 and v.in_lane:
                    rank = (2, -v.seen)                 # the box just behind, car straddles both
                else:
                    continue
            if rank[0] == 3 and (linger is None or rank < linger[1]):
                linger = (v, rank)
            if best_rank is None or rank < best_rank:
                best, best_rank = v, rank
        if linger and best_rank[0] == 1 and best_rank[2] == 2:
            best = linger[0]                            # not a jump over a box: the car that just left
        if best is not None:
            self._attach(best, t, key, spot, None)
            return
        if spot == 0:
            self._new(t, key, S, 0, self.s.score_candidate_s)
        elif spot == 1:
            self._new(t, key, S, 1, self.s.score_candidate_s + self.s.score_box)
        elif spot == 9:
            self._new(t, key, N, 9, self.s.score_candidate_n)
        else:
            self.orphans = [o for o in self.orphans if t - o[0] <= ORPHAN_S] + [(t, key)]
            self.e.trace(f"{label(key)}: no car fits yet")

    def _line(self, t, key, spot, move):
        cam = key[0]
        best, best_rank = None, None
        for v in self.vehicles:
            if v.direction != move:
                continue
            prev = v.crossed.get(spot)
            # the other GuiLan camera reporting the crossing of a car that just went
            # over (and may have ended on it): that car, before any car behind it
            same_crossing = (prev is not None and spot in MULTI_CAMERA_LINES
                             and prev[1] != cam and key not in v.visited
                             and t - prev[0] <= MULTI_CAMERA_S)
            if not v.live and not (same_crossing and v.state == "ended"
                                   and t - v.end_time <= LINGER_S):
                continue
            if prev is not None:
                if not same_crossing:
                    continue                            # crossed already: the next car
                rank = (0, v.vid)
            else:
                a = self._ahead(v, spot)
                if not -2 <= a <= (3 if v.in_lane else 2) or self._blocked(v, spot, t):
                    continue
                rank = (1, abs(a), -v.front * SIGN[move])   # nearest; the car further on first
            if best_rank is None or rank < best_rank:
                best, best_rank = v, rank
        if best is None and spot == EXIT_LINE[move]:
            for v in self.vehicles:                     # the car that just left, crossing last
                prev = v.crossed.get(spot)
                if (v.state == "ended" and v.direction == move and t - v.end_time <= LINGER_S
                        and (prev is None or (prev[1] != cam and t - prev[0] <= MULTI_CAMERA_S))):
                    best = v
        if best is not None:
            self._attach(best, t, key, spot, move)
            return
        for v in self.vehicles:                         # C and D both report one crossing
            prev = v.crossed_back.get(spot)
            if (prev and spot in MULTI_CAMERA_LINES and prev[1] != cam
                    and t - prev[0] <= MULTI_CAMERA_S):
                v.visited.add(key)
                v.path.append((t, label(key) + " (backwards)"))
                return
        # against a car's direction: that car moved back over the line
        reverse = None
        for v in self.vehicles:
            if v.in_lane and v.direction != move:
                past = (v.front - spot) * SIGN[v.direction]
                if 0 <= past <= 1 and (reverse is None or v.vid < reverse.vid):
                    reverse = v
        if reverse is not None:
            self._backwards(reverse, t, key, spot)
        entry = (move == S and spot in (2, 5)) or (move == N and spot in (8, 5))
        if entry:
            v = self._new(t, key, move, spot, 0.0)
            self._adopt(v, t, spot)
            self._attach(v, t, key, spot, move, created=True)
        elif move == S and spot == 8 and reverse is None:
            v = self._new(t, key, S, 8, 0.0)
            v.unseen = True
            self._adopt(v, t, spot)
            self._attach(v, t, key, spot, move, created=True)
        elif reverse is None:
            self.e.trace(f"{label(key)}: no car fits, ignored")

    def _new(self, t, key, direction, spot, score):
        v = Vehicle(self.next_id, direction, t, spot, score, t, t)
        self.next_id += 1
        v.zones = {key: t} if not key[1].startswith("CL") else {}
        v.visited.add(key)
        v.path.append((t, label(key)))
        self.vehicles.append(v)
        self.e.trace(f"{label(key)}: new {NAME[direction]} candidate #{v.vid}")
        return v

    def _adopt(self, v, t, spot):
        """A car first seen on a line: the boxes just behind it (or the next one,
        reported in the same moment) that no car explained were this car."""
        sign = SIGN[v.direction]
        keep = []
        for o in self.orphans:
            behind = (spot - SPOT[o[1]]) * sign
            if (t - o[0] <= ORPHAN_S and 0 < behind <= 3) or (behind == -1 and t - o[0] <= 2):
                v.visited.add(o[1])
                v.path.insert(len(v.path) - 1, (o[0], label(o[1])))
                if t - o[0] <= self.s.occupied_s:
                    v.zones[o[1]] = o[0]
            else:
                keep.append(o)
        self.orphans = keep

    def _attach(self, v, t, key, spot, move, created=False):
        """Give one message to car v and move it on."""
        s = self.s
        v.seen = t
        if move is None:
            v.zones[key] = t
        if not created:
            if key not in v.visited or (v.path and v.path[-1][1] != label(key)):
                v.path.append((t, label(key)))
            v.visited.add(key)
        if move == v.direction:
            v.crossed.setdefault(spot, (t, key[0]))
        if not v.live:
            return                                      # a finished car's last messages
        a = self._ahead(v, spot)
        new_line = move == v.direction and v.crossed[spot][0] == t
        if a > 0:
            v.front = spot
            if move is None:                            # keep the boxes it may still cover
                here = self._box_here(v)
                v.zones = {k: last for k, last in v.zones.items()
                           if k[1].startswith("CL") or
                           (BOX_INDEX[SPOT[k]] - here) * SIGN[v.direction] >= -1}
        if a > 0 or new_line:
            v.first.setdefault(spot, t)
            v.progress = t
            v.base += s.score_line if move else s.score_box
            if v.parked:
                v.parked = False
                self.e.event(f"{self._name(v)} moves again at {label(key)}", "EVENT")
        if move == v.direction and spot in (2, 5, 8):
            v.inside = True                             # crossed a line in its direction
        elif v.front >= 4 if v.direction == S else v.front <= 6:
            v.inside = True                             # reached a box past the entry line
        self.e.trace(f"{label(key)} -> #{v.vid} ({v.state}, now at {v.where})")
        if v.state == "candidate" and self._confirms(v, key, spot, move):
            self._activate(v, t, key)
        if v.state not in ("active", "leaving"):
            return
        d = v.direction
        if move == d and spot == EXIT_LINE[d]:
            if v.exit_time is None:
                v.exit_time = t
        elif move is None and spot == OUTER_BOX[d]:
            if v.outer_time is None:
                v.outer_time = t
        else:
            return
        if v.exit_time is not None and v.outer_time is not None:
            self.finish(v, t, "ended", f"left at {END_NAME[d]} ({EXIT_LINE_NAME[d]} and "
                                       f"{OUTER_BOX_NAME[d]})")
        elif v.state == "active" and (v.exit_time is not None or d == N):
            # a southbound car at C/D/E Box-1 has not left until it crosses C/D
            # Cross-Line-1: it may still wait at the mouth
            v.state = "leaving"
            self.e.event(f"{self._name(v)} leaving the lane at {END_NAME[d]} ({label(key)})", "EVENT")

    def _confirms(self, v, key, spot, move):
        if v.direction == S:
            if self.s.south_start == "A Box-1" and key == ("A", "B1") and ("F", "B0") in v.visited:
                return True                             # turning in from the HuoShih arterial
            return (move == S and spot in (2, 5, 8)) or v.front >= 4 or (
                move is None and spot == 3 and ("A", "B1") in v.visited)
        return (move == N and spot in (8, 5)) or v.front <= 6

    def _activate(self, v, t, key):
        v.state, v.entered, v.backing = "active", True, False
        v.active_since = v.active_since or t
        v.base = max(v.base, self.s.score_active)
        if v.unseen:
            self.e.event(f"{self._name(v)} leaving at GuiLan, but no camera saw it enter "
                         f"the lane", "WARN")
        else:
            self.e.event(f"{self._name(v)} in the lane ({label(key)}, "
                         f"{v.base:.0f}%)", "EVENT")

    def _backwards(self, v, t, key, spot):
        """Line crossed against v's direction: v moved back over it."""
        v.backing = True
        v.seen = t
        v.crossed_back[spot] = (t, key[0])
        v.visited.add(key)
        v.path.append((t, label(key) + " (backwards)"))
        v.front = spot - SIGN[v.direction]
        v.crossed = {k: c for k, c in v.crossed.items() if (k - spot) * SIGN[v.direction] < 0}
        self._moved_back(v, t, f"crossed {label(key)} backwards")

    def _moved_back(self, v, t, why):
        if (v.front - OUTSIDE[v.direction]) * SIGN[v.direction] <= 0:
            v.state, v.backing, v.parked, v.inside = "candidate", False, False, False
            v.base = min(v.base, self.s.score_active - self.s.score_box)
            v.zones = {k: last for k, last in v.zones.items()
                       if (SPOT[k] - OUTSIDE[v.direction]) * SIGN[v.direction] <= 0}
            self.e.event(f"{self._name(v)} backed out of the lane ({why}); it no "
                         f"longer holds the lights", "EVENT")
        else:
            v.base = max(self.s.cut_pct + 1, v.base - self.s.score_back)
            self.e.event(f"{self._name(v)} moving backwards ({why}), now at {v.where}", "EVENT")

    # -------------------------------------------------------------- time
    def update(self, t, north_go):
        s = self.s
        for v in list(self.vehicles):
            if not v.live:
                if t - v.end_time > LINGER_S:
                    self.vehicles.remove(v)
                    if v.entered:
                        self.e.health.trip_done(v, self._clean(v))
                continue
            v.zones = {k: last for k, last in v.zones.items() if t - last <= 60}
            if v.in_lane:
                self._retreat(v, t)
            if not v.live:
                continue
            if v.state == "candidate":
                v.score = v.base
                if t - v.seen > s.candidate_s:
                    self.finish(v, t, "cancelled", "no message")
                continue
            if not v.inside:                            # only seen at the mouth, never past the line
                if t - v.seen > s.candidate_s:
                    self.finish(v, t, "cancelled", "left the mouth without entering the lane")
                continue
            if v.direction == N and v.front <= 4 and not north_go:
                v.seen = max(v.seen, t)                 # waits for 0x01: no fade
            quiet = t - v.seen
            if quiet <= s.hold_s:
                v.score = v.base
            elif quiet >= s.fade_to_s:
                self.finish(v, t, "cancelled", f"lost: no message for {s.fade_to_s:.0f} s")
                continue
            else:
                frac = (quiet - s.hold_s) / (s.fade_to_s - s.hold_s)
                v.score = s.cut_pct + max(0.0, v.base - s.cut_pct) * (1 - frac * frac)
            if v.state == "leaving":
                d = v.direction
                if v.exit_time is not None and t - v.exit_time >= s.gone_s:
                    self.finish(v, t, "ended", f"left at {END_NAME[d]} ({EXIT_LINE_NAME[d]}, "
                                               f"{s.gone_s:g} s without {OUTER_BOX_NAME[d]})")
                    continue
                if v.exit_time is None and not any(     # northbound at A Box-1, A Cross-Line-2 missed
                        t - last < s.gone_s for k, last in v.zones.items()
                        if not k[1].startswith("CL") and SPOT[k] >= 3):
                    self.finish(v, t, "ended", f"left at HuoShih (A Box-1, its lane boxes quiet "
                                               f"{s.gone_s:g} s)")
                    continue
            if not v.parked and t - v.progress >= s.max_red:
                v.parked = True
                self.e.event(f"{self._name(v)} has not moved for {s.max_red} s at {v.where}; "
                             f"it no longer holds the lights", "WARN")

    def _retreat(self, v, t):
        """Front box quiet while a box behind it keeps reporting: moved back."""
        if not v.zones or t - v.progress < RETREAT_S:
            return
        sign = SIGN[v.direction]
        boxes = {k: last for k, last in v.zones.items() if not k[1].startswith("CL")}
        live = {k: last for k, last in boxes.items() if t - last <= self.s.occupied_s}
        if not live:
            return
        here = max((SPOT[k] for k in live), key=lambda p: p * sign)
        top = max((SPOT[k] for k in boxes), key=lambda p: p * sign)
        if (here - top) * sign >= 0 or (v.front - top) * sign > 0:
            return                                      # still at its furthest box, or past it on a line
        if any(t - last < RETREAT_S for k, last in boxes.items() if SPOT[k] == top):
            return
        v.backing = True
        v.front = here
        v.crossed = {k: c for k, c in v.crossed.items() if (k - here) * sign < 0}
        v.zones = {k: last for k, last in v.zones.items() if (SPOT[k] - here) * sign <= 0}
        v.path.append((t, f"back to {SPOT_NAMES[here]}"))
        self._moved_back(v, t, f"{SPOT_NAMES[top]} quiet, {SPOT_NAMES[here]} still busy")

    def finish(self, v, t, state, reason):
        v.state, v.end_time, v.end_reason = state, t, reason
        if v.entered:
            self.active_spans.append((v.active_since, t))
            self.active_spans = [sp for sp in self.active_spans if t - sp[1] < 600]
            self.done.append(v)
            del self.done[:-self.keep_done]
            level = "EVENT" if state == "ended" else "WARN"
            self.e.event(f"{self._name(v)} {'ended' if state == 'ended' else 'cancelled'}: "
                         f"{reason}", level)
        else:
            self.e.trace(f"#{v.vid} candidate dropped: {reason}")

    def _clean(self, v):
        """No other car held the lights during this car's trip."""
        a, b = v.born - 2, v.end_time + 2
        others = [sp for sp in self.active_spans if not (sp[0] == v.active_since
                                                          and sp[1] == v.end_time)]
        return v.state == "ended" and not any(s0 < b and s1 > a for s0, s1 in others) and not any(
            u is not v and u.entered and u.live for u in self.vehicles)

    def _name(self, v):
        return f"{NAME[v.direction].capitalize()} car #{v.vid}"

    def demand(self):
        return (any(v.holding and v.direction == S for v in self.vehicles),
                any(v.holding and v.direction == N for v in self.vehicles))

    def recent(self, keys, t, window):
        return any(t - self.last.get(k, -1e18) <= window for k in keys)


# ------------------------------------------------------------ camera health

class Health:
    def __init__(self, engine):
        self.e = engine
        self.misses = Counter()             # check -> misses in a row
        self.hits = Counter()               # check -> hits in a row while suspect
        self.suspect = {}                   # check -> time it became suspect
        self.trips = 0

    @staticmethod
    def check_label(check):
        if isinstance(check, frozenset):
            return "/".join(sorted(c for c, _ in check)) + " Box-2"
        return label(check)

    def trip_done(self, v, clean):
        if not clean or v.state != "ended":
            return
        self.trips += 1
        s = self.e.settings
        for check in HEALTH_ROUTE[v.direction]:
            zones = check if isinstance(check, frozenset) else {check}
            name = self.check_label(check)
            if zones & v.visited:
                self.misses[check] = 0
                if check in self.suspect:
                    self.hits[check] += 1
                    if self.hits[check] >= s.recover_hits:
                        del self.suspect[check]
                        self.e.event(f"{name} works again ({s.recover_hits} cars in a row)", "INFO")
            else:
                self.hits[check] = 0
                self.misses[check] += 1
                if self.misses[check] >= s.suspect_misses and check not in self.suspect:
                    self.suspect[check] = self.e.now
                    self.e.event(f"{name} suspect: missed {self.misses[check]} "
                                 f"{NAME[v.direction]} cars in a row", "WARN")

    def suspect_zones(self, cam):
        return [self.check_label(c) for c in self.suspect
                if (c[0] == cam if not isinstance(c, frozenset) else cam in {k[0] for k in c})]

    def south_blind(self, offline):
        """Neither camera A nor camera B can see a southbound car come in."""
        def failing(cam):
            return cam in offline or all(z in self.suspect for z in SOUTH_ENTRY[cam])
        return failing("A") and failing("B")


# ------------------------------------------------------------------ lights

class LightGroup:
    """Addresses that always show the same light."""
    def __init__(self, label_, addresses, traffic, adjust_name):
        self.label, self.addresses, self.traffic, self.adjust_name = (
            label_, addresses, traffic, adjust_name)


GROUPS = [LightGroup("0x00", (0,), ("red", "green"), "adjust_00"),
          LightGroup("0x01", (1,), ("green", "red"), "adjust_01"),
          LightGroup("0x02-03", (2, 3), ("green", "red"), "adjust_23")]
QUANTITY = 4


def fixed_program(s):
    """The V22 cycle CLEARANCE_1 -> TRAFFIC -> ADJUST -> CLEARANCE_2 -> TRAFFIC as one
    settings list per second; every light counts down the seconds left in its colour."""
    seconds = (s.clearance_1, s.traffic, s.adjust, s.clearance_2, s.traffic)
    per_address = [None] * QUANTITY
    for g in GROUPS:
        colors = ("red", g.traffic[0], getattr(s, g.adjust_name), "red", g.traffic[1])
        flat = [c for n, c in zip(seconds, colors) for _ in range(n)]
        cycle = []
        for i, c in enumerate(flat):
            left = 1
            while left < len(flat) and flat[(i + left) % len(flat)] == c:
                left += 1
            cycle.append((c, left))
        for a in g.addresses:
            per_address[a] = cycle
    return [[per_address[a][i] for a in range(QUANTITY)] for i in range(sum(seconds))]


class Lights:
    """The two state machines (south = 0x02/0x03, north = 0x00 + 0x01) and the
    fixed-cycle fallback.  A smart-control state holds its deadline (absolute
    time), so a countdown lasts exactly its seconds and a light changes exactly
    at its deadline, however the packets fall: step() may run at any moment (a
    packet every second, one at once when a car starts or stops holding the
    lights, one at every deadline).  The fixed cycle moves once a second."""

    TRANSITION = 3              # green countdown before the fixed cycle takes over

    def __init__(self, engine):
        self.e = engine
        self.south = ("idle", None)     # idle | count | hold | clear, deadline
        self.north = ("idle", None)     # idle | count | allred | go | end | clear, deadline
        self.mode = "smart"             # smart | to_fixed | fixed
        self.program, self.second = None, 0
        self.transition = None
        self.shown = None               # settings of the last packet
        self.red_since = {S: None, N: None}

    @property
    def north_go(self):
        return self.mode == "smart" and self.north[0] in ("go", "end")

    def next_deadline(self):
        """When the smart lights change next by themselves (None = not by time)."""
        if self.mode != "smart":
            return None
        dues = [u for _, u in (self.south, self.north) if u is not None and u > self.e.now]
        return min(dues, default=None)

    def step(self, south_demand, north_demand, x, z, fixed, extra=False):
        s = self.e.settings
        if extra and self.mode != "smart":
            return self.shown                           # the fixed cycle only moves once a second
        if self.mode == "smart" and fixed:
            self._start_transition()
        if self.mode == "to_fixed":
            out = self._transition_step()
        elif self.mode == "fixed":
            if not fixed and self.second == s.clearance_1 and self.program:
                self._back_to_smart(south_demand, north_demand)
                out = self._smart_step(south_demand, north_demand, x, z, fresh=True)
            else:
                if self.second == 0:
                    self.program = fixed_program(s)     # settings changes apply per cycle
                out = self.program[self.second]
                self.second = (self.second + 1) % len(self.program)
        else:
            out = self._smart_step(south_demand, north_demand, x, z)
        self.shown = out
        return out

    # ------------------------------------------------------------ smart
    def _smart_step(self, sd, nd, x, z, fresh=False):
        s, now = self.e.settings, self.e.now
        blank = s.blank_number
        old_south, old_north = self.south, self.north
        if not fresh:
            self.south = self._south(sd, x, now)
            self.north = self._north(nd, z, now)

        def left(until):                                # whole seconds still to show
            return max(1, math.ceil(until - now - 1e-6))

        st, until = self.south
        south = (("green", left(until)) if st == "count" else
                 ("green", blank) if st == "idle" else ("red", blank))
        nt, until = self.north
        a00 = (("green", left(until)) if nt == "count" else
               ("green", blank) if nt == "idle" else ("red", blank))
        a01 = (("green", left(until)) if nt == "end" else
               ("green", blank) if nt == "go" else ("red", blank))
        self._explain(old_south, old_north, x, z)
        return [a00, a01, south, south]

    def _south(self, demand, x, now):
        s = self.e.settings
        st, until = self.south
        for _ in range(6):                              # a late step may pass several deadlines
            before = (st, until)
            due = until is not None and now >= until
            if st == "idle":
                if demand:
                    st, until = ("count", now + x) if x > 0 else ("hold", None)
            elif st == "count":
                if not demand:
                    st, until = "idle", None
                elif due:
                    st, until = "hold", None
            elif st == "hold":
                if not demand:
                    st, until = ("clear", now + s.y) if s.y > 0 else ("idle", None)
            elif st == "clear":
                if demand:
                    st, until = "hold", None
                elif due:
                    st, until = "idle", None
            if (st, until) == before:
                break
        return st, until

    def _north(self, demand, z, now):
        s = self.e.settings

        def allred(start):
            return ("allred", start + s.w) if s.w > 0 else ("go", None)

        def clear(start):
            return ("clear", start + s.v) if s.v > 0 else ("idle", None)

        st, until = self.north
        for _ in range(8):
            before = (st, until)
            due = until is not None and now >= until
            if st == "idle":
                if demand:
                    st, until = ("count", now + z) if z > 0 else allred(now)
            elif st == "count":
                if not demand:
                    st, until = "idle", None
                elif due:
                    st, until = allred(until)
            elif st == "allred":
                if not demand:
                    st, until = clear(now)
                elif due:
                    st, until = "go", None
            elif st == "go":
                if not demand:
                    st, until = ("end", now + s.u) if s.u > 0 else clear(now)
            elif st == "end":
                if demand:
                    st, until = "go", None
                elif due:
                    st, until = clear(until)
            elif st == "clear":
                if demand:
                    st, until = allred(now)
                elif due:
                    st, until = "idle", None
            if (st, until) == before:
                break
        return st, until

    def _explain(self, old_south, old_north, x, z):
        """Log every change of state, with the reason."""
        e, s = self.e, self.e.settings
        st = self.south[0]
        if st != old_south[0]:
            text = {"count": f"0x02/0x03 green countdown {x} s ({'car on GuiLan arterial' if x == s.x1 else 'GuiLan arterial empty'}) "
                             f"for {e.holders(S)}",
                    "hold": f"0x02/0x03 red for {e.holders(S)}",
                    "clear": f"0x02/0x03 stay red {s.y} s more: no southbound car left",
                    "idle": "0x02/0x03 green"}[st]
            if st == "idle" and old_south[0] == "count":
                text = "0x02/0x03 countdown stopped, green again: the southbound car is gone"
            e.event(text, "LIGHT")
        nt = self.north[0]
        if nt != old_north[0]:
            text = {"count": f"0x00 green countdown {z} s ({'car on HuoShih arterial' if z == s.z1 else 'HuoShih arterial empty'}) "
                             f"for {e.holders(N)}",
                    "allred": f"0x00 red, 0x01 green in {s.w} s",
                    "go": f"0x01 green for {e.holders(N)}",
                    "end": f"0x01 green countdown {s.u} s: no northbound car left",
                    "clear": f"0x01 red, 0x00 green in {s.v} s",
                    "idle": "0x00 green, 0x01 red"}[nt]
            if nt == "idle" and old_north[0] == "count":
                text = "0x00 countdown stopped, green again: the northbound car is gone"
            if nt == "go" and old_north[0] == "end":
                text = f"0x01 green again for {e.holders(N)}"
            e.event(text, "LIGHT")
        for d, red in ((S, st in ("hold", "clear")), (N, nt not in ("idle", "count"))):
            if red and self.red_since[d] is None:
                self.red_since[d] = e.now
            elif not red:
                self.red_since[d] = None

    # ------------------------------------------------------------ fixed
    def _start_transition(self):
        """Count every green down, then all red, then the fixed cycle."""
        self.mode = "to_fixed"
        shown = self.shown or [("green", 0), ("red", 0), ("green", 0), ("green", 0)]
        self.transition = []
        for color, number in shown:
            if color == "green":
                left = number if 0 < number < self.TRANSITION else self.TRANSITION
                self.transition.append(left)
            else:
                self.transition.append(0)
        self.e.event(f"Switching to the fixed cycle (V22): {self.e.fixed_reason}", "WARN")

    def _transition_step(self):
        blank = self.e.settings.blank_number
        if not any(self.transition):
            self.mode, self.second = "fixed", 0
            self.program = fixed_program(self.e.settings)
            self.south, self.north = ("hold", None), ("allred", None)
            out = self.program[0]
            self.second = 1 % len(self.program)
            return out
        out = []
        for i, left in enumerate(self.transition):
            out.append(("green", left) if left else ("red", blank))
            self.transition[i] = max(0, left - 1)
        return out

    def _back_to_smart(self, sd, nd):
        """After the fixed cycle's all-red CLEARANCE_1: every light has been red."""
        self.mode, self.program, self.second = "smart", None, 0
        self.south = ("hold", None) if sd else ("idle", None)
        self.north = ("go", None) if nd else ("idle", None)
        self.e.event("Back to smart control after the all-red clearance", "INFO")


# ------------------------------------------------------------------ engine

class Engine:
    """One object per program: feed it messages and call tick() once a second."""

    def __init__(self, settings=None, log=None, tracing=False):
        self.settings = settings or Settings()
        self.log = log or (lambda msg, level="INFO": None)
        self.tracing = tracing
        self.now = 0.0
        self.tracker = Tracker(self)
        self.health = Health(self)
        self.lights = Lights(self)
        self.counts = Counter()                 # (camera, zone) -> messages
        self.last_cam = {}                      # camera -> time of its last message
        self.started = None
        self.unknown = set()
        self.forced_fixed = False               # operator chose the fixed cycle
        self.last_demand = (False, False)       # (southbound, northbound) at the last packet
        self.fixed_reason = ""
        self.silent_from = None                 # last message before the silence alarm fired

    # ------------------------------------------------------------ input
    def message(self, t, cam, zone):
        """One camera message, timed by this PC (seconds, any steady clock)."""
        self.now = max(self.now, t)
        if self.started is None:
            self.started = t
        key = (cam, zone)
        self.counts[key] += 1
        self.last_cam[cam] = t
        self.tracker.message(t, key)

    def unknown_zone(self, key):
        if key not in self.unknown:
            self.unknown.add(key)
            self.event(f"Message {label(key)} is not part of the B3 setup; ignored", "WARN")

    # ------------------------------------------------------------- tick
    def demand_changed(self):
        """A car started or stopped holding the lights since the last packet."""
        return self.tracker.demand() != self.last_demand

    def next_deadline(self):
        """Time of the next light change that is due by the clock alone."""
        return self.lights.next_deadline()

    def tick(self, t, wall, offline=frozenset(), server_ok=True, extra=False):
        """Advance to time t (wall = local time, for quiet hours) and return the
        packet settings: [(colour, number)] for 0x00, 0x01, 0x02, 0x03.
        extra=True is a packet between the once-a-second ones (a car started or
        stopped holding the lights, or a deadline): smart lights change at once,
        the fixed cycle does not move."""
        self.now = max(self.now, t)
        if self.started is None:
            self.started = t
        s = self.settings
        self.tracker.update(t, self.lights.north_go)
        sd, nd = self.last_demand = self.tracker.demand()
        x = s.x1 if self.tracker.recent(GUILAN_ARTERIAL, t, s.x_window) else s.x2
        z = s.z1 if self.tracker.recent(HUOSHIH_ARTERIAL, t, s.z_window) else s.z2
        reason = self._fixed_reason(t, wall, offline, server_ok)
        if reason != self.fixed_reason:
            if reason:
                self.fixed_reason = reason
            elif self.lights.mode != "smart":
                self.event(f"Safe again ({self.fixed_reason} is over); smart control "
                           f"returns after the next all-red clearance", "INFO")
                self.fixed_reason = ""
            else:
                self.fixed_reason = ""
        return self.lights.step(sd, nd, x, z, bool(self.fixed_reason), extra=extra)

    def _fixed_reason(self, t, wall, offline, server_ok):
        s = self.settings
        if self.forced_fixed:
            return "chosen by the operator"
        if not server_ok:
            return "the HTTP server for the cameras is not running"
        if self.health.south_blind(offline):
            return "cameras A and B both fail: a southbound car could enter unseen"
        quiet = (wall.hour >= s.quiet_from or wall.hour < s.quiet_to) if s.quiet_from > s.quiet_to \
            else s.quiet_from <= wall.hour < s.quiet_to
        last = max(self.last_cam.values(), default=self.started)
        silent = t - last
        if s.quiet_from != s.quiet_to:                  # only count the silence since the quiet hours ended
            day = wall.replace(hour=s.quiet_to, minute=0, second=0, microsecond=0)
            silent = min(silent, (wall - day).total_seconds() % 86400)
        if (not quiet and silent >= s.silent_alarm_min * 60) or self.silent_from == last:
            self.silent_from = last                     # quiet hours do not end it: only a message
            return f"no camera has sent anything for {s.silent_alarm_min} min"
        self.silent_from = None
        return ""

    # ----------------------------------------------------------- output
    def event(self, msg, level="EVENT"):
        self.log(msg, level)

    def trace(self, msg):
        if self.tracing:
            self.log(msg, "TRACE")

    def holders(self, direction):
        cars = [v for v in self.tracker.vehicles if v.holding and v.direction == direction]
        if not cars:
            return "no car"
        return ", ".join(f"#{v.vid} at {v.where}" for v in cars)

    def camera_status(self, offline=frozenset()):
        """{camera: (status, detail)}; status OK / SUSPECT / OFFLINE."""
        out = {}
        for cam in CAMERAS:
            zones = self.health.suspect_zones(cam)
            if cam in offline:
                out[cam] = ("OFFLINE", "no answer to ping")
            elif zones:
                out[cam] = ("SUSPECT", ", ".join(zones))
            else:
                out[cam] = ("OK", "")
        return out

    def vehicles_view(self):
        """Live cars for the screen: newest first."""
        rows = []
        for v in sorted(self.tracker.vehicles, key=lambda v: -v.vid):
            if not v.live:
                continue
            state = v.state + (", parked" if v.parked else "") + (", backing" if v.backing else "")
            rows.append({"id": v.vid, "dir": NAME[v.direction], "score": v.score,
                         "where": v.where, "state": state, "age": self.now - v.born,
                         "quiet": self.now - v.seen, "holding": v.holding})
        return rows


# ------------------------------------------------------------------ replay

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
BODY_RE = re.compile(r"\[Received POST text\]:\s*(\S.*?)\s*$")
REQ_RE = re.compile(r'(\d+\.\d+\.\d+\.\d+) - - \[(\d{1,2})/([A-Za-z]{3})/(\d{4}) '
                    r'(\d{2}):(\d{2}):(\d{2})\] "POST /([^ "]+) HTTP')


def read_log(path):
    """[(t, camera, zone)] from a log written by HTTP_Server.py or by the smart
    program (UTF-16 or UTF-8).  The n-th message text pairs with the n-th
    request line; t counts seconds of the log's own clock."""
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
    elif raw[:2000].count(b"\x00") > 200:
        text = raw.decode("utf-16-le", "replace")
    else:
        text = raw.decode("utf-8-sig", "replace")
    bodies, reqs = [], []
    ip_cam = {ip: cam for cam, ip in CAMERAS.items()}
    for line in text.splitlines():
        m = BODY_RE.search(line)
        if m:
            bodies.append(zone_of_text(m.group(1)))
            continue
        m = REQ_RE.search(line)
        if m:
            ip, d, mon, y, hh, mm, ss, p = m.groups()
            t = calendar.timegm((int(y), MONTHS[mon], int(d), int(hh), int(mm), int(ss)))
            cam = ip_cam.get(ip) or (re.search(r"IP-CAM-([A-Z])", p) or [None, None])[1]
            reqs.append((t, cam))
    return [(t, cam, z) for (t, cam), z in zip(reqs, bodies) if cam and z]


def clock(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M:%S")


def replay(path, settings=None, trace=None, out=sys.stdout):
    """Run a recorded log through the engine, one tick per second, and print the
    light changes, every car and the safety checks."""
    msgs = read_log(path)
    if not msgs:
        print("No messages found.", file=out)
        return None
    lines = []
    lo, hi = trace or (None, None)
    eng = None

    def log(msg, level="INFO"):
        if level == "TRACE" and not (lo is not None and lo <= eng.now % 86400 <= hi):
            return
        lines.append((eng.now, level, msg))

    eng = Engine(settings, log, tracing=trace is not None)
    first, last = int(msgs[0][0]), int(msgs[-1][0]) + 30
    timeline = []                   # (second, settings)
    i = 0
    for sec in range(first, last + 1):
        k = 0
        while i < len(msgs) and msgs[i][0] <= sec:
            t, cam, zone = msgs[i]
            eng.message(sec + 0.01 * min(k, 90), cam, zone)
            if trace is not None and lo <= sec % 86400 <= hi:
                lines.append((sec + 0.01 * k, "RX", label((cam, zone))))
            i += 1
            k += 1
        wall = datetime.fromtimestamp(sec, timezone.utc).replace(tzinfo=None)
        timeline.append((sec, eng.tick(sec + 0.995, wall)))
    report(eng, msgs, lines, timeline, out)
    return eng, lines, timeline


def _red_since(timeline, sec, addr):
    """First second of the red run that covers second sec (None if green then)."""
    colors = {t: st[addr][0] for t, st in timeline}
    if colors.get(sec) != "red":
        return None
    while colors.get(sec - 1) == "red":
        sec -= 1
    return sec


def safety(eng, timeline):
    """Per-car safety numbers from a replay.  The packet sent at the end of
    second k is what the lights show during second k + 1."""
    shown = {sec + 1: st for sec, st in timeline}
    rows = []
    for v in eng.tracker.done:
        row = {"car": v, "danger": False, "note": ""}
        if v.direction == S:
            out_t = v.first.get(8) or v.first.get(9)
            if out_t is None:
                row["note"] = f"did not reach GuiLan ({v.end_reason})"
            else:
                sec = int(out_t)
                st = shown.get(sec)
                red = _red_since(timeline, sec - 1, 2) if st else None
                if red is None:
                    row["danger"] = True
                    row["note"] = "0x02/0x03 GREEN when it left the lane at GuiLan"
                else:
                    row["margin"] = out_t - (red + 1)
                    row["note"] = f"0x02/0x03 red {row['margin']:.0f} s before it left the lane"
        else:
            mouth = min((t for sp, t in v.first.items() if sp <= 3), default=None)
            if mouth is None:
                row["note"] = f"did not reach HuoShih ({v.end_reason})"
            else:
                sec = int(mouth)
                go = next((k for k in range(int(v.active_since), sec + 60)
                           if shown.get(k, [None, ("red",)])[1][0] == "green"), None)
                if go is None:
                    row["note"] = "0x01 not green within 60 s"
                else:
                    row["wait"] = go - mouth
                    row["note"] = (f"0x01 green {row['wait']:.0f} s after it reached the mouth"
                                   if row["wait"] > 0 else
                                   f"0x01 green {-row['wait']:.0f} s before it reached the mouth")
            if v.active_since is not None:
                red = next((k for k in range(int(v.active_since), int(v.active_since) + 60)
                            if shown.get(k, [("green",)])[0][0] == "red"), None)
                if red is not None:
                    row["red00"] = red - v.active_since
        rows.append(row)
    return rows


def report(eng, msgs, lines, timeline, out):
    p = lambda *a: print(*a, file=out)        # noqa: E731
    p(f"# Replay: {len(msgs)} messages, {clock(msgs[0][0])} to {clock(msgs[-1][0])}\n")
    rows = safety(eng, timeline)
    cars = [r["car"] for r in rows]
    p("## Summary\n")
    for d in (S, N):
        mine = [r for r in rows if r["car"].direction == d]
        ended = [r for r in mine if r["car"].state == "ended"]
        margins = sorted(r["margin"] for r in mine if "margin" in r)
        p(f"- {NAME[d].capitalize()} cars in the lane: {len(mine)}; ended normally {len(ended)}; "
          f"cancelled {len(mine) - len(ended)}")
        if margins:
            p(f"  - 0x02/0x03 red before the car left at GuiLan: min {margins[0]:.0f} s, "
              f"median {margins[len(margins) // 2]:.0f} s, max {margins[-1]:.0f} s")
        if d == N:
            waits = sorted(r["wait"] for r in mine if r.get("wait") is not None)
            reds = sorted(r["red00"] for r in mine if r.get("red00") is not None)
            if reds:
                p(f"  - 0x00 red after the car entered: median {reds[len(reds) // 2]:.0f} s, "
                  f"max {reds[-1]:.0f} s")
            if waits:
                p(f"  - 0x01 green after the car reached the HuoShih mouth: median "
                  f"{waits[len(waits) // 2]:.0f} s, max {waits[-1]:.0f} s (negative = already green; "
                  f"the cars in this log drove under the old lights)")
        dangers = [r for r in mine if r["danger"]]
        p(f"  - **unsafe: {len(dangers)}**" if dangers else "  - unsafe: 0")
    both = [sec for sec, st in timeline if st[0][0] == "green" and st[1][0] == "green"]
    p(f"- 0x00 and 0x01 green at the same time: {len(both)} s" + (" **DANGER**" if both else ""))
    for name, addr in (("0x02/0x03", 2), ("0x00", 0)):
        reds = sum(st[addr][0] == "red" for _, st in timeline)
        p(f"- {name} red {reds} s of {len(timeline)} s ({100 * reds / len(timeline):.1f}%)")
    fixed = sum(1 for t, level, msg in lines if "fixed cycle" in msg and level == "WARN")
    p(f"- switches to the fixed cycle: {fixed}")
    p("")
    p("## Every car that entered the lane\n")
    p("| # | dir | in the lane | ended | how | path | safety |")
    p("|---|---|---|---|---|---|---|")
    for r in rows:
        v = r["car"]
        path = " > ".join(dict.fromkeys(z for _, z in v.path))
        p(f"| {v.vid} | {v.direction} | {clock(v.active_since)} | {clock(v.end_time)} | "
          f"{v.state}: {v.end_reason} | {path} | {'**' if r['danger'] else ''}{r['note']}"
          f"{'**' if r['danger'] else ''} |")
    p("")
    p("## Decisions and events\n")
    p("```")
    for t, level, msg in lines:
        p(f"{clock(t)}  {level:5s}  {msg}")
    p("```")
    return cars


# ---------------------------------------------------------------------- CLI

def _span(text):
    a, b = text.split("-")
    to_s = lambda x: sum(int(n) * m for n, m in zip(x.split(":"), (3600, 60, 1)))  # noqa: E731
    return to_s(a), to_s(b)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--replay", metavar="LOG", required=True,
                    help="camera log (HTTP_Server.py output or the smart program's daily file)")
    ap.add_argument("--trace", metavar="HH:MM:SS-HH:MM:SS",
                    help="also show every message and which car it went to in this time span")
    args = ap.parse_args()
    replay(args.replay, trace=_span(args.trace) if args.trace else None)


if __name__ == "__main__":
    main()
