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
- **Correction (10/23, matcher fix: convoys split into one trip per car, each stage
  matched once per car, line crossings not shared between cars)**: 50 S / 46 N trips;
  A CL1 100% (not 94%) with 22% wrong direction, A CL2 100% with 9%; C CL1 / D CL1 100%
  with 0% wrong; B B0 S 94% (misses 13:35:23, 13:44:59, 14:12:41). Same re-run of
  10/21-22 (without E/F lines): 130 S / 124 N; A CL1 98% (12% wrong), A CL2 98% (5%),
  C CL1 97%, D CL1 98%; Box-1 per camera S/N: C 52/40%, D 14/20%, E 57/60%.

## B3_log_22-23.txt: 2026-10-22 21:56 to 2026-10-23 11:47 (after the 10/22 ~21:00 changes)

- Changes: F and E cross-lines deleted, C Box-1 and D Box-1 shrunk, A CL1 moved half a
  car length toward the lane (just past A CL2).
- Only 22 S / 12 N trips (one miss = 4.5% / 8.3%): far less traffic than 10/22 (08:00
  hour: 5 trips vs 39) on every camera incl. A/F arterial boxes; B/C/D/E silent
  22:13-07:53 and 08:36-09:41 with no A turn-ins either, so an empty lane, not an outage.
- Every stage 100% except C/D/E B1: S 95% (miss 10-23 11:28:33: C B2 and C/D CL1 fired,
  no Box-1 at all), N 92% (miss 10-22 22:12:51: trip started at C/D CL2).
- Box-1 per camera after shrinking, S/N: C 32/33% (was 60/41), D 27/25% (was 10/24),
  E 41/33%; the three now barely overlap (sum ~100%), so a car between them is missed.
- A CL1 at its new place: 22/22 hit, 0/12 wrong direction (22% on 10/22; 0 of 12 has
  ~5% chance if nothing had changed). A CL2: 22/22, 1/12 wrong (+4 s after B CL2).
- All other lines 100% hit, 0% wrong direction, 0% no-trip firings.
- Timing: S whole route median 11 s (90th 20 s), N 8 s (90th 9 s).

## B3_log_1023.txt: 2026-10-23 11:54-21:38 (same setup as 22-23; chain window now 30 s)

- 22 S / 34 N trips (traffic about a quarter of 10/22). Two northbound cars stopped ~20 s
  (14:18:36 between C/D B2 and B B2 with no zone firing; 18:54:13 on B CL2 in B B2), so
  the chain window was raised from 20 to 30 s; with it every N stage is 100%.
- S: B B0 95% (13:55:03, fast car, A B2 caught it), C/D/E B1 95% (12:48:10); rest 100%.
- A CL1 22/22 hit, fired for 2 of 34 northbound cars (15:41:33, 18:54:39, both together
  with A CL2 while the car swung onto the arterial at A B1). A CL2 22/22 hit, 6/29 (21%)
  wrong direction at +2..+4 s.
- Box-1 per camera S/N: C 9/26%, D 14/21%, E 86/74%.
- C B0 last message 15:41, D B0 15:01 (and only 1-13/h before, vs up to 135/h on
  10/22) while E B0 and C/D lines kept working: check C/D Box-0 (they set x1/x2).
- Combined 22-23 + 1023 (44 S / 46 N since the 10/22 ~21:00 changes): every stage >= 98%;
  A CL1 100% hit, 2% wrong (clean trips); A CL2 17% wrong.
- A B2 vs B B0 over 440 trips (10/21-10/23): never both missed; S A B2 224/224, B B0
  217/224; N B B0 216/216, A B2 207/216 (all 9 during camera A set-up 10/21 16:35-16:50).
- Advised: reverse A CL2 (exit check, A CL1 alone covers southbound), keep A B2 and B B0
  as one zone, check C/D Box-0; the user agreed Box-1 is optional (end S on C/D CL1 + y s,
  start N at Box-1 or C/D CL2).

