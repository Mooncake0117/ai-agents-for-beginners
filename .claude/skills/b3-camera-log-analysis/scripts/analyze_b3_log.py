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
    return [(t, cam, z, ip) for (t, cam, ip), z in zip(reqs, bodies)], warnings


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

    def chain(self, d, k, t0):
        """Best match of route d around stage k seen at t0.

        Every burst of every stage near the anchor is a candidate.  A chain
        visits stages in route order; the next matched stage must still be
        active when the previous one started (order tolerance) and start no
        later than chain_window_s after the previous one's burst ended.
        Stages may be skipped.  The chain matching the most stages wins
        (ties: smallest total gaps), so one stray trigger cannot derail the
        rest of the trip.  A burst that began before the car could have got
        there (another car was already in the zone) counts as a detection
        but is marked shared and left out of the timing.
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
                for c in self.candidates(d, j, lo, hi):
                    best = None
                    for si, (_, pc, cnt, gs, _) in enumerate(states):
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
            k, t0 = self.primary(tr)
            tr["k"], tr["t0"] = k, t0
            tr["chain"] = self.chain(tr["dir"], k, t0) if k is not None else None
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
                runs = []
                for tr in dtrips:
                    t0 = self.episode_first(tr, stages[k]["alts"]) if ref_only else tr["chain"]["first"][k]
                    if t0 is not None:
                        runs.append(self.chain(d, k, t0))
                results[k] = runs
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
