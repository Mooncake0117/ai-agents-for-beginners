# B3 log analysis: results history

One entry per analysed log, newest last. Compare a new log with these before reporting.
Hit rates are "hit (healthy)" from section 6 unless noted; S = southbound, N = northbound.

## B3_log_.txt: 2026-10-19 11:00-18:38 (run with --drop E:CL1 --drop E:CL2)

- Trips found by B: 80 S, 111 N (+2 passing, 2 unclear). Messages: 126,607.
- Cameras sent ~10 messages/s while a zone was occupied (lines ~10 per crossing).
- S stages 91-100%: A lines 99%, B CL1 100%, C/D CL1 99% (C CL1 81%, D CL1 only 20%).
- N stages: C/D CL2 99% healthy but **outage from 16:44 to the end** (C/D lines stopped
  16:14-17:08 after the vendor changed their settings around 16:30); B boxes/lines 99-100%;
  F CL2 98%, F CL1 41%.
- D CL1: 80% of its bursts unrelated to lane trips (burst storm 14:11-14:26) - misplaced.
- Timing (S): steps 0-3 s typical, 90th percentile <= 10 s, stops up to ~40-77 s at the
  GuiLan end; whole trip median 14 s. (N): steps 0-7 s, whole trip median 10 s; northbound
  cars wait at 0x01 red (dwell at B B0/B1 up to ~58 s).

## B3_log_1021.txt: 2026-10-21 16:35 to 2026-10-22 12:13 (current config, E lines included)

- Trips found by B: 123 S, 119 N (+3 passing, 4 unclear). Messages: 11,681.
- **Message rate changed**: lines now send exactly 1 message per crossing, boxes at most
  1 message per second while occupied (vendor alarm interval). Burst lengths unchanged.
- 10/21 ~16:35-17:45 looks like a setup period: outages of C/D CL2 (16:38-17:14),
  E CL2 (to 17:44), F/A (16:35-16:50). E CL1/CL2 appear in their new position from ~17:45.
- S: A lines 98%, B CL1 100%, C/D CL1 97% (C 93%, D 93% - D CL1 fixed), E CL1 77%,
  B B2 95%, C/D/E B2 100%, end C/D/E B1 97%.
- N: C/D CL2 99% healthy, E CL2 91% healthy (72% overall), B 97-100%, A B2|F CL 99%,
  A B1 100% healthy.
- All cross-lines now <= 4% unrelated (D CL1 3%, was 80%).
- **F CL1/CL2 are not direction-specific**: they fired in 64 of 123 southbound trips,
  2-3 s after A B1 (the southbound car turning in), besides 104 northbound bursts.
- B/C/D/E silent together 22:42-07:44 (no lane traffic at night); A/F kept seeing
  arterial traffic.
- Timing (S): whole trip median 13 s, 90th 29 s; (N): median 10 s, 90th 28 s.
- Re-run 2026-10-22 with the corrected route order and the scorecard (sections 10/11):
  E CL1 93% S, wrong direction 10%; E CL2 75% N (setup period included), 9%; A CL1 98%
  with 17% wrong direction, A CL2 98% with 10%; F CL1 83% / 25%, F CL2 79% / 17%;
  B, C, D lines 0-3% wrong direction.

## B3_log_1022.txt: 2026-10-22 12:14-14:23 (no camera changes since 10/21)

- Trips found by B: 49 S, 45 N (+3 passing, 2 unclear); 28 S / 31 N clean. Short log:
  one miss = 2%.
- S stages: F B0, A B1, A CL1|CL2, A B2, B CL1, B B2, C/D/E B2 100%; B B0 96%, B B1 98%,
  E CL1 96%, C/D CL1 98%, C/D/E B1 98%. Lines: A CL1 94% (23% wrong direction, firing
  +3..+8 s after the northbound car's B CL2, as it turns out at A B1), A CL2 98% (10%),
  B CL1 100% (0%), E CL1 96% (13%), C CL1 / D CL1 98% (3%).
- N stages: C/D CL2, C/D/E B2, B (all), A B2|F CL 100%, A B1 100%; C/D/E B1 96%,
  E CL2 98%. Lines: C/D CL2 100% (0%), B CL2 100% (0%), E CL2 98% (14%), F CL1 100%
  (18%), F CL2 100% (14%); F fires 3-6 s before B CL1 as southbound cars turn in.
- E lines: every wrong firing came within 1 s of the other E line (4/4 both ways), and
  they fire next to the C/D lines (E CL1 +4 s after B CL1, 1 s before C/D CL1; E CL2
  1-2 s after C/D CL2), not between B CL1 and B B2 as intended.
- Per-camera end boxes: C B1 47-57%, D B1 12-20%, E B1 41-47% (stage 96-98% combined).
- No-trip firings 0-2% on all lines after the "send once" setting (D CL1 2%).
- Advised: delete F's lines (keep F boxes); keep A CL2 southbound rather than reversing
  it, use B B0 -> A B2 -> A B1 as the northbound exit check; move A CL1 deeper into the
  lane; delete E's lines; shrink D B1 (and C/E B1); record a full day next.
