"""Shared helpers for the B3 checks: engines, replays, analysis trips, live light states.

Put the logs in traffic-light-shinkong/data/ (or set B3_DATA): B3_log_YYYY-MM-DD.txt and
B3_decisions_YYYY-MM-DD.txt.  ENGINE_DIR arguments are folders holding a smart_B3_engine.py
(e.g. ".." for the current one, or a folder with an older version from git show).

    python check.py live                 safety at every real exit, live decisions
    python check.py ..                   the same in a replay with the engine in ..
    python summary.py OLD_DIR NEW_DIR    red seconds, cars, possible cars, stops per day
    python margins.py OLD_DIR NEW_DIR    exits that get less red warning with NEW
    python trace.py .. DAY 10:05:25 10:05:50 [-t] [-q]   decisions (+ messages) in a window
    python spans.py DAY 10:05:25 10:05:50                 raw zone activity in a window
    python rules_test.py ..              scenario tests (no line may say DANGER)
"""
import sys, io, os, re, json, calendar, contextlib, importlib.util, pickle, collections

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # traffic-light-shinkong
REPO = os.path.dirname(PKG)
DATA = os.environ.get("B3_DATA", os.path.join(PKG, "data"))  # B3_log_*.txt / B3_decisions_*.txt (not in git)
SKILL = REPO + "/.claude/skills/b3-camera-log-analysis"
sys.path.insert(0, SKILL + "/scripts")
import analyze_b3_log as A        # noqa: E402

DAYS = sorted(f[7:17] for f in os.listdir(DATA) if f.startswith("B3_log_") and f.endswith(".txt")) \
    if os.path.isdir(DATA) else []                # every B3_log_YYYY-MM-DD.txt in DATA
def log_of(day): return f"{DATA}/B3_log_{day}.txt"
def dec_of(day): return f"{DATA}/B3_decisions_{day}.txt"

_engines = {}
def engine(d):
    """Load smart_B3_engine.py from directory d (each directory its own module)."""
    d = os.path.abspath(d)
    if d not in _engines:
        name = "eng_" + re.sub(r"\W", "_", d)
        spec = importlib.util.spec_from_file_location(name, d + "/smart_B3_engine.py")
        m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m)
        _engines[d] = m
    return _engines[d]

def pc_settings(e):
    """The settings the B3-PC runs with (read from the 10/28-10/30 decisions logs)."""
    st = e.Settings()
    st.u, st.v, st.w, st.y = 3, 2, 2, 3
    st.x1, st.x2, st.z1, st.z2 = 3, 2, 3, 2
    st.south_start, st.backing_stop = "A Box-1", "On"
    return st

def replay(d, day, trace=None, **over):
    e = engine(d)
    st = pc_settings(e)
    for k, v in over.items(): setattr(st, k, v)
    eng, lines, tl = e.replay(log_of(day), st, trace=trace, out=io.StringIO())
    return e, eng, lines, tl

def clk(t): return f"{int(t) % 86400 // 3600:02d}:{int(t) % 3600 // 60:02d}:{int(t) % 60:02d}"
def ts(day, hms):
    y, mo, d = map(int, day.split("-")); h, mi, s = map(int, hms.split(":"))
    return calendar.timegm((y, mo, d, h, mi, s))

def analysis(day):
    """Raw events, the analysis trips and each trip's stage times (cached)."""
    os.makedirs(f"{DATA}/cache", exist_ok=True)
    cache = f"{DATA}/cache/an_{day}.pkl"
    if os.path.exists(cache):
        return pickle.load(open(cache, "rb"))
    cfg = json.load(open(SKILL + "/config.json"))
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        ev, w = A.parse_log(log_of(day))
        an = A.Analyser(ev, cfg, w)
        trips = [t for t in an.find_trips() if t["dir"] in ("S", "N")]
        out = []
        for d in ("S", "N"):
            cs = [t for t in trips if t["dir"] == d]
            for t in cs: t["k"], t["t0"] = an.primary(t)
            cs = [t for t in cs if t["k"] is not None]
            ch = an.chain_cars(d, [(t["k"], t["t0"]) for t in cs])
            st = [s["label"] for s in an.routes[d]["stages"]]
            for t, c in zip(cs, ch):
                out.append({"dir": d, "t0": t["t0"], "f": dict(zip(st, c["first"]))})
    res = ([(t, cam, z) for t, cam, z, ip in ev], sorted(out, key=lambda x: x["t0"]))
    pickle.dump(res, open(cache, "wb"))
    return res

def by_zone(ev):
    by = collections.defaultdict(list)
    for t, cam, z in ev: by[(cam, z)].append(t)
    return by

