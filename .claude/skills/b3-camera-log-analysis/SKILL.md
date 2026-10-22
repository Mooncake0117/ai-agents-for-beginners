---
name: b3-camera-log-analysis
description: Analyse the ShinKong B3 parking-lot IP-camera trigger logs (HTTP_Server.py output such as B3_log_*.txt, UTF-16 from PowerShell) - find every trip through the connecting lane between HuoShih and GuiLan, check hour by hour which camera boxes and cross-lines (IP-CAM-A to F) fired or missed, detect camera outages, attribute noisy zones, and measure per-stage detection rates and timing for tuning the smart traffic-light confidence weights. Use it whenever the user uploads or mentions a B3 log, asks how often a camera, box or line missed, whether detections are reliable, how long cars take between zones, wants a new log compared with earlier ones, or asks to re-run "the analysis" - even if they do not name this skill.
---

# B3 camera log analysis

The B3 project controls four traffic lights (0x00 HuoShih arterial, 0x01 lane exit
northbound, 0x02/0x03 GuiLan main lanes) from six AI cameras that POST messages like
`Box-1_triggered.` / `Cross-Line-2_triggered.` to an HTTP test server about 10 times a
second while a vehicle is in a zone. The user records them with
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
   gaps are normal; a gap while other cameras report trips is an outage.

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
