---
name: b3-camera-log-analysis
description: Analyse the ShinKong B3 parking-lot IP-camera trigger logs (HTTP_Server.py output such as B3_log_*.txt, UTF-16 from PowerShell) - find every trip through the connecting lane between HuoShih and GuiLan, check hour by hour which camera boxes and cross-lines (IP-CAM-A to F) fired or missed, detect camera outages, attribute noisy zones, and measure per-stage detection rates and timing for tuning the smart traffic-light confidence weights, score every detection against the 98% target and advise which boxes or lines to move, delete or redirect. Use it whenever the user uploads or mentions a B3 log, asks how often a camera, box or line missed, whether detections are reliable, how long cars take between zones, wants a new log compared with earlier ones, or asks to re-run "the analysis" - even if they do not name this skill.
---

# B3 camera log analysis

The B3 project controls four traffic lights (0x00 HuoShih arterial, 0x01 lane exit
northbound, 0x02/0x03 GuiLan main lanes) from six AI cameras that POST messages like
`Box-1_triggered.` / `Cross-Line-2_triggered.` to an HTTP test server (since 10/21: one
message per line crossing, at most one per second while a box is occupied; before that
about 10 per second). The user records them with
`uv run python -u HTTP_Server.py > B3_log.txt 2>&1` and uploads the file. This skill
turns such a log into the numbers that decide the smart controller's design: which
detections can be trusted, which fail, and how long each step of a trip takes.

## Run it

Uploads are large (30 MB, hundreds of thousands of lines), so never read them into the
conversation. Copy each upload into its own scratchpad folder and run the bundled script
on it; it decodes UTF-16/UTF-8 itself and finishes in seconds:

```bash
mkdir -p <scratchpad>/logs && cp "<uploaded log>" <scratchpad>/logs/
python .claude/skills/b3-camera-log-analysis/scripts/analyze_b3_log.py \
    <scratchpad>/logs/B3_log_1021.txt --json <scratchpad>/logs/B3_log_1021.json \
    > <scratchpad>/logs/B3_log_1021.md
```

- Several logs can be given at once; they are merged in time order. Multi-day logs work.
- **Match the routes to the camera setup at recording time.** `config.json` describes
  the current setup and its `config_history` lists every change with its date. For a
  log recorded before a change, leave the zones that did not exist yet out with
  `--drop CAM:ZONE` (repeatable), e.g. `--drop E:CL1 --drop E:CL2` for logs before
  IP-CAM-E's lines were moved next to the lane. Otherwise a zone that sat elsewhere
  looks like a broken detector, and can steal matches from its neighbours.
- When a change moves a zone between directions (10/24 03:13: A Cross-Line-2 reversed
  into a northbound exit check), save the old setup as `config-until-<date>.json` and
  analyse logs from before the change with `--config` pointing at it.
  `config-until-2026-10-24-0313.json` covers 10/22 ~21:00 to 10/24 03:13.
- If the user describes a new camera change, update `config.json` (stage order or
  alternatives) and add a dated `config_history` line. The script itself should not
  need edits for configuration changes.

Then read the Markdown report (it is a few hundred lines) and answer from it.

## What the report contains and how to read it

1. **Input summary**: messages per camera and zone, IPs, last message per zone. A zone
   whose last message is hours before the end of the log stopped working.
2. **Trips**: passages through the connecting lane found by the reference camera
   IP-CAM-B (its messages grouped into episodes). Direction comes from B's
   direction-specific lines (CL1 southbound, CL2 northbound), else from box order.
   "Both lines fired" means two cars passing each other; those and unclear ones are
   listed but kept out of the statistics. Trips B missed completely are invisible here;
   section 8 shows them indirectly as unrelated bursts of A/C/D/F lines.
3. **Hourly volume**: trips and messages per camera per hour. A camera whose volume
   collapses while trips continue is degrading (10/19 after 17:00: C and D).
4. **Hourly cross-line messages** per camera line.
5. **Hourly line hits per trip**: for each trip, did each camera's line fire
   (`hits/trips`), plus `miss` = no alternative of that stage fired.