LIGHT_RULES = [
    ("0x00 green countdown", {"00": "count", "01": "red"}),
    ("0x00 red, 0x01 green in", {"00": "red", "01": "red"}),
    ("0x01 green for", {"00": "red", "01": "green"}),
    ("0x01 green again", {"00": "red", "01": "green"}),
    ("0x01 green countdown", {"00": "red", "01": "count"}),
    ("0x01 red, 0x00 green in", {"00": "red", "01": "red"}),
    ("0x00 green, 0x01 red", {"00": "green", "01": "red"}),
    ("0x00 countdown stopped", {"00": "green", "01": "red"}),
    ("0x02/0x03 green countdown", {"23": "count"}),
    ("0x02/0x03 red", {"23": "red"}),
    ("0x02/0x03 stay red", {"23": "red"}),
    ("0x02/0x03 green", {"23": "green"}),
    ("0x02/0x03 countdown stopped", {"23": "green"}),
]
def live_lines(day):
    out = []
    for line in open(dec_of(day), encoding="utf-8"):
        m = re.match(r"\S+ (\d\d:\d\d:\d\d) \[(\w+)\] (.*)", line.rstrip("\r\n"))
        if m: out.append((ts(day, m[1]), m[2], m[3]))
    return out

def light_fn_live(day):
    cur = {"00": "green", "01": "red", "23": "green"}; ch = []
    for t, lvl, msg in live_lines(day):
        c = dict(cur)
        if msg.startswith("0x00 red for") and "0x01 stays red" in msg: c.update({"00": "red", "01": "red"})
        else:
            for p, upd in LIGHT_RULES:
                if msg.startswith(p): c.update(upd); break
        if "Smart control stopped" in msg or "Switching to the fixed" in msg: c = {"00": "off", "01": "off", "23": "off"}
        elif "Smart control started" in msg or "Back to smart" in msg: c = {"00": "green", "01": "red", "23": "green"}
        if c != cur: ch.append((t, c)); cur = c
    def state(t):
        s = {"00": "green", "01": "red", "23": "green"}
        for tc, c in ch:
            if tc <= t: s = c
            else: break
        return s
    return state

def light_fn_replay(tl):
    col = dict(tl)
    def state(t):
        c = col.get(int(t))
        if c is None: return {"00": "?", "01": "?", "23": "?"}
        return {"00": c[0][0], "01": c[1][0], "23": c[2][0]}
    return state

B1 = [("C", "B1"), ("D", "B1"), ("E", "B1")]
B2 = [("C", "B2"), ("D", "B2"), ("E", "B2")]
CL1 = [("C", "CL1"), ("D", "CL1")]

def safety(day, state):
    """Every analysis trip: lights when it really left.  Southbound: at its C/D Cross-Line-1
    and when it then reached C/D/E Box-1 while C/D/E Box-2 still showed it at the exit.
    Northbound: 0x00 red and 0x01 green/countdown at its A Cross-Line-2 (or A Box-1)."""
    ev, trips = analysis(day)
    by = by_zone(ev)
    box2 = sorted(t for k in B2 for t in by[k]); box1 = sorted(t for k in B1 for t in by[k])
    cl1 = sorted(t for k in CL1 for t in by[k])
    probs, n = [], {"S": 0, "N": 0}
    for tr in trips:
        f = tr["f"]
        if tr["dir"] == "S":
            te = f.get("C/D CL1")
            if te is None: continue
            n["S"] += 1
            last = te
            for t in box2:
                if last < t <= last + 2: last = t
            lines = [t for t in cl1 if te <= t <= last + 2]
            groups = []
            for t in lines:
                if groups and t - groups[-1][0] <= 3: groups[-1].append(t)
                else: groups.append([t])
            g0 = groups[-1][0]
            tb = next((t for t in box1 if t >= g0 - 1), None)
            if tb is not None and tb > max(last, g0) + 3: tb = None
            chk = [te] + ([tb] if tb else [g0 + 3])
            lt = [state(t)["23"] for t in chk]
            if any(x != "red" for x in lt):
                probs.append(("S", te, f"C/D Cross-Line-1 {clk(te)}, Box-2 until {clk(last)}, Box-1 "
                              f"{clk(tb) if tb else '-'}: 0x02/0x03 {' / '.join(lt)}"))
        else:
            te = f.get("A CL2") or f.get("A B1")
            if te is None: continue
            n["N"] += 1
            s = state(te)
            if not (s["00"] == "red" and s["01"] in ("green", "count")):
                tin = f.get("C/D CL2") or tr["t0"]
                probs.append(("N", te, f"in {clk(tin)} out {clk(te)} ({te - tin:.0f} s): 0x00 {s['00']}, 0x01 {s['01']}"))
    return n, probs
