#!/usr/bin/env python3
"""Analyse ShinKong B3 IP-camera trigger logs (output of the HTTP test server).

    python analyze_b3_log.py LOG [LOG ...] [--config CONFIG] [--json OUT.json]

The log is what `uv run python -u HTTP_Server.py > B3_log.txt 2>&1` writes in
PowerShell (UTF-16) or any shell (UTF-8): one "[Received POST text]: Box-1_triggered."
line (stdout) and one '192.168.7.164 - - [19/Oct/2026 11:00:00] "POST /IP-CAM-A
HTTP/1.1" 200 -' line (stderr) per message.  The two streams can be interleaved
out of order, but each request writes exactly one of each, so the n-th text is
paired with the n-th request line.

Report sections (Markdown on stdout):
  1. Input summary            messages, time span, per-camera zones, last message
  2. Trips                    passages through the connecting lane, seen by the
                              reference camera (IP-CAM-B), with their direction
  3. Hourly volume and trips  messages per camera per hour
  4. Hourly line activity     cross-line messages per camera per hour
  5. Hourly line hits/misses  per trip, did each camera's line fire
  6. Stage reliability        hit rate, outages (N misses in a row), hit rate
                              while healthy, per-camera breakdown
  7. Route timing             per-stage detection rate re-run with every
                              reliable stage as anchor, plus timing and dwell
  8. Zone attribution         bursts of every zone inside southbound / northbound
                              trips or unrelated to any trip (noise)
  9. Camera silences          long gaps with no message from a camera
"""

import argparse
import bisect
import calendar
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
BODY_RE = re.compile(r"\[Received POST text\]:\s*(\S.*?)\s*$")
REQ_RE = re.compile(r'(\d+\.\d+\.\d+\.\d+) - - \[(\d{1,2})/([A-Za-z]{3})/(\d{4}) '
                    r'(\d{2}):(\d{2}):(\d{2})\] "POST /([^ "]+) HTTP')


# ----------------------------------------------------------------- reading

def read_lines(path):
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
    elif raw[:3] == b"\xef\xbb\xbf":
        text = raw[3:].decode("utf-8", "replace")
    elif raw[:2000].count(b"\x00") > 200:        # UTF-16 without BOM
        text = raw.decode("utf-16-le", "replace")
    else:
        text = raw.decode("utf-8", "replace")
    return text.splitlines()


def zone_of(text):
    """'Box-1_triggered.' -> 'B1', 'Cross-Line-2_triggered.' -> 'CL2',
    a merged 'Cross-Line_triggered.' -> 'CL'."""
    m = re.match(r"Box-(\d+)", text)
    if m:
        return "B" + m.group(1)
    m = re.match(r"Cross-Line-(\d+)", text)
    if m:
        return "CL" + m.group(1)
    if text.startswith("Cross-Line"):
        return "CL"
    return text.split("_triggered")[0]


def camera_of(path):
    m = re.search(r"IP-CAM-([A-Za-z0-9]+)", path)
    return m.group(1) if m else path


def parse_log(path):
    """[(t, camera, zone, ip)], warnings.  t = seconds (log clock, no time zone)."""
    bodies, reqs = [], []
    for line in read_lines(path):
        m = BODY_RE.search(line)
        if m:
            bodies.append(zone_of(m.group(1)))
            continue
        m = REQ_RE.search(line)
        if m:
            ip, d, mon, y, hh, mm, ss, p = m.groups()
            t = calendar.timegm((int(y), MONTHS[mon], int(d), int(hh), int(mm), int(ss)))
            reqs.append((t, camera_of(p), ip))
    warnings = []
    if len(bodies) != len(reqs):
        warnings.append(f"{path}: {len(bodies)} message texts but {len(reqs)} request lines; "
                        f"paired the first {min(len(bodies), len(reqs))} in order")
    events, other = [], 0
    for (t, cam, ip), z in zip(reqs, bodies):
        if re.fullmatch(r"B\d+|CL\d*", z) and re.fullmatch(r"[A-Za-z0-9]+", cam):
            events.append((t, cam, z, ip))
        else:
            other += 1                      # not a camera trigger (another program's POST)
    if other:
        warnings.append(f"{path}: skipped {other} POSTs that are not camera triggers")
    return events, warnings


# ------------------------------------------------------------------ helpers

def fmt(t, date=True):
    d = datetime.fromtimestamp(t, timezone.utc)
    return d.strftime("%m-%d %H:%M:%S" if date else "%H:%M:%S")


def hour_label(h):
    return datetime.fromtimestamp(h * 3600, timezone.utc).strftime("%m-%d %H")


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def stats(values):
    """'median / 90% / max' of a list of seconds."""
    if not values:
        return "-"
    v = sorted(values)
    return f"{statistics.median(v):.0f} / {v[int(0.9 * (len(v) - 1))]} / {v[-1]}"


