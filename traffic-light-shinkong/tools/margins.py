"""Seconds of red before every real exit (S: 0x02/0x03 at C/D Cross-Line-1, N: 0x00 at A
Cross-Line-2), engine A vs B: list trips where B gives less warning.  margins.py A B [DAY..]"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
a_dir, b_dir = sys.argv[1:3]
for day in sys.argv[3:] or C.DAYS:
    ev, trips = C.analysis(day)
    cols = []
    for d in (a_dir, b_dir):
        cols.append(dict(C.replay(d, day)[3]))
    worse = []
    for tr in trips:
        f = tr["f"]
        te = f.get("C/D CL1") if tr["dir"] == "S" else (f.get("A CL2") or f.get("A B1"))
        if te is None: continue
        addr = 2 if tr["dir"] == "S" else 0
        m = []
        for col in cols:
            k = 0
            while col.get(int(te) - 1 - k) and col[int(te) - 1 - k][addr][0] == "red" and k < 120: k += 1
            m.append(k)
        if m[1] < m[0] and m[1] < 10:
            worse.append(f"{tr['dir']} exit {C.clk(te)}: red {m[0]} s -> {m[1]} s before")
    print(f"{day}: {len(worse)} exits with less red before them")
    for w in worse: print("   ", w)
