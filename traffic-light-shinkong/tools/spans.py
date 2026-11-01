"""Zone activity (gaps <= 2 s merged) between two times: spans.py DAY HH:MM:SS HH:MM:SS"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
day, a, b = sys.argv[1:4]
t0, t1 = C.ts(day, a), C.ts(day, b)
ev, trips = C.analysis(day)
sp = collections.defaultdict(list)
for t, cam, z in ev:
    if t0 <= t <= t1:
        k = f"{cam} {z}"
        if sp[k] and t - sp[k][-1][1] <= 2: sp[k][-1][1] = t
        else: sp[k].append([t, t])
for k, ss in sorted(sp.items(), key=lambda x: x[1][0][0]):
    print(f"   {k:7s} " + ", ".join(f"{C.clk(s)[3:]}-{C.clk(e)[6:]}" if e > s else C.clk(s)[3:] for s, e in ss))