def table(header, rows):
    out = ["| " + " | ".join(str(h) for h in header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def stage_label(alts):
    cams = [c for c, _ in alts]
    zones = [z for _, z in alts]
    if len(set(zones)) == 1:
        return "/".join(cams) + " " + zones[0]
    if len(set(cams)) == 1:
        return cams[0] + " " + "|".join(zones)
    return "|".join(f"{c} {z}" for c, z in alts)


def bursts(times, gap):
    out = []
    for t in times:
        if out and t - out[-1][1] <= gap:
            out[-1][1] = t
        else:
            out.append([t, t])
    return out


# ----------------------------------------------------------------- analyser

class Analyser:
    def __init__(self, events, config, warnings=()):
        self.events = events                     # sorted [(t, cam, zone, ip)]
        self.parse_warnings = list(warnings)
        self.cfg = config
        self.p = config["params"]
        self.ref = config["reference_camera"]
        self.index = defaultdict(list)           # (cam, zone) -> sorted times
        for t, cam, z, _ in events:
            self.index[(cam, z)].append(t)
        self._runs = {}
        self.routes = {}
        for d, spec in config["directions"].items():
            stages = []
            for alts in spec["stages"]:
                pairs = [tuple(a.split(":")) for a in alts]
                stages.append({"alts": pairs, "label": stage_label(pairs)})
            self.routes[d] = dict(spec, stages=stages)

    # occurrences ----------------------------------------------------------
    def first_occ(self, alts, a, b):
        best = None
        for alt in alts:
            lst = self.index.get(alt, ())
            i = bisect.bisect_left(lst, a)
            if i < len(lst) and lst[i] <= b and (best is None or lst[i] < best):
                best = lst[i]
        return best

    # trips -----------------------------------------------------------------
    def find_trips(self):
        gap = self.p["episode_gap_s"]
        eps, cur = [], []
        for t, cam, z, _ in self.events:
            if cam != self.ref:
                continue
            if cur and t - cur[-1][0] > gap:
                eps.append(cur)
                cur = []
            cur.append((t, z))
        if cur:
            eps.append(cur)
        trips = []
        for ep in eps:
            zones = [z for _, z in ep]
            hits = {d: any(z in r["reference_lines"] for z in zones) for d, r in self.routes.items()}
            dirs = [d for d, h in hits.items() if h]
            if len(dirs) == 1:
                d = dirs[0]
                # cars following each other through B without a gap form one episode;
                # each crossing of the direction's reference line is one car
                marks = bursts([t for t, z in ep if z in self.routes[d]["reference_lines"]],
                               self.p["run_gap_s"])
                if len(marks) > 1:
                    parts = [[] for _ in marks]
                    for t, z in ep:
                        i = min(range(len(marks)), key=lambda i: max(marks[i][0] - t, t - marks[i][1], 0))
                        parts[i].append((t, z))
                    trips += [{"dir": d, "start": p[0][0], "end": p[-1][0], "episode": p} for p in parts]
                    continue
            elif len(dirs) > 1:
                d = "+".join(sorted(dirs))            # two cars passing / ambiguous
            else:
                boxes = [z for z in zones if z.startswith("B")]
                d = "?"
                for dd, r in self.routes.items():
                    if boxes and [boxes[0], boxes[-1]] == r["reference_box_order"]:
                        d = dd
            trips.append({"dir": d, "start": ep[0][0], "end": ep[-1][0], "episode": ep})
        return trips

    def episode_first(self, trip, alts):
        for t, z in trip["episode"]:
            if (self.ref, z) in alts:
                return t
        return None

    # route chain -----------------------------------------------------------
    def stage_runs(self, d, j):
        """Bursts of stage j (any alternative): sorted [(start, end)], cached."""
        key = (d, j)
        if key not in self._runs:
            times = sorted(t for alt in self.routes[d]["stages"][j]["alts"] for t in self.index.get(alt, ()))
            runs, gap, cap = [], self.p["run_gap_s"], self.p["run_cap_s"]
            for t in times:
                if runs and t - runs[-1][1] <= gap and t - runs[-1][0] < cap:
                    runs[-1][1] = t
                else:
                    runs.append([t, t])
            self._runs[key] = ([r[0] for r in runs], [r[1] for r in runs], runs)
        return self._runs[key]

    def candidates(self, d, j, a, b):
        starts, ends, runs = self.stage_runs(d, j)
        return [tuple(r) for r in runs[bisect.bisect_left(ends, a):bisect.bisect_right(starts, b)]]

    def chain(self, d, k, t0, taken=()):
        """Best match of route d around stage k seen at t0.

        Every burst of every stage near the anchor is a candidate.  A chain
        visits stages in route order; the next matched stage must still be
        active when the previous one started (order tolerance) and start no
        later than chain_window_s after the previous one's burst ended.
        Stages may be skipped.  The chain matching the most stages wins
        (ties: smallest total gaps), so one stray trigger cannot derail the
        rest of the trip.  A burst that began before the car could have got
        there (another car was already in the zone) counts as a detection
        but is marked shared and left out of the timing.  Bursts listed in
        `taken` as (stage, start) belong to another car and are skipped.
        Returns per stage: entry time, burst end and shared flag, or None."""
        stages = self.routes[d]["stages"]
        n, W = len(stages), self.p["chain_window_s"]
        tol, span = self.p["order_tolerance_s"], self.p["chain_span_s"]
        starts, ends, runs = self.stage_runs(d, k)
        i = bisect.bisect_right(starts, t0) - 1
        anchor = (t0, max(t0, ends[i]) if i >= 0 and ends[i] >= t0 else t0)

        def fits(early, late):          # can `late` follow `early` on the route?
            return late[1] >= early[0] - tol and late[0] <= early[1] + W

        def best_side(order, lo, hi, forward):
            states = [(k, anchor, 1, 0, -1)]            # stage, burst, matched, gap sum, back
            for j in order:
                before = states[:]              # a stage follows earlier stages, never itself
                for c in self.candidates(d, j, lo, hi):
                    if (j, c[0]) in taken:
                        continue
                    best = None
                    for si, (_, pc, cnt, gs, _) in enumerate(before):
                        if fits(pc, c) if forward else fits(c, pc):
                            score = (cnt + 1, -(gs + abs(c[0] - pc[0])))
                            if best is None or score > best[0]:
                                best = (score, si)
                    if best:
                        states.append((j, c, best[0][0], -best[0][1], best[1]))
            si = max(range(len(states)), key=lambda x: (states[x][2], -states[x][3]))
            picked = {}
            while si >= 0:
                j, c, _, _, si = states[si]
                picked[j] = c
            return picked

        picked = best_side(range(k + 1, n), t0 - tol, t0 + span, True)
        picked.update(best_side(range(k - 1, -1, -1), t0 - span, t0 + tol, False))
        first, end, shared = [None] * n, [None] * n, [False] * n
        for j, (s, e) in picked.items():
            first[j], end[j] = s, e
        for j in sorted(picked):        # entry before the neighbour nearer the anchor?
            near = [i for i in picked if (i < j if j > k else i > j) and (i >= k if j > k else i <= k)]
            if near:
                i = max(near) if j > k else min(near)
                limit = first[i] - tol if j > k else first[i] - W
                shared[j] = first[j] < limit
        return {"first": first, "end": end, "shared": shared}

    def chain_cars(self, d, anchors):
        """chain() for every (stage, time) anchor of direction d, car by car in time
        order.  Cars cannot overtake in the lane and a cross-line sends one message per
        car, so a line burst matched to one car is not offered to the next: otherwise a
        car in a convoy takes the crossing of the car in front and hides its own miss."""
        lines_only = {j for j, st in enumerate(self.routes[d]["stages"])
                      if all(z.startswith("CL") for _, z in st["alts"])}
        taken, out = set(), [None] * len(anchors)
        for i in sorted(range(len(anchors)), key=lambda i: anchors[i][1]):
            ch = self.chain(d, *anchors[i], taken)
            taken.update((j, ch["first"][j]) for j in lines_only if ch["first"][j] is not None)
            out[i] = ch
        return out

    def primary(self, trip):
        r = self.routes[trip["dir"]]
        stages = r["stages"]
        for a in r["primary_anchors"]:
            alt = tuple(a.split(":"))
            t0 = self.episode_first(trip, [alt])
            if t0 is None:
                continue
            for k, st in enumerate(stages):
                if alt in st["alts"]:
                    return k, t0
        return None, None

    def alt_hits(self, d, ch):
        """Which alternatives of each stage fired during its matched burst."""
        out = []
        for st, s, e in zip(self.routes[d]["stages"], ch["first"], ch["end"]):
            out.append({alt: (s is not None and self.first_occ([alt], s, e) is not None)
                        for alt in st["alts"]})
        return out

    # scorecard -------------------------------------------------------------
    def scorecard(self, good, odd, out, lines):
        """Sections 10 and 11.  Uses 'clean' trips (no other lane trip within
        clean_window_s) so that a detection can only come from the trip's own car."""
        P = self.p
        target, cw, look = P["target_pct"], P["clean_window_s"], P["placement_window_s"]
        tol = P["order_tolerance_s"]
        dirs = list(self.routes)
        times = sorted(tr.get("t0") or tr["start"] for tr in good + odd)

        def is_clean(t):
            return bisect.bisect_right(times, t + cw) - bisect.bisect_left(times, t - cw) <= 1

        clean = {d: [tr for tr in good if tr["dir"] == d and is_clean(tr["t0"])] for d in dirs}
        cache = {}

        def entry_near(pair, t0):
            """Entry time of the burst of `pair` closest to t0 (within +-look), or None."""
            if pair not in cache:
                bs = bursts(self.index.get(pair, ()), P["run_gap_s"])
                cache[pair] = ([b[0] for b in bs], [b[1] for b in bs])
            starts, ends = cache[pair]
            best = None
            for i in range(bisect.bisect_left(ends, t0 - look), bisect.bisect_right(starts, t0 + look)):
                dist = 0 if starts[i] <= t0 <= ends[i] else min(abs(starts[i] - t0), abs(ends[i] - t0))
                if best is None or dist < best[0]:
                    best = (dist, starts[i])
            return None if best is None else best[1]

        def is_line(pair):
            return pair[1].startswith("CL")

        lines.append(f"\n## 10. Detection scorecard (target {target}%)\n")
        lines.append(
            "*route order* = hit rate from the route match (section 6), which decides the status; "
            f"*clean trips* = trips with no other car in the lane within {cw} s, counting the stage "
            f"as fired if any of its zones fired within {look} s, in any order (a cross-check: much "
            "higher than the route-order rate means the zone fires, but not where the route says); "
            "*wrong direction* = a line firing while the car of a clean opposite-direction trip was "
            "in front of that camera (flagged from 2 occurrences); *no trip* = share of the line's "
            "bursts with no lane trip at all (section 8).  Missed trips are listed so the camera "
            "recording can be checked at those times.\n")
        out["scorecard"] = {}
        attribution = out.get("attribution", {})
        for d in dirs:
            stages = self.routes[d]["stages"]
            dtrips = [tr for tr in good if tr["dir"] == d]
            n, nc = len(dtrips), len(clean[d])
            if not n:
                continue
            others = [tr for o in dirs if o != d for tr in clean[o]]

            def in_view(alt, tr):
                """When did line `alt` fire while the opposite trip's car was in front of
                that camera (its own matched stages on the same camera, +-tolerance)?
                None = the camera never saw that trip, False = the line stayed quiet."""
                st_o = self.routes[tr["dir"]]["stages"]
                ch = tr["chain"]
                spans_o = [(f, e) for s_, f, e in zip(st_o, ch["first"], ch["end"])
                           if f is not None and any(c == alt[0] for c, _ in s_["alts"])]
                if not spans_o:
                    return None
                a = min(f for f, _ in spans_o) - tol
                b = max(min(e, f + P["chain_window_s"]) for f, e in spans_o) + tol
                t = self.first_occ([alt], a, b)
                return False if t is None else t

            rows, flags = [], []
            for k, st in enumerate(stages):
                hits = sum(tr["hit"][k] for tr in dtrips)
                c_hits = sum(any(entry_near(alt, tr["t0"]) is not None for alt in st["alts"])
                             for tr in clean[d])
                wrong, noise = [], []
                for alt in st["alts"]:
                    if not is_line(alt) or alt not in self.index:
                        continue
                    seen = [v for v in (in_view(alt, tr) for tr in others) if v is not None]
                    if seen:
                        w = sum(v is not False for v in seen)
                        wrong.append((100 * w / len(seen), f"{alt[0]} {alt[1]}", w))
                    at = attribution.get(f"{alt[0]} {alt[1]}")
                    if at and at.get("bursts"):
                        noise.append((100 * at.get("unrelated", 0) / at["bursts"], f"{alt[0]} {alt[1]}"))
                worst_w = max(wrong) if wrong else None
                worst_n = max(noise) if noise else None
                problems = []
                if 100 * hits / n < target:
                    problems.append("misses")
                if nc and 100 * c_hits / nc - 100 * hits / n >= 10:
                    problems.append("check route order (fires, but not where configured)")
                if worst_w and worst_w[0] > 100 - target and worst_w[2] >= 2:
                    problems.append(f"wrong direction ({worst_w[1]})")
                if worst_n and worst_n[0] > 100 - target:
                    problems.append(f"fires without a trip ({worst_n[1]})")
                missed = [fmt(tr["t0"]) for tr in sorted(dtrips, key=lambda tr: tr["t0"]) if not tr["hit"][k]]
                rows.append([st["label"], f"{hits}/{n} ({pct(hits, n)})",
                             f"{c_hits}/{nc} ({pct(c_hits, nc)})" if nc else "-",
                             f"{worst_w[0]:.0f}% {worst_w[1]} ({worst_w[2]}x)" if worst_w else "-",
                             f"{worst_n[0]:.0f}% {worst_n[1]}" if worst_n else "-",
                             "OK" if not problems else "**" + ", ".join(problems) + "**",
                             ", ".join(missed[:6]) + (f" (+{len(missed) - 6} more)" if len(missed) > 6 else "")
                             or "-"])
                if problems:
                    flags.append(f"{st['label']}: {', '.join(problems)}")
                out["scorecard"].setdefault(d, []).append({
                    "stage": st["label"], "route_hits": hits, "trips": n, "clean_hits": c_hits,
                    "clean_trips": nc, "wrong_direction_pct": worst_w and round(worst_w[0]),
                    "no_trip_pct": worst_n and round(worst_n[0]), "problems": problems, "missed": missed})
            lines.append(f"\n**{self.routes[d]['name']}**: {n} trips ({nc} clean); one miss = "
                         f"{100 / n:.1f}% of all trips\n")
            lines.append(table(["Stage", "hit, route order", "hit, clean trips", "wrong direction",
                                "no trip", "status", "missed trips"], rows))
            lines.append("\nBelow target: " + ("; ".join(flags) if flags else "none"))

            # every cross-line of this direction on its own
            lrows = []
            for k, st in enumerate(stages):
                for alt in st["alts"]:
                    if not is_line(alt) or alt not in self.index:
                        continue
                    own = sum(tr["alt"][k][alt] for tr in dtrips)
                    seen = [(v, tr) for tr in others if (v := in_view(alt, tr)) is not None]
                    fired = [(v, tr) for v, tr in seen if v is not False]
                    offs = sorted(v - tr["t0"] for v, tr in fired)
                    mates = [p for p in self.index if p[0] == alt[0] and is_line(p) and p != alt]
                    together = sum(any(self.first_occ([p], v - 1, v + 1) is not None for p in mates)
                                   for v, _ in fired)
                    at = attribution.get(f"{alt[0]} {alt[1]}", {})
                    lrows.append([f"{alt[0]} {alt[1]}", f"{own}/{n} ({pct(own, n)})",
                                  f"{len(fired)}/{len(seen)} ({pct(len(fired), len(seen))})" if seen else "-",
                                  f"{statistics.median(offs):+.0f} ({offs[0]:+d} .. {offs[-1]:+d})"
                                  if offs else "-",
                                  f"{together}/{len(fired)}" if fired and mates else "-",
                                  pct(at.get("unrelated", 0), at.get("bursts", 0))])
            if lrows:
                lines.append(f"\nEvery cross-line used {self.routes[d]['name'].split(' (')[0].lower()}: "
                             "hit = fired on this direction's trips; wrong direction = fired while a "
                             "clean opposite-direction car was in front of the camera; *when* = seconds "
                             "from that car's anchor (B CL2 for a southbound line, B CL1 for a northbound "
                             "one) to the wrong firing, median (range); *with other line* = wrong firings "
                             "within 1 s of another line of the same camera, i.e. one car set off both "
                             "lines at once\n")
                lines.append(table(["Line", "hit", "wrong direction", "when (s)", "with other line",
                                    "no trip"], lrows))

        lines.append("\n## 11. Placement and order check\n")
        lines.append(f"Where each zone really fires on clean trips: entry time of its burst nearest to "
                     f"the trip anchor, in seconds relative to the anchor (median and 10-90% range). "
                     f"A stage that fires more than {tol} s out of the configured order is flagged: "
                     f"either the route order in config.json is wrong, or the zone is not where it "
                     f"was meant to be.\n")
        out["placement"] = {}
        for d in dirs:
            stages = self.routes[d]["stages"]
            cl = clean[d]
            if not cl:
                continue
            anchor = self.routes[d]["primary_anchors"][0].replace(":", " ")
            meds, rows = [], []
            for k, st in enumerate(stages):
                stage_offs = []
                for tr in cl:
                    es = [entry_near(alt, tr["t0"]) for alt in st["alts"]]
                    es = [e for e in es if e is not None]
                    if es:
                        stage_offs.append(min(es) - tr["t0"])
                meds.append(statistics.median(stage_offs) if stage_offs else None)
                for alt in st["alts"]:
                    if alt not in self.index:
                        continue
                    offs = sorted(e - tr["t0"] for tr in cl
                                  if (e := entry_near(alt, tr["t0"])) is not None)
                    rows.append([k + 1, f"{alt[0]} {alt[1]}", pct(len(offs), len(cl)),
                                 f"{statistics.median(offs):+.0f}" if offs else "-",
                                 f"{offs[int(0.1 * (len(offs) - 1))]:+d} .. {offs[int(0.9 * (len(offs) - 1))]:+d}"
                                 if offs else "-", ""])
            # order notes per stage, attached to the stage's first row
            notes = {}
            for k in range(len(stages)):
                if meds[k] is None:
                    continue
                msg = []
                for i in range(k):
                    if meds[i] is not None and meds[k] < meds[i] - tol:
                        msg.append(f"fires {meds[i] - meds[k]:.0f} s before {stages[i]['label']}")
                for j in range(k + 1, len(stages)):
                    if meds[j] is not None and meds[k] > meds[j] + tol:
                        msg.append(f"fires {meds[k] - meds[j]:.0f} s after {stages[j]['label']}")
                if msg:
                    notes[k] = "**" + "; ".join(msg) + "**"
            for r in rows:
                if r[0] - 1 in notes:
                    r[5] = notes.pop(r[0] - 1)
            order = [st["label"] for _, st in sorted(
                ((m, st) for m, st in zip(meds, stages) if m is not None), key=lambda x: x[0])]
            lines.append(f"\n**{self.routes[d]['name']}**: {len(cl)} clean trips, anchor {anchor}\n")
            lines.append(table(["Stage #", "Zone", "fired", "median s", "10-90% s", "order note"], rows))
            lines.append("\nOrder by median entry time: " + " -> ".join(order))
            out["placement"][d] = {"order": order, "medians": meds}

    # report ----------------------------------------------------------------
    def run(self):
        P = self.p
        out = {"warnings": list(self.parse_warnings)}
        lines = []
        ev = self.events
        if not ev:
            print("No messages found.")
            return {}
        cams = sorted({c for _, c, _, _ in ev})

        # 1. input summary
        lines.append("# B3 camera log analysis\n")
        lines.append(f"Messages: **{len(ev)}**, from {fmt(ev[0][0])} to {fmt(ev[-1][0])}.\n")
        zc = Counter((c, z) for _, c, z, _ in ev)
        ips = defaultdict(set)
        for _, c, _, ip in ev:
            ips[c].add(ip)
        zones = sorted({z for _, _, z, _ in ev})
        last = {}
        for t, c, z, _ in ev:
            last[(c, z)] = t
        lines.append("## 1. Input summary\n")
        lines.append(table(["Camera", "IP"] + zones + ["last message per zone"],
                           [[c, ",".join(sorted(ips[c]))] + [zc[(c, z)] or "" for z in zones]
                            + [", ".join(f"{z} {fmt(last[(c, z)])}" for z in zones if (c, z) in last)]
                            for c in cams]))
        expected_ips = self.cfg.get("cameras", {})
        for c in cams:
            if c in expected_ips and ips[c] != {expected_ips[c]}:
                out["warnings"].append(f"camera {c} sent from {sorted(ips[c])}, config says {expected_ips[c]}")

        # 2. trips
        trips = self.find_trips()
        good = [tr for tr in trips if tr["dir"] in self.routes]
        for tr in good:
            tr["k"], tr["t0"] = self.primary(tr)
            tr["chain"] = None
        for d in self.routes:
            cars = [tr for tr in good if tr["dir"] == d and tr["k"] is not None]
            for tr, ch in zip(cars, self.chain_cars(d, [(tr["k"], tr["t0"]) for tr in cars])):
                tr["chain"] = ch
        good = [tr for tr in good if tr["chain"]]
        dc = Counter(tr["dir"] for tr in trips)
        lines.append("\n## 2. Trips through the connecting lane (reference camera "
                     f"IP-CAM-{self.ref})\n")
        lines.append(table(["Direction", "Trips"],
                           [[self.routes[d]["name"] if d in self.routes else
                             ("both lines fired (cars passing?)" if "+" in d else "unclear"), n]
                            for d, n in sorted(dc.items())]))
        odd = [tr for tr in trips if tr["dir"] not in self.routes]
        if odd:
            lines.append("\nNot used in the statistics: " + ", ".join(
                f"{fmt(tr['start'])} ({tr['dir']})" for tr in odd))

        # per trip, per stage hit / miss from the primary chain
        for tr in good:
            tr["hit"] = [f is not None for f in tr["chain"]["first"]]
            tr["alt"] = self.alt_hits(tr["dir"], tr["chain"])

        # 3. hourly volume
        hours = sorted({t // 3600 for t, _, _, _ in ev})
        vol = defaultdict(Counter)
        for t, c, _, _ in ev:
            vol[t // 3600][c] += 1
        th = defaultdict(Counter)
        for tr in good:
            th[tr["t0"] // 3600][tr["dir"]] += 1
        dirs = list(self.routes)
        lines.append("\n## 3. Hourly volume and trips\n")
        lines.append(table(["Hour"] + [f"{d} trips" for d in dirs] + cams,
                           [[hour_label(h)] + [th[h][d] for d in dirs] + [vol[h][c] for c in cams]
                            for h in hours]))

        # 4. hourly line activity
        line_pairs = sorted({(c, z) for _, c, z, _ in ev if z.startswith("CL")})
        lc = defaultdict(Counter)
        for t, c, z, _ in ev:
            if z.startswith("CL"):
                lc[t // 3600][(c, z)] += 1
        lines.append("\n## 4. Hourly cross-line messages per camera\n")
        lines.append(table(["Hour"] + [f"{c} {z}" for c, z in line_pairs],
                           [[hour_label(h)] + [lc[h][p] for p in line_pairs] for h in hours]))

        # 5. hourly line hits / misses per trip
        lines.append("\n## 5. Hourly cross-line hits per trip (hits/trips; 'miss' = no "
                     "alternative of that stage fired)\n")
        out["hourly_lines"] = {}
        for d in dirs:
            stages = self.routes[d]["stages"]
            line_stages = [k for k, st in enumerate(stages) if any(z.startswith("CL") for _, z in st["alts"])]
            cols, colspec = [], []
            for k in line_stages:
                for alt in stages[k]["alts"]:
                    if alt[1].startswith("CL") and alt in self.index:
                        cols.append(f"{alt[0]} {alt[1]}")
                        colspec.append(("alt", k, alt))
                if len(stages[k]["alts"]) > 1:
                    cols.append(f"miss {stages[k]['label']}")
                    colspec.append(("miss", k, None))
            rows = []
            dtrips = [tr for tr in good if tr["dir"] == d]
            for h in hours:
                ht = [tr for tr in dtrips if tr["t0"] // 3600 == h]
                if not ht:
                    continue
                row = [hour_label(h), len(ht)]
                for kind, k, alt in colspec:
                    if kind == "alt":
                        row.append(f"{sum(tr['alt'][k][alt] for tr in ht)}/{len(ht)}")
                    else:
                        row.append(sum(not tr["hit"][k] for tr in ht))
                rows.append(row)
            lines.append(f"\n**{self.routes[d]['name']}**\n")
            lines.append(table(["Hour", "trips"] + cols, rows) if rows else "(no trips)")

        # 6. stage reliability, outages, healthy hit rate
        lines.append("\n## 6. Stage reliability (outage = "
                     f"{P['outage_streak']}+ trips in a row missed)\n")
        out["stages"] = {}
        for d in dirs:
            stages = self.routes[d]["stages"]
            dtrips = sorted((tr for tr in good if tr["dir"] == d), key=lambda tr: tr["t0"])
            rows = []
            for k, st in enumerate(stages):
                hits = [tr["hit"][k] for tr in dtrips]
                outages, i = [], 0
                while i < len(hits):
                    if not hits[i]:
                        j = i
                        while j < len(hits) and not hits[j]:
                            j += 1
                        if j - i >= P["outage_streak"]:
                            outages.append((i, j - 1))
                        i = j
                    else:
                        i += 1
                in_out = set(x for a, b in outages for x in range(a, b + 1))
                healthy = [h for i, h in enumerate(hits) if i not in in_out]
                alt_txt = ", ".join(
                    f"{c} {z} {pct(sum(tr['alt'][k][(c, z)] for tr in dtrips), len(dtrips))}"
                    for c, z in st["alts"] if (c, z) in self.index) if len(st["alts"]) > 1 else ""
                out_txt = "; ".join(f"{fmt(dtrips[a]['t0'])} to {fmt(dtrips[b]['t0'])} ({b - a + 1} trips)"
                                    for a, b in outages)
                rows.append([st["label"], f"{sum(hits)}/{len(hits)} ({pct(sum(hits), len(hits))})",
                             f"{sum(healthy)}/{len(healthy)} ({pct(sum(healthy), len(healthy))})",
                             out_txt or "-", alt_txt or "-"])
                out["stages"].setdefault(d, []).append({
                    "stage": st["label"], "hits": sum(hits), "trips": len(hits),
                    "healthy_hits": sum(healthy), "healthy_trips": len(healthy),
                    "outages": [(fmt(dtrips[a]["t0"]), fmt(dtrips[b]["t0"]), b - a + 1) for a, b in outages]})
            lines.append(f"\n**{self.routes[d]['name']}** ({len(dtrips)} trips)\n")
            lines.append(table(["Stage", "hit (all trips)", "hit (healthy)", "outages", "per camera"], rows))

        # 7. route timing with several anchors
        lines.append("\n## 7. Route detection rate and timing per anchor\n")
        lines.append("Each column re-runs the route chain anchored on a different stage "
                     f"(every stage with at least {P['anchor_min_rate_pct']}% detection, plus the "
                     "primary anchor). 'trips' = trips in which that anchor stage was seen.\n")
        out["anchors"] = {}
        for d in dirs:
            stages = self.routes[d]["stages"]
            dtrips = [tr for tr in good if tr["dir"] == d]
            if not dtrips:
                continue
            rate = [sum(tr["hit"][k] for tr in dtrips) / len(dtrips) for k in range(len(stages))]
            cand = [k for k in range(len(stages)) if 100 * rate[k] >= P["anchor_min_rate_pct"]]
            results = {}
            for k in cand:
                ref_only = all(c == self.ref for c, _ in stages[k]["alts"])
                anchors = []
                for tr in dtrips:
                    t0 = self.episode_first(tr, stages[k]["alts"]) if ref_only else tr["chain"]["first"][k]
                    if t0 is not None:
                        anchors.append((k, t0))
                results[k] = self.chain_cars(d, anchors)
            header = ["Stage"] + [f"anchor {stages[k]['label']}" for k in cand]
            rows = [["trips"] + [len(results[k]) for k in cand]]
            for j, st in enumerate(stages):
                row = [st["label"]]
                for k in cand:
                    rs = results[k]
                    row.append("anchor" if j == k else pct(sum(r["first"][j] is not None for r in rs), len(rs)))
                rows.append(row)
            lines.append(f"\n**{self.routes[d]['name']}** ({len(dtrips)} trips found by IP-CAM-{self.ref})\n")
            lines.append(table(header, rows))
            out["anchors"][d] = {stages[k]["label"]: {
                "trips": len(results[k]),
                "detected_pct": [round(100 * sum(r["first"][j] is not None for r in results[k]) / max(1, len(results[k])))
                                 for j in range(len(stages))]} for k in cand}
            # timing from the primary chains
            trows = []
            for j, st in enumerate(stages):
                gaps, dwell = [], []
                for tr in dtrips:
                    f, sh = tr["chain"]["first"], tr["chain"]["shared"]
                    if f[j] is None or sh[j]:
                        continue
                    dwell.append(tr["chain"]["end"][j] - f[j])
                    prev = [i for i in range(j - 1, -1, -1) if f[i] is not None]
                    if prev and not sh[prev[0]]:
                        gaps.append(max(0, f[j] - f[prev[0]]))
                trows.append([st["label"], pct(sum(tr["hit"][j] for tr in dtrips), len(dtrips)),
                              stats(gaps) if j else "-", stats(dwell)])
            totals = []
            for tr in dtrips:
                f = [x for x, sh in zip(tr["chain"]["first"], tr["chain"]["shared"]) if x is not None and not sh]
                if len(f) > 1:
                    totals.append(max(f) - min(f))
            lines.append("\nTiming (primary anchor), seconds as median / 90% / max; bursts shared with "
                         "another car are left out:\n")
            lines.append(table(["Stage", "detected", "after previous detected stage", "dwell in zone"], trows))
            lines.append(f"\nWhole route, first to last detected stage: {stats(totals)} s")

        # 8. zone attribution
        lines.append("\n## 8. Zone attribution (bursts of messages; a burst ends after "
                     f"{P['episode_gap_s']} s of silence)\n")
        margin = P["attribution_margin_s"]
        spans = defaultdict(list)
        for tr in good:
            ch = tr["chain"]
            f = [x for x in ch["first"] if x is not None]
            e = [min(en, fi + P["chain_window_s"]) for fi, en in zip(ch["first"], ch["end"]) if fi is not None]
            spans[tr["dir"]].append((min(f) - margin, max(e) + margin))
        for tr in odd:
            spans["unclear"].append((tr["start"] - 10, tr["end"] + 10))
        for k in spans:
            spans[k].sort()

        def overlaps(lst, a, b):
            i = bisect.bisect_right(lst, (b, float("inf")))
            return any(s <= b and e >= a for s, e in lst[max(0, i - 50):i])

        rows = []
        out["attribution"] = {}
        for pair in sorted(self.index):
            bs = bursts(self.index[pair], P["episode_gap_s"])
            cnt = Counter()
            for a, b in bs:
                inn = [d for d in dirs if overlaps(spans[d], a, b)]
                if len(inn) > 1:
                    cnt["both"] += 1
                elif inn:
                    cnt[inn[0]] += 1
                elif overlaps(spans["unclear"], a, b):
                    cnt["unclear"] += 1
                else:
                    cnt["unrelated"] += 1
            rows.append([f"{pair[0]} {pair[1]}", len(self.index[pair]), len(bs)]
                        + [cnt[d] for d in dirs] + [cnt["both"], cnt["unclear"], cnt["unrelated"],
                                                    pct(cnt["unrelated"], len(bs))])
            out["attribution"][f"{pair[0]} {pair[1]}"] = dict(cnt, bursts=len(bs))
        lines.append(table(["Zone", "messages", "bursts"] + [f"in {d} trips" for d in dirs]
                           + ["in both", "unclear trips", "unrelated", "unrelated %"], rows))

        # 9. camera silences
        lim = P["silence_report_min"] * 60
        lines.append(f"\n## 9. Camera silences of {P['silence_report_min']}+ minutes\n")
        rows = []
        by_cam = defaultdict(list)
        for t, c, _, _ in ev:
            by_cam[c].append(t)
        for c in cams:
            ts = by_cam[c]
            gaps = [(a, b) for a, b in zip(ts, ts[1:]) if b - a >= lim]
            rows.append([c, len(gaps), "; ".join(f"{fmt(a)} to {fmt(b)} ({(b - a) // 60} min)"
                                                 for a, b in gaps[:8]) + (" ..." if len(gaps) > 8 else "") or "-"])
        lines.append(table(["Camera", "silences", "periods"], rows))

        # 10-11. scorecard against the accuracy target, placement / order check
        self.scorecard(good, odd, out, lines)

        warnings = out["warnings"]
        if warnings:
            lines.insert(1, "\n**Warnings:** " + " / ".join(warnings) + "\n")
        print("\n".join(lines))
        out["trips"] = [{"dir": tr["dir"], "time": fmt(tr["t0"] if tr.get("t0") else tr["start"]),
                         "hits": tr.get("hit")} for tr in trips]
        return out


def main():
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+", help="log file(s) written by HTTP_Server.py")
    ap.add_argument("--config", default=str(here / "config.json"))
    ap.add_argument("--json", help="also write the computed numbers to this JSON file")
    ap.add_argument("--drop", action="append", default=[], metavar="CAM:ZONE",
                    help="leave a zone out of the routes, e.g. --drop E:CL1 for logs recorded "
                         "before IP-CAM-E's lines were moved next to the lane (repeatable)")
    args = ap.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    for spec in config["directions"].values():
        spec["stages"] = [kept for kept in ([a for a in alts if a not in args.drop]
                                            for alts in spec["stages"]) if kept]
        spec["primary_anchors"] = [a for a in spec["primary_anchors"] if a not in args.drop]
    events, warnings = [], []
    for i, path in enumerate(args.logs):
        ev, w = parse_log(path)
        events += [(t, c, z, ip, i, n) for n, (t, c, z, ip) in enumerate(ev)]
        warnings += w
    events.sort(key=lambda e: (e[0], e[4], e[5]))
    an = Analyser([e[:4] for e in events], config, warnings)
    out = an.run()
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
