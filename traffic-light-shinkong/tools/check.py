"""Safety at every real exit: check.py live DAY... | check.py ENGINE_DIR DAY..."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
mode, days = sys.argv[1], sys.argv[2:] or C.DAYS
for day in days:
    if mode == "live": state = C.light_fn_live(day)
    else: state = C.light_fn_replay(C.replay(mode, day)[3])
    n, probs = C.safety(day, state)
    print(f"{day} {'live' if mode == 'live' else 'replay'}: {n['S']} southbound + {n['N']} northbound exits, {len(probs)} flagged")
    for d, t, s in probs: print(f"   {d} {s}")