## B3_log_23-24.txt: 2026-10-23 22:04 to 2026-10-24 01:28 (quiet hours, before A CL2 reversal)

- 3 S / 3 N trips. All stages fired except B B0 for one fast southbound car (22:56:55;
  A B2 caught it; B B0 has now missed 8 of 227 southbound cars, A B2 none).
- 22:26:04: a car came from F B0, nosed into the mouth (A B1 + A B2 repeating for 9 s,
  no A CL1, no B), went back to F B0 and on to A B0: a real turn-in-and-back-out.
- 23:03:19-39: a northbound car waited ~20 s in E B0/E B1 before entering (C/D CL2).
- C/D Box-0 checked by the user on site: working (10/23 evening was just quiet).
- A CL2 reversed 10/24 03:13; config.json updated, old setup kept in
  config-until-2026-10-24-0313.json.

## B3_log_1024.txt: 2026-10-24 06:20-15:08 (A CL2 reversed since 03:13)

- 47 S / 38 N trips. Every northbound stage 100%; reversed A CL2 38/38 hit, 1/40 wrong
  direction (was 21% before the reversal). C/D CL2 2/40 wrong direction (+17 s).
- S: B B0 94% (09:09:53, 09:22:10, 10:40:22; A B2 caught all three), B B1 and B B2 98%
  (09:13:00), C/D/E B1 98% (08:10:18); every other stage 100%. A CL1 2% no-trip firings.
- Box-1 per camera S/N: C 36/42%, D 11/13%, E 74/66%. C/D/E B2 for S: C 98%, D 68%, E 45%.
- Northbound blind spot between C/D/E B2 and B B2: one car unseen for 30 s (11:07:42).

## B3_log_24-25.txt: 2026-10-24 15:11 to 2026-10-25 18:21 (B Box-2 widened by the user)

- 44 S / 54 N trips. One southbound car missed by A CL1, A B2, B B0 and B B1 at once
  (10-25 08:26:51; F B0, A B1 and B CL1 saw it); single misses: A B1 11:21:49, B B2
  11:23:24, C/D CL1 11:13:53 (C and D both). Every other S stage 100%.
- N: B B0, A CL2 96% (10-24 19:21:36 when a car stood 40+ s at B B1/B B2 under the V22
  red, and 22:38:25); A B2, A B1 98%. A CL2 4/39 (10%) wrong direction at -5..-3 s.
- Box-1 per camera S/N: C 25/28%, D 25/26%, E 93/81%.
- Blind spot after widening B Box-2: max 19 s (11:43:45; 21:30:32 16 s, 17:45:28 14 s),
  vs 30 s on 10/24 and 21 s on 10/23. Cars still stop where neither C/D/E B2 nor B B2
  sees them, but under the controller's 25 s fade no car is lost.
- All six cameras silent 10-25 06:41-07:48 (Sunday morning, no traffic).
- Smart engine replay (10/24 and 24-25): every trip found, 0 unsafe once the second
  GuiLan camera's report of one C/D CL1 crossing goes to the car that has just crossed.

## B3_log_1025.txt: 2026-10-25 18:45-23:25 (Sunday evening, same setup)

- 5 S / 7 N trips, all clean: every stage 100% both ways, no wrong-direction or no-trip
  line firings. Box-1 per camera S/N: C 40/14%, D 20/29%, E 100/100%.
- D B0 sent nothing all evening (C B0 11, E B0 21 messages); D B0 has been sporadic
  since 10/24 afternoon, so watch it (C/D Box-0 only choose the 3 s / 2 s countdown).
- All cameras silent 20:58-21:29 (31 min); B-E 20:51-22:40 while A/F kept reporting.
- Smart engine replay: every trip found, 0 unsafe; 3 one-message A B1 clips right after
  F B0 started a 2 s countdown each (cars passing on the HuoShih arterial).
- Silence alarm now 60 min, quiet hours 23:00-08:00.