6. **Stage reliability**: hit rate over all trips; *outages* = the stage missed
   `outage_streak` (3) trips in a row, which is the same rule the live controller will
   use to flag a suspect camera; *healthy* hit rate excludes outage trips; *per camera*
   splits a stage with alternatives (e.g. C/D CL1) so a weak or misplaced camera shows
   up (10/19: D CL1 fired for only ~10-20% of southbound exits).
7. **Route detection and timing per anchor**: the route chain is re-run anchored on
   every stage that is detected in at least `anchor_min_rate_pct` of trips. `trips` per
   column = trips in which that anchor itself was seen, so it differs between anchors;
   the detection percentages should be stable across columns (if one column disagrees,
   that anchor is unreliable). The timing table (primary anchor) gives median / 90th
   percentile / max seconds from the previous detected stage, and dwell time in each
   zone. These feed the confidence fade: the 90th percentile is the "no progress yet"
   grace time, the maximum shows real stops.
8. **Zone attribution**: every burst of every zone is classified as inside a
   southbound trip, a northbound trip, both, an unclear trip, or unrelated. High
   unrelated % is expected for zones that watch general traffic (A B0, F B0/B1, C/D B0);
   for a cross-line it means the line is misplaced or catches other traffic (10/19:
   D CL1 80% unrelated). Two-way zones (A B1, A B2, B boxes, C/D/E B2) show how often a
   detection belongs to each direction, which is why order matters in the controller.
9. **Camera silences**: gaps of `silence_report_min`+ minutes per camera. Night-time
   gaps are normal (hospital car park: almost no lane traffic 23:00-07:00, while A/F
   still see arterial traffic); a gap while other cameras report trips is an outage.
10. **Detection scorecard** against `target_pct` (98%), the user's acceptance bar before
    the event/confidence engine is written. Per stage: *hit, route order* (decides the
    status), *hit, clean trips* (trips with no other lane trip within `clean_window_s`,
    stage counted if it fired anywhere near; much higher than the route-order rate means
    the zone fires but not where the route says), *wrong direction* (a direction-specific
    line fired while a clean opposite-direction car was in front of that camera, flagged
    from 2 occurrences), *no trip* (section 8 unrelated share), a status and the times
    of every missed trip, so the user can check the camera recording. Below each
    direction, every cross-line on its own, with *when* the wrong firings happen
    (seconds from the opposite car's B anchor) and *with other line* (wrong firings
    within 1 s of another line of the same camera, i.e. one car set off both lines).
11. **Placement and order check**: on clean trips, median and 10-90% entry time of
    every zone relative to the anchor, and the order the zones really fire in. A zone
    out of the configured order by more than `order_tolerance_s` is flagged: either the
    route in `config.json` is wrong (fix it there) or the zone is not where the user
    thinks it is (tell them where it really fires, e.g. "E CL1 fires 4 s after B CL1,
    together with C/D/E B2, not between B CL1 and B B2").

## How the matching works (so you can explain or adjust it)

- Text lines and request lines come from different output streams and are interleaved
  out of order, but each request writes one of each, so the n-th text pairs with the
  n-th request line. The script warns if the counts differ.
- Timestamps have 1 s resolution, so order within a second is unknown.
- For each trip, every burst of every stage near the anchor is a candidate. A dynamic
  programme picks the chain that matches the most stages in route order, where the next
  stage must still be active when the previous one started (`order_tolerance_s`) and
  start within `chain_window_s` after the previous burst ended. Stages may be skipped,
  so one stray trigger cannot derail the rest of the trip.
- A burst that began before the car could have arrived (another car was already in the
  zone) counts as a detection but is marked shared and excluded from timing.
- Cars following each other through B without a 3 s gap form one B episode; it is
  split into one trip per crossing of B's reference line (one message per car since
  10/21). Cars are then matched in time order and a cross-line burst used by one car is
  not offered to the next (cars cannot overtake in the lane), so a convoy cannot hide a
  miss by sharing the car in front's crossing. Boxes may still be shared.
