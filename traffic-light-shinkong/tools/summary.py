"""Per day, old vs new engine: red seconds, cars, possible cars, stops, one-message-two-cars.
summary.py OLD_DIR NEW_DIR [DAY...]"""
import sys, os, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
old, new = sys.argv[1:3]
days = sys.argv[3:] or C.DAYS
def stats(d, day):
    e, eng, lines, tl = C.replay(d, day)
    r23 = sum(1 for x in tl if x[1][2][0] == "red"); r00 = sum(1 for x in tl if x[1][0][0] == "red")
    ev = [m for t, l, m in lines if l in ("EVENT", "WARN")]
    cars = collections.Counter()
    for m in ev:
        mm = re.match(r"(\w+) car #\d+ (in the lane|possibly in the lane|leaving at GuiLan, but no camera)", m)
        if mm: cars[mm[1][0] + (" possible" if "possibly" in m else " unseen" if "no camera" in m else "")] += 1
    poss = collections.Counter("confirmed" if "confirmed" in m else "dropped" for m in ev
                               if "a northbound car after all" in m or "rolling back at the GuiLan exit" in m)
    stops = collections.Counter(re.search(r"backing out at (\w+)", m)[1] for m in ev if re.search(r"backing out at \w+ \(.*\): 0x", m))
    lost = sum(1 for m in ev if "cancelled: lost" in m)
    return r23, r00, cars, poss, stops, lost
for day in days:
    a, b = stats(old, day), stats(new, day)
    print(f"== {day}")
    print(f"   0x02/0x03 red {a[0]} -> {b[0]} s ({b[0]-a[0]:+d}), 0x00 red {a[1]} -> {b[1]} s ({b[1]-a[1]:+d})")
    print(f"   cars old {dict(a[2])}  new {dict(b[2])}")
    print(f"   possible northbound cars (new): {dict(b[3])}; arterial stops old {dict(a[4])} new {dict(b[4])}; 'lost' old {a[5]} new {b[5]}")
