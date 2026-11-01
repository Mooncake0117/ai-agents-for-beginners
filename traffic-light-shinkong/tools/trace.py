"""Replay a day and print decisions (+ messages, + per-message attribution with -t) between two
times.  trace.py ENGINE_DIR DAY HH:MM:SS HH:MM:SS [-t] [-q]   (-q: no raw messages)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
d, day, a, b = sys.argv[1:5]
lo, hi = (C.ts(day, x) % 86400 for x in (a, b))
e, eng, lines, tl = C.replay(d, day, trace=(lo, hi))
prev = None
for t, l, m in lines:
    if not lo <= int(t) % 86400 <= hi: continue
    if l == "TRACE" and "-t" not in sys.argv: continue
    if l == "RX" and "-q" in sys.argv: continue
    s = f"{C.clk(t)} {l:5s} {m}"
    if s != prev: print(s)
    prev = s