- Before 10/23 the matcher could count one stage twice (e.g. this car's B B2 and the
  next car's), which pulled a convoy car's chain onto the following car: per-line rates
  reported before then (10/22: "A CL1 94%") were too low; re-run old logs if comparing.
- All thresholds are in `config.json` → `params`.

## Reporting back

Lead with the answer to the user's question. Then give, per direction, a compact table of
stage hit rates (all trips and healthy), name every outage with its time span, and call
out misplaced or noisy zones and anything that changed since earlier logs (compare with
`references/results-history.md`). Mention the caveats that matter for the conclusion
(trips B missed, logs from before a camera change). Keep the user's own camera names
(A Box-1, C Cross-Line-2, ...) rather than the script's short forms when writing prose.

After each analysis, append a short dated summary of the key numbers to
`references/results-history.md`, so the next log can be compared against it.

## Advising on camera settings

The user wants concrete, per-zone advice after every log ("move E Cross-Line-1 closer to
B Cross-Line-1", "delete F's lines"), aimed at every stage reaching 98%. Give a short
numbered list of changes for the next recording, each with the number that motivates it
and what the next log should show if it worked. Collision avoidance is the top priority:
a zone that adds no information the engine needs but adds false firings should be
removed, not tuned forever. Heuristics that the logs so far support:

- **Wrong direction has two causes.** Lines where cars drive straight (B, C, D) have
  0-3% wrong-direction firings. Far from the camera the bounding box jitters (F's lines,
  set at long focal distance, deleted 10/22). Close to the camera, a car swinging
  through a turn moves its box sideways: A's lines fire for 2-21% of northbound cars as
  they swing onto the arterial in A Box-1 (+2..+4 s after B CL2), and E's lines at the
  GuiLan mouth did the same. Ask the user where in the picture the swing happens before
  advising a move; typical fixes are moving the line to where the turn is finished, or
  ending it short of the swing, across the lane width only and perpendicular to travel.
  Do not assume two cameras' lines behave alike; the user knows the views. *With other
  line* near 100% means the camera's two lines are crossed by one car at once: they sit
  too close together or in the turn, so separate them by at least a car length or drop
  one.
- **Lines judge movement, not which way a car faces.** A car reversing out of the lane
  fires the line set for the opposite direction, exactly like a car driving out. The
  analysis cannot tell them apart; the live controller does it by where each car is.
- **Two cameras on one spot.** A Box-2 and B Box-0 cover the same place (entries within
  0-2 s). Over 440 trips (10/21-10/23) they never missed together: B Box-0 misses fast
  southbound cars, A Box-2 was lost only while camera A was being set up. Treat them as
  one zone with two sensors rather than deleting one.
- **Redundancy before reversal.** A stage with alternatives (A CL1|CL2, C/D CL1) reaches
  98% because the alternatives back each other up; repurposing one of them can push the
  stage below target. Check the remaining line's own hit rate in the per-line table.
- **Box misses**: a box triggers only when a vehicle covers more than 50% of its area, so
  a box much bigger than a car, or one that cars only clip at its edge, fires rarely
  (D B1 12-26%). Advise shrinking it to about one car on the path cars actually take.
  Boxes where cars pass quickly miss more than boxes where they stop. Boxes that are
  alternatives of one stage (C/D/E Box-1) each watch a different exit path, so judge the
  stage, not each box: if the per-camera rates add up to about 100% they no longer
  overlap, and shrinking one opens a gap where a car is missed (10/23 after C/D Box-1
  were shrunk). Check the video at a stage miss to see which path the car took.
- **No-trip firings** above 2% mean the zone catches other traffic or triggers on its
  own (ghost triggers on B CL2 / D CL1 stopped once lines were set to send once).
- **Out-of-order zones**: if section 11 shows a zone firing far from where the user's
  sequence puts it, say where it really is relative to its neighbours before advising
  a move; fix `config.json` so the matching follows reality.
- **Small samples**: one miss in 50 trips is 2%. Judge the 98% target only on at least
  ~100 trips per direction (a full day); say so when a log is shorter.
- When the user reports a change (zone deleted, moved, reversed), update `config.json`
  (stages, alternatives) and add a dated `config_history` line before analysing logs
  recorded after it; use `--drop` for older logs.
