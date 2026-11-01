"""Scenario tests: rules_test.py ENGINE_DIR [name-filter]"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
from datetime import datetime
e = C.engine(sys.argv[1])
flt = sys.argv[2] if len(sys.argv) > 2 else ""
wall = datetime(2026, 10, 30, 12, 0, 0)

def run(name, script, until, **settings):
    if flt not in name:
        return
    log = []
    st = C.pc_settings(e)
    for k, val in settings.items():
        setattr(st, k, val)
    eng = e.Engine(st, lambda m, l="INFO": log.append(f"{eng.now:6.2f} {l:5s} {m}"))
    for t in range(0, 3):
        eng.tick(float(t), wall)
    events = sorted(script)
    t = 3.0
    while t <= until:
        for ev in [x for x in events if x[0] <= t]:
            eng.message(*ev)
            events.remove(ev)
        out = eng.tick(t, wall)
        if out[0][0] == "green" and out[1][0] == "green":
            log.append(f"{t:6.2f} DANGER 0x00 and 0x01 green together")
        t += 0.5
    print(f"== {name}")
    for line in log:
        if " INFO " not in line:
            print("  ", line)

# (a) passing in the two-way part
S_trip = [(3.0, "F", "B0"), (3.6, "A", "B1"), (4.2, "A", "B2"), (4.6, "A", "CL1"), (5.0, "B", "B0"),
          (5.6, "B", "B1"), (6.4, "B", "CL1"), (6.6, "B", "B2"), (7.6, "B", "B2"), (8.0, "B", "B1"),
          (9.4, "C", "B2"), (10.6, "C", "CL1"), (10.8, "D", "CL1"), (11.4, "E", "B1")]
N_trip = [(4.0, "C", "B1"), (5.2, "C", "CL2"), (5.3, "D", "CL2"), (5.6, "D", "B2"), (6.8, "B", "B2"),
          (7.2, "B", "CL2"), (7.6, "B", "B1"), (8.6, "B", "B0"), (8.8, "A", "B2"), (10.0, "A", "B1"), (10.9, "A", "CL2")]
run("a S and N pass each other", S_trip + N_trip, 24)
# (b) southbound exits
run("b1 S: C/D/E Box-1 before C/D Cross-Line-1", [(3.0, "F", "B0"), (3.5, "A", "B1"), (4.0, "A", "B2"), (4.4, "A", "CL1"),
    (5.0, "B", "B1"), (5.5, "B", "CL1"), (6.0, "B", "B2"), (7.5, "C", "B2"), (8.5, "E", "B1"), (8.9, "C", "CL1")], 18)
run("b2 S: C/D Cross-Line-1, no C/D/E Box-1", [(3.0, "F", "B0"), (3.5, "A", "B1"), (4.0, "A", "B2"), (4.4, "A", "CL1"),
    (5.0, "B", "B1"), (5.5, "B", "CL1"), (6.0, "B", "B2"), (7.5, "C", "B2"), (8.9, "C", "CL1"), (9.0, "D", "CL1")], 20)
# (c) northbound exits
run("c1 N: A Cross-Line-2 before A Box-1", [(3.0, "C", "CL2"), (4.0, "B", "B2"), (4.5, "B", "CL2"), (5.0, "B", "B1"),
    (5.5, "B", "B0"), (6.0, "A", "B2"), (6.6, "A", "CL2"), (7.2, "A", "B1")], 16)
run("c2 N: A Cross-Line-2 missed", [(3.0, "C", "CL2"), (4.0, "B", "B2"), (4.5, "B", "CL2"), (5.0, "B", "B1"),
    (5.5, "B", "B0"), (6.0, "A", "B2"), (7.0, "A", "B1"), (7.5, "A", "B2"), (8.0, "A", "B1")], 20)
# (d) convoy: second camera's copy of car 1's crossing while car 2 is at B Box-2
c1 = [(3.0, "F", "B0"), (3.5, "A", "B1"), (4.0, "A", "B2"), (4.4, "A", "CL1"), (5.0, "B", "B1"), (5.5, "B", "CL1"),
      (6.0, "B", "B2"), (7.0, "C", "B2"), (8.0, "C", "B1"), (9.0, "D", "CL1"), (9.4, "C", "CL1")]
c2 = [(6.0, "F", "B0"), (6.5, "A", "B1"), (7.0, "A", "B2"), (7.4, "A", "CL1"), (7.8, "B", "B1"), (8.4, "B", "CL1"),
      (8.9, "B", "B2"), (9.5, "B", "B2"), (10.2, "B", "B2"), (11.2, "D", "B2"), (12.2, "D", "B1"), (12.6, "C", "CL1")]
run("d convoy, car 2 at B Box-2", c1 + c2, 24)
# (e) stray A Cross-Line-2 while a southbound car drives in
run("e S: stray A Cross-Line-2 during the countdown", [(3.0, "F", "B0"), (3.5, "A", "B1"), (4.0, "A", "CL2"),
    (4.5, "A", "B2"), (5.0, "A", "CL1"), (5.5, "B", "B0"), (6.0, "B", "B1"), (6.5, "B", "CL1"), (7.0, "B", "B2"),
    (8.0, "C", "B2"), (9.0, "C", "CL1"), (9.5, "E", "B1")], 18)
# (j) 10/24 16:13: waits at B Box-1, rear in A Box-2, reverses out
m = [(3.0, "F", "B0"), (3.5, "A", "B1"), (4.0, "A", "B2"), (4.5, "A", "CL1"), (5.0, "B", "B0"), (5.5, "B", "B1")]
m += [(6.0 + k, "B", "B1") for k in range(0, 14, 2)] + [(15.0 + k, "A", "B2") for k in range(0, 6)]
m += [(20.2, "A", "B1"), (20.3, "A", "CL1"), (21.0, "A", "CL2"), (21.2, "A", "B1"), (22.5, "F", "B0"), (24.0, "F", "B1")]
run("j S: 16:13 pattern, reverses out (backing_stop On)", m, 40)
n = [(21.5, "E", "B1"), (22.0, "C", "CL2"), (22.1, "D", "CL2"), (22.5, "D", "B2"), (24.0, "B", "B2"),
     (24.5, "B", "CL2"), (25.0, "B", "B1"), (26.5, "B", "B0"), (27.0, "A", "B2"), (27.5, "A", "CL2"), (28.0, "A", "B1")]
run("k S backs out at HuoShih while a northbound car comes in", m + n, 45)
# (l) 10/27 10:04: F Box-1, A Box-2 just before A Box-1, lines missed
p = [(3.0, "F", "B0"), (4.0, "F", "B0"), (5.0, "F", "B0"), (6.0, "F", "B1"), (7.0, "F", "B1"),
     (8.0, "A", "B2"), (8.05, "A", "B1"), (10.0, "B", "B1"), (10.05, "B", "B2"), (11.0, "B", "B2"),
     (13.0, "E", "B2"), (13.05, "D", "B2"), (14.0, "C", "CL1"), (15.0, "E", "B2"), (16.0, "E", "B1")]
run("l S: 10/27 10:04 pattern", p, 28)
# (m) 10/27 18:36: N car 1 stands at A Box-1; N car 2 waits at B Box-1/B Box-2
q = [(3.0, "C", "CL2"), (4.0, "B", "B2"), (4.5, "B", "CL2"), (5.0, "B", "B1"), (5.5, "B", "B0"),
     (6.0, "A", "B2"), (6.5, "A", "B1"), (7.0, "A", "CL2")] + [(8.0 + 1.5 * k, "A", "B1") for k in range(13)]
q += [(7.0, "C", "CL2"), (9.0, "B", "B2"), (11.0, "B", "B2"), (13.0, "B", "CL2"), (13.0, "B", "B1")]
q += [(14.0 + 1.5 * k, "B", "B1") for k in range(27)] + [(14.2 + 1.5 * k, "B", "B2") for k in range(27)]
q += [(55.0, "B", "B0"), (56.0, "A", "B2"), (57.0, "A", "B1"), (58.0, "A", "CL2")]
run("m N: 10/27 18:36 pattern", q, 70)
# (n) N car stands at A Box-1 after leaving; a southbound car turns in behind it
r = [(3.0, "C", "CL2"), (4.0, "B", "B2"), (4.5, "B", "CL2"), (5.0, "B", "B1"), (5.5, "B", "B0"),
     (6.0, "A", "B2"), (6.5, "A", "B1"), (7.0, "A", "CL2")] + [(8.0 + 1.5 * k, "A", "B1") for k in range(9)]
s2 = [(21.0, "A", "B1"), (21.5, "A", "B1"), (22.0, "A", "B2"), (22.5, "A", "CL1"), (23.0, "B", "B0"),
      (23.5, "B", "B1"), (24.5, "B", "CL1"), (25.0, "B", "B2"), (26.5, "C", "B2"), (27.5, "C", "CL1"), (28.0, "E", "B1")]
run("n1 N stands at A Box-1, S turns in (F Box-0 seen)", r + [(19.0, "F", "B0"), (20.0, "F", "B0")] + s2, 40)
run("n2 N stands at A Box-1, S turns in (F Box-0 missed)", r + s2, 40)
# (p) 10/28 12:40: S car stands 60 s over B Box-1/B Box-2, then backs out
p2 = [(3.0, "F", "B0"), (3.5, "A", "B1"), (4.0, "A", "B2"), (4.5, "A", "CL1"), (5.0, "B", "B0"), (6.0, "B", "B1")]
p2 += [(7.0 + 1.5 * k, "B", "B1") for k in range(42)] + [(7.2 + 1.5 * k, "B", "B2") for k in range(42)]
p2 += [(70.5, "B", "B0"), (71.0, "A", "B2"), (72.0, "B", "B0"), (73.0, "A", "B2"), (73.1, "A", "B1")]
p2 += [(75.0 + 2 * k, "A", "B2") for k in range(5)] + [(75.1 + 2 * k, "A", "B1") for k in range(5)]
p2 += [(83.0, "A", "CL2"), (84.0, "A", "B1"), (86.0, "F", "B2")]
run("p S: 10/28 12:40 pattern, stood 60 s then backs out", p2, 95)

# ---- new rules (11/01)
into = [(3.0, "F", "B0"), (3.5, "A", "B1"), (4.0, "A", "B2"), (4.4, "A", "CL1"), (5.0, "B", "B1"), (5.5, "B", "CL1"),
        (6.0, "B", "B2")]
# A-(1): stands at C/D/E Box-2 15 s, then crosses and drives away
w1 = into + [(7.0 + k, "E", "B2") for k in range(15)] + [(22.0, "C", "CL1"), (22.3, "D", "CL1"), (22.6, "E", "B1")]
run("A1 S stands 15 s at C/D/E Box-2: not ended until it has gone", w1, 35)
# A-(2): crosses, stands 10 s on Box-1
w2 = into + [(7.0, "E", "B2"), (8.0, "C", "CL1"), (8.2, "D", "CL1")] + [(8.5 + k, "E", "B1") for k in range(10)]
run("A2 S crosses and stands 10 s on C/D/E Box-1: ended after 3 s without movement", w2, 25)
# A-(3): on Box-1 but C/D Cross-Line-1 never fired
w3 = into + [(7.0, "E", "B2"), (8.0, "E", "B1"), (9.0, "E", "B1")]
run("A3 S on C/D/E Box-1, Cross-Line-1 missed: waits for the line", w3, 40)
# A-(4): reaches Box-1, rolls back to Box-2 (no Cross-Line-2), stands there, then goes out
w4 = into + [(7.0, "E", "B2"), (8.0, "C", "CL1"), (8.2, "D", "CL1"), (8.5, "E", "B1"), (9.5, "E", "B1")]
w4 += [(10.5 + k, "E", "B2") for k in range(8)] + [(18.5, "E", "B1"), (19.5, "E", "B1")]
run("A4 S rolls back from Box-1 to Box-2 (no line): kept, ends after it goes out", w4, 32)
# A-(5): rolls back over C/D Cross-Line-2, then goes out again: the possible northbound car is dropped
w5 = into + [(7.0, "E", "B2"), (8.0, "C", "CL1"), (8.2, "D", "CL1"), (8.5, "E", "B1"), (9.5, "E", "B1"),
             (10.0, "C", "CL2"), (10.2, "D", "CL2")] + [(10.5 + k, "E", "B2") for k in range(5)]
w5 += [(15.5, "C", "CL1"), (15.7, "D", "CL1"), (16.0, "E", "B1"), (17.0, "E", "B1")]
run("A5 S rolls back over Cross-Line-2, out again: possible northbound car dropped", w5, 35)
# B: a real northbound car comes in beside the leaving southbound car
w6 = into + [(7.0, "E", "B2"), (8.0, "C", "CL1"), (8.2, "D", "CL1"), (8.5, "E", "B1"), (9.5, "E", "B1"),
             (10.0, "C", "CL2"), (10.2, "D", "CL2"), (10.5, "D", "B2"), (11.5, "B", "B2"), (12.0, "B", "CL2"),
             (12.5, "B", "B1"), (13.5, "B", "B0"), (14.0, "A", "B2"), (14.5, "A", "B1"), (15.0, "A", "CL2")]
run("B1 northbound car comes in beside the leaving southbound car: confirmed", w6, 30)
# B: two southbound cars 1 s apart at the exit; C reports car 1, D reports car 2
t1 = [(3.0, "F", "B0"), (3.5, "A", "B1"), (4.0, "A", "B2"), (4.4, "A", "CL1"), (5.0, "B", "B1"), (5.5, "B", "CL1"),
      (6.0, "B", "B2"), (7.0, "C", "B2"), (8.0, "C", "CL1"), (8.0, "E", "B1")]
t2 = [(5.0, "F", "B0"), (5.5, "A", "B1"), (6.0, "A", "B2"), (6.4, "A", "CL1"), (6.8, "B", "B1"), (7.2, "B", "CL1"),
      (7.6, "B", "B2"), (8.5, "E", "B2"), (8.6, "D", "B2"), (9.0, "D", "CL1"), (10.0, "D", "B1")]
run("B2 two southbound cars 1 s apart: each keeps its own crossing", t1 + t2, 25)
# 3: HuoShih mouth one car wide
hm = [(3.0, "C", "CL2"), (4.0, "B", "B2"), (4.5, "B", "CL2"), (5.0, "B", "B1"), (5.5, "B", "B0"),
      (6.0, "A", "B2"), (6.5, "A", "B1"), (7.0, "A", "CL1"), (7.5, "A", "B1"), (8.0, "A", "CL2")]
run("H1 N leaves, A Cross-Line-1 misfires: no southbound car", hm, 20)
rp = [(3.0, "F", "B0"), (3.5, "A", "B1"), (4.0, "A", "B2"), (4.5, "A", "CL1")] + \
     [(5.0 + k, "A", "B2") for k in range(5)] + [(5.1 + k, "A", "B1") for k in range(5)] + \
     [(9.5, "A", "CL1"), (10.0, "B", "B0"), (10.5, "B", "B1"), (11.0, "B", "CL1"), (11.5, "B", "B2"),
      (13.0, "C", "B2"), (14.0, "C", "CL1"), (14.5, "E", "B1")]
run("H2 S stands in the mouth, A Cross-Line-1 fires again: one car", rp, 25)
