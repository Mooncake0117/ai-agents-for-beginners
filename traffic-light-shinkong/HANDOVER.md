# ShinKong B3 smart traffic light: handover (as of 2026-11-01)

This file carries everything agreed in the first Claude account's sessions (10/19 to 11/01),
so the work can continue in another account. **Claude: read this whole file first, then
`smart_B3_engine.py`, then `.claude/skills/b3-camera-log-analysis/SKILL.md` and
`references/results-history.md`, before you answer the user.**

Branch with the latest work: `claude/traffic-light-cycle-refactor-4isbz8`.

---

## 1. The user's working rules (binding, in the user's own words)

1. **Since 11/26 (replaces the old "ask before any fix" rules):** "From now on, for this
   Traffic light smart control project, I will let you decide if a new rule/code build is
   necessary or not ... if you feel this change/modify is necessary, then build the code, I
   will update to the B3's PC, after then I will update the daily log, let's see how it
   works." "If you need my help/clarification, use Bold, Big font to let me know!"
2. "If adding a new rule or modifying the code to address a single specific case ends up
   negatively impacting other scenarios, then such a change might not be necessary."
3. "Your response should continue our previous discussion first before starting the new
   log analysis. For the new log analysis, discuss each False/Alarm item based on the time
   the event occurred; avoid repeating points that have already been mentioned."
4. "You can send me the updates of .py file once the changes are verified."
5. "Don't make any work-around for this kind of IP-CAM's bug (Cross-Line misfired)."

How the user likes to work:
- Short, direct answers and simple commands (PowerShell on the B3-PC).
- Judge each decision by what the program could know **at that moment**, not with
  hindsight from later messages. Where two explanations are physically possible, keep both
  until later messages decide (the user's "keep both possibilities").
- Use the user's own names: A Box-1, C Cross-Line-2, C/D/E Box-2, 0x00, 0x02/0x03, ...
- The user checks facts on site. When they say a message was a misfire, it was a misfire.
- Verify every change by replaying all logs before sending a file (section 9).

## 2. Site and hardware

| Item | Detail |
|---|---|
| Light 0x00 | HuoShih arterial |
| Light 0x01 | Lane exit at HuoShih (for northbound cars leaving the lane) |
| Lights 0x02/0x03 | GuiLan arterial |
| Light controller | ETH-to-RS485 at 192.168.7.161:1111 |
| B3-PC | 192.168.7.170, runs the smart program; cameras POST to http://192.168.7.170:8100/IP-CAM-A ... -F |
| Cameras | A .164, B .165, C .162, D .167, E .163, F .166 (all 192.168.7.x) |
| Avoid | ports 8000 and 8200 on 127.0.0.1 (the ASUS LED board suite) |

The connecting lane runs between HuoShih (north end) and GuiLan (south end).
**Southbound (S)** = HuoShih -> lane -> GuiLan. **Northbound (N)** = GuiLan -> lane -> HuoShih.

Lane width: the HuoShih side is **one car wide** (A Box-1 to B Box-1). The GuiLan side, from
C/D/E Box-2 up to B Box-1, is **two cars wide** (cars can pass each other).

### Spot map (engine `SPOT`, numbers grow southbound)

| Spot | Zones |
|---|---|
| 0 | F Box-0 (HuoShih side, outside) |
| 1 | A Box-1 |
| 2 | A lines (A Cross-Line-1 = S, A Cross-Line-2 = N) |
| 3 | A Box-2 / B Box-0 |
| 4 | B Box-1 |
| 5 | B lines |
| 6 | B Box-2 |
| 7 | C/D/E Box-2 (the GuiLan exit) |
| 8 | C/D lines (C/D Cross-Line-1 = S out, C/D Cross-Line-2 = N in) |
| 9 | C/D/E Box-1 (GuiLan side, outside) |

Box spots (0,1,3,4,6,7,9). MOUTH {S:3, N:7}, OUTSIDE {S:1, N:9}, EXIT_LINE {S:8, N:2}.
Arterial boxes: A Box-0 (HuoShih, selects z1/z2), C/D Box-0 (GuiLan, selects x1/x2).
F Box-1 / F Box-2 / E Box-0 are recorded only.

## 3. Files in this repo

| Path | What |
|---|---|
| `traffic-light-shinkong/traffic_light_smart_B3.py` | The program on the B3-PC (GUI, HTTP camera server on port 8100, RS485 output). Unchanged since d07ea59b. |
| `traffic-light-shinkong/smart_B3_engine.py` | The decision engine (all the rules). Also replays a log: `python smart_B3_engine.py --replay B3_log_1024.txt` |
| `traffic-light-shinkong/traffic_light_cli_V21_modified_for_ShinKong.py` | The fixed-cycle program (V22), used at B4 and as the fallback cycle. |
| `traffic-light-shinkong/install_autostart.ps1` | Registers a Scheduled Task (default name "ShinKong Traffic Light", default script = the V22 file). |
| `traffic-light-shinkong/tools/` | Replay and safety checks used to verify every change (section 9). |
| `traffic-light-shinkong/data/` | Put the logs here (not in git, see `data/.gitignore`). |
| `.claude/skills/b3-camera-log-analysis/` | The camera-log analysis skill (script, config, results history). |

## 4. What runs on the B3-PC

- Scheduled Task **"ShinKong Traffic Light B3"**, started with uv's Python 3.14 `pythonw`.
- Restart after copying a new file:
  ```powershell
  Stop-ScheduledTask -TaskName "ShinKong Traffic Light B3"
  Start-ScheduledTask -TaskName "ShinKong Traffic Light B3"
  ```
- **Installed:** c0414021 since 11/24 05:40 (fade_to_s 20 s since 11/24 05:42:06 "Settings
  applied"); 1c81bcfb on 11/23; f8d41076 11/21 05:50-11/22; 11/20 still ran 6958870f.
- **Latest file:** see the commit table (section 11); to install.
- **Watchdog / 00:00 restart** set up by the user 11/21 (restart seen 11/21 00:00:02-14,
  lights dark ~12 s). 1-min check, 2 s pause and DontShowUI suggested, not confirmed.
- **11/15 stop:** the program stopped 11/15 09:34:09 and was started again 11/16 14:18:06
  (no Python error, no Stop, no V22 switch logged: the process or the PC stopped). Proposed
  to the user 11/19, waiting: a 5-minute watchdog trigger on the task, a daily 00:00
  restart task, automatic sign-in / BIOS power-on / Windows Update restart settings, and
  Event Viewer commands to find the cause.
- The program writes the camera log `B3_log_YYYY-MM-DD.txt` (same format as HTTP_Server.py)
  and its decisions `B3_decisions_YYYY-MM-DD.txt`. The user uploads both for analysis.

### Settings on the PC (differ from the defaults where marked *)

| Setting | PC | Meaning |
|---|---|---|
| x1 / x2 | 3 / 2 | 0x02/0x03 countdown, GuiLan arterial busy / empty |
| z1 / z2 | 3 / 2 | 0x00 countdown, HuoShih arterial busy / empty |
| w | 2 | 0x00 red -> 0x01 green |
| y | 3 | 0x02/0x03 red after the last southbound car left |
| u * | 3 (default 2) | 0x01 green countdown after the last northbound car left |
| v * | 2 (default 0) | 0x01 red -> 0x00 green |
| south_start | A Box-1 | southbound countdown starts at A Box-1 (user's choice, not A Box-2) |
| backing_stop * | On (since 10/27 09:36) | stop the arterial behind a car backing out |
| backing_clear_s | 3 | release after F Box-0 / GuiLan boxes |
| max_red | 60 | a car that does not move holds the lights at most 60 s ("parked") |
| gone_s | 3 | car ends this long after its exit line with no further movement |
| hold_s / fade_to_s | 5 / 20 * (25 before 11/24) | silent car keeps its score / fades to the cut-off |
| occupied_s | 2.5 | a box counts as occupied this long after its last message |
| quiet_from / quiet_to | 22 * / 8 | no silence alarm 22:00-08:00 (user set 22 long ago, told 11/23) |
| silent_alarm_min | 60 | fixed cycle (V22) if no camera sends for 60 min in the daytime |

## 5. How the engine decides (short)

- A car (Vehicle) is `candidate` -> `active` -> `leaving` -> `ended` (or `cancelled`).
- Each camera message is given to one car by rank:
  0 = the box the car is in (within occupied_s), 1 = just ahead (1-2 boxes),
  2 = straddle just behind (-1, or -2 when backing), 3 = an ended car lingering
  (LINGER_S 5 s) or standing (STAND_S 30 s, e.g. a northbound car waiting at A Box-1).
- Other timings: RETREAT_S 3 (front quiet while a box behind reports = moved back),
  MULTI_CAMERA_S 3 (C and D report one GuiLan crossing up to 2 s apart: one crossing),
  ORPHAN_S 6 (a car first seen on a line adopts recent unexplained boxes).
- Countdowns: southbound starts 0x02/0x03 countdown at A Box-1 (south_start); northbound
  starts the 0x00 countdown at C/D Cross-Line-2 (agreed, not at C/D/E Box-2).
- backing_stop: a car that had passed its entry line and backs out stops the arterial
  behind it (0x00 at HuoShih via ArterialStop; 0x02/0x03 at GuiLan), released by F Box-0
  (+ backing_clear_s) or F Box-1/F Box-2 at HuoShih, C/D/E Box-1 at GuiLan.

### Rules added in 6958870f (agreed 11/01)

1. **Southbound end at GuiLan** (`_south_gone`): do not end while C/D/E Box-2 still shows
   the car; after C/D Cross-Line-1 (and Box-1 if seen) end it when there has been no
   movement and nothing at C/D/E Box-2 for gone_s (3 s). Box-1 alone never ends a car
   (it ended cars still in the lane: 10/27 10:17:48, 10/30 15:18:55), except after a car
   that had crossed rolled back over Cross-Line-2.
2. **Roll-back at the GuiLan exit**: back to Box-2 without Cross-Line-2 = still the same
   car, not ended. Back over C/D Cross-Line-2 = keep both possibilities: the southbound
   car rolled back (its crossing is undone, `before_back` saved) **and** a *possible*
   northbound car (`possible_of`). The possible car is confirmed by B Box-2 or deeper,
   dropped by `_possible_gone`, and never starts an arterial stop. If the possible car is
   confirmed, the southbound car's crossing is restored.
3. **One-car-wide HuoShih mouth** (`_in_mouth`): while a car is in A Box-1/A Box-2/B Box-0,
   an A line there is that car, not a new car (path "(again)").
4. **C/D copy** (`_also_crossing`): the second camera's report of the same GuiLan crossing
   goes to the southbound car right behind only if it is at C/D/E Box-2 (`_ahead == 1`).
5. **Standing southbound car revived** (`_revive`) by its Box-2 at the exit.
6. **Parked car (stood 60 s) that moves again**: a box just behind it (`_behind_rear`) is
   that car moving backwards (rank 2), event "stood 60 s and moves again: backwards".

Verified on 10/26-10/31 with the PC settings: no southbound car reaches C/D/E Box-1 under
green (7 cases before); every northbound exit under 0x00 red; one message used for two
cars 21 -> 3 (left: B lines, 10/28 11:04:45, 10/29 12:53:47, 10/30 14:33:13). Cost:
0x02/0x03 red +410-550 s per day.

## 6. Decisions agreed with the user (keep them)

- Southbound countdown starts at **A Box-1**, not A Box-2 (user's choice; replay: never
  green at an exit, 0x02/0x03 red +9%).
- Northbound countdown stays at **C/D Cross-Line-2**, not C/D/E Box-2 (the user asked on
  10/28; replay: 8% of Box-2 candidates were nothing, Box-2 leads only ~1 s).
- Northbound end: kept as it was (A Cross-Line-2 / A Box-1, gone_s), incl. the STAND_S
  rule for a car waiting at A Box-1 to turn into HuoShih.
- **Keep the 60 s limit** (max_red). The user: "once it moves again, it is a new car and
  your program has to decide which way it will go". The 60 s limit was shown NOT to be
  the cause of the 10/28 12:40 case.
- **No arterial stop for a mouth-only car** (a car that reaches A Box-2 but never passed
  A Cross-Line-1 and backs out to HuoShih: 10/30 12:22:59, 10/31 12:17:11, 13:26:48).
- **Keep-both** only at the GuiLan C/D Cross-Line-2 (roll-back vs new northbound car) and
  for C/D pairing; **not** at HuoShih.
- **C/D pairing**: the user agrees to pair C and D only within 1 s (3 s apart can be two
  cars). Done as keep-both: C and D within MULTI_CAMERA_S (3 s) are one crossing for the
  first car, and the second report is also given to a southbound car right behind it at
  C/D/E Box-2 (10/30 09:46:23: a 1 s D CL1 was the second car).
- A car is treated as backing out only if the program can clearly tell it is reversing out.
- **No workaround for Cross-Line misfires** (rejected fix 710e2477, reverted in 7396c169).
- The rejected 10/29 fixes (16:36 roll-back, 12:40 rear-box) were reverted; do not bring
  them back without asking.

## 7. Facts the user confirmed on site

- **F Box-1** is triggered by the car *behind* (at F Box-0 too) turning right, never by
  the car turning in.
- 10/28 16:36:40 A Cross-Line-1 at a northbound exit was a **misfire** (nowhere in the
  mouth can a car stand unseen for 17 s); ending the car then was right.
- Cars rocking at the GuiLan exit are **turning around** (reverse, then turn right), not
  backing out of the lane. Most "GuiLan back-out" stops on 10/29-10/30 were such cars.
- The IP-CAMs have **no "one crossing per vehicle" option**.
- The user will **adjust camera A's angle** on site (log after that still to come).

## 8. Open questions (waiting for the user's decision: do NOT implement)

1. ~~Rear-box rule~~: **agreed 11/20, built in (f8d41076)**. A box just behind the boxes
   a car still covers is its own tail (lowest rank). Replay 10/26-11/16: 13 phantom cars
   fewer, same lights at every real exit, also with every F Box-0 message removed.
2. **Keep-both on the B Cross-Lines** (the 3 remaining one-message-two-cars cases above).
3. ~~10/28 12:40 leftover~~: the "seen outside = backed out" rule was **declined by the
   user 11/21** (one special case, not worth a rule). Do not bring it back.
4. **Camera B in the morning** (07:30-08:40 on 10/31): B/C/D silent until 07:38 (E 07:32),
   B missed a car at 07:59:22, B fired alone 07:41:57 and 5 times 08:05-08:35.
5. A log **after camera A's angle is adjusted**.
6. **Northbound car rolling back at HuoShih** (asked 11/21). Today a northbound car that has
   ended at HuoShih is never revived: A Box-2/B Box-0 after its end is "no car fits", A Box-1
   after a pause makes a new southbound car. Possible cases: 10/28 15:16:08, 10/29 08:38:15,
   10/31 12:35:12. The user moved F Box-0 (11/21) so exiting / rolling-back northbound cars
   do not trigger it; F Box-0 came before 841 of 844 southbound entries (old position), F
   Box-1/F Box-2 followed only 608 of 910 northbound exits. Moved around 13:45-14:00 on 11/21
   (last northbound exit seen by F Box-0 13:44:55; after it 1 of 29). Example 11/21 13:07:18-
   57 (northbound car out to F Box-2, back in A Box-1/A Box-2 27 s, out again; read as a
   southbound car, 0x00 green). Idea: such a report holds 0x00 for that northbound car too
   (keep both with the southbound car). Waiting for weekday logs with the new F Box-0.
7. **Lost limit** (fade_to_s 25 s): the user wants 3 s (11/21). Replay 10/26-11/16 with hold
   2 / fade 3: 458 cars lost (28 today), 22 real exits under green; 11/16 alone: 24 lost, 13
   of 171 real trips had a 3-4 s silence. 10 s / 15 s: one unsafe exit (10/28 10:09:14, a car
   silent 15 s in the old blind spot between B Box-2 and C/D/E Box-2). Advised: keep 25 s
   until logs with the new boxes show the longest silence of a real car. 20 s: same safety
   as 25 s on all logs; the user will set 20 s once 08999ed7 shows the Confidence boxes.
8. ~~Parked car moving back~~: **built 11/22 (ac9df112)**: its stop starts once it is two
   boxes back, or back in its entry mouth, whichever comes first (user's choice; a stop at
   the first move back gave a 60 s false 0x00 stop on 11/20 13:35:03).
9. ~~GuiLan keep-both gap~~: **built 11/22 (ac9df112, window 3 s since 1c81bcfb)**: a C/D
   Cross-Line-2 within 3 s after a southbound car's box showed it back in the exit from
   C/D/E Box-1 keeps both. Fixes 11/21 10:10:52 and 10:49:41, 10/28 15:23, 10/29 14:31,
   10/30 10:59.
10. **Camera A** missed a whole southbound car 11/20 09:37:03-05 (A Box-1, A CL1, A Box-2;
   B CL1 too). User 11/22: isolated case, record only and keep watching; no program change.
11. ~~GuiLan Box-1 rules~~ **built 11/23 (95eea501)**: a southbound car at C/D/E Box-1 with no
   C/D Cross-Line-1 ends once Box-1 and Box-2 are quiet 3 s, only if it reached C/D/E Box-2
   first (5 s / 8 s Box-1 time alone was rejected: 10/28 11:41 near-miss).
12. ~~GuiLan stop release~~ **built 11/23**: also when C/D/E Box-1 reported and Box-2 quiet 3 s.
13. ~~HuoShih mouth rule~~ **built 11/23**: a southbound candidate does not take a box a
   northbound car in the lane covers or has just behind it (11/21 12:03:45).
14. ~~Northbound roll-back at HuoShih~~ **built 11/23 (c0414021)**: A
   Box-2/B Box-0 3-30 s after a northbound car left at HuoShih, after a 3 s pause and with no
   F Box-0 since it left -> that car "possibly back" (holds 0x00/0x01) and a southbound
   possibility beside it; southbound deeper in -> drop the northbound; northbound boxes
   quiet 3 s -> it left again. 11/21 13:07: 0x00 red 13:07:31-13:08:04. 7 other times in 11
   days (real hesitations at the exit), ~7-10 s 0x00 red each; same lights at real exits.
   11/22 (F Box-0 moved all day): F Box-0 before 16/16 southbound entries, after 1/16
   northbound exits; F Box-1/F Box-2 after 15/16 northbound exits; no roll-back that day.
   11/23: real roll-backs at 12:55:30, 14:09:45, 22:14:44 (0x00 red while the car was back
   in the mouth, then out on HuoShih); 10:19:49 resolved as a southbound car by A CL1. The
   cancelled possibility now gives up its mouth boxes at once (else it hid the southbound
   car's back-out at 10:19:58).
15. **11/16 16:00:35** (not new, also live 6958870f and 730ab509): E Box-1 (GuiLan traffic)
   pulled southbound car #265 over C/D/E Box-2 into Box-1, so its own B Cross-Line-1 in the
   same second made car #266. Tested fix (ver/nojump): a southbound car does not jump over
   C/D/E Box-2 into Box-1. **Built 11/23 (c0414021).** It also ends 11/23 10:49:20's car
   (C Box-1 at 10:49:23) normally instead of lost after 25 s.
16. **11/22 log**: 21:04:23-22:06:42 no camera message at all, but the live program did not
   switch to V22 (replay with silent_alarm_min 60 does). Asked the user to check the
   silence setting. Camera A CL1 12/16 (75%) on 11/22 (86-88% on 11/20-21).
17. Agreed 11/23: look at new logs only; old logs are used only as a regression check.
18. **11/23 log, proposals waiting for the user** (all stages >= 98%, 200 S + 201 N exits,
   only fast-northbound all-red flags, 9 cars lost after 25 s in the new build vs 0-4 before):
   a. Northbound car backing out at GuiLan, GuiLan stop released by "C/D/E Box-1 quiet 3 s",
      but the car itself kept until lost (25 s more 0x00 red + 0x01 green): 11:08:34,
      11:21:47, 11:22:32. Cause: a Box-2 report right after the backwards Cross-Line-1 says
      "back in the lane", and "backed out" needs Box-1 still busy. Proposal: end the car when
      its GuiLan stop ends that way and nothing further in reported.
   b. 11:00:54: southbound car #382 rolled back from Box-1 (11:00:46) and stood in E Box-2;
      C/D Cross-Line-2 8 s later -> full northbound car, lost (27 s 0x00 red). Proposal: the
      keep-both "possible" car while that southbound car still stands in Box-2 after rolling
      back, not only within 3 s.
   c. Late A Cross-Line-1 (1-2 s after the car is already at B Box-1/B Box-2) plus the car's
      own F Box-0 / A Box-1 -> phantom southbound car, lost after 25 s (~15-25 s extra
      0x02/0x03 red): 13:20:31 (+13:20:56), 14:10:48, 14:35:57 (also 10/31 10:07:33,
      11/20 09:22:31). New since F Box-0 was moved (it now sees the car itself). Proposal:
      a southbound car made in the mouth within 3 s behind another one stays a mouth
      candidate until it reaches B Box-1 (dropped like a nose-in otherwise).
   d. Record only: 11:08:05 northbound phantom (previous car's B Box-2 tail + E Box-1/E Box-2
      GuiLan traffic; (a) would shorten it); 15:17 three cars meeting (B CL2 of one car
      confirmed another's possible car, ~23 s extra 0x00 red).
   **Tested together 11/24 (scratchpad ver/abc = c0414021 + a + b + c, script work/mkabc.py),
   waiting for the user:** a needs two more conditions (C/D/E Box-2 quiet 3 s; no line crossed
   in its direction since the stop began), else it ended a car that drove in again (11/20
   13:08:26) or still stood in C/D Box-2 (11/20 14:12:17). Result over 12 days: no
   interaction (the combined copy = the three single changes added, never at the same second),
   real exits and the no-F-Box-0 stress test identical, scenario tests no DANGER. Lost cars
   11/23 9 -> 2, 11/20 2 -> 0. Side effects: GuiLan green 3-4 s earlier at 11/23 09:51:44 and
   11/20 15:19:48 (the old code restarted a GuiLan stop right after releasing it); 11/21
   14:28:48 the car that backed out came in again as a new car (2 s countdown, out under 0x01
   green); a close convoy's second car counts at B Box-1 instead of A Box-1 (first car's red).

19. **11/24-11/25 logs (installed c0414021, fade 20 s) and the 11/26 build** (Claude decides
   now, rule 1): built a (with its two extra conditions), b, c from item 18, plus:
   - f: a southbound car that reached A Box-2/B Box-0 and backs out over A Cross-Line-2
     gets the 0x00 stop even if A Cross-Line-1 missed it (11/24 13:13:45 and 11/25
     10:53:06 backed onto HuoShih under 0x00 green; ~1-2 s of 0x00 red, 5-10 times a day).
   - i: B Box-0, B Box-1, B Box-2 in that order, unexplained, no northbound car -> a
     southbound car (camera A missed the whole car: 11/20 09:37:05, 11/24 14:09:17 left
     at GuiLan under green). B Box-0 + B Box-1 alone was 3 camera-B phantoms (10/31
     08:11:30, 08:35:13; 11/22 08:53:43), so all three are needed.
   - k: roll-back keep-both resolved as southbound only at B Cross-Line-1 or further; A
     Cross-Line-1 and B Box-1 come from the car rolling back too (the user's 11/23 10:19
     explanation; 11/24 17:29:02): GuiLan green at 10:19:59 instead of 10:20:25.
   Not built: e (end a backing-out southbound car on F Box-1/F Box-2 with the mouth quiet,
   the user's idea for 10:19) changed nothing on 14 days, k covers its case; h (a car that
   left keeps its box at C/D/E Box-1, fixes 11/24 10:23:05) made 11/25 10:52 13 s worse;
   g (A Cross-Line-1 while a car is in the mouth goes to it before a candidate, 11/24
   09:32:50) is a double-fired line = rule 5. Verified: 14 days, no rule interaction, real
   exits identical except the two dangerous ones fixed, scenario tests no DANGER, no-F-Box-0
   stress the same. Lost cars 11/23 9->1, 11/24 12->11, 11/25 8->5.
   Record only: 11/24 14:06-14:07 two-way jam (northbound car parked 60 s at B lines,
   0x00 green 14:07:12-21, out at 14:07:22 as 0x00 turned red); B Cross-Line-1 misfires
   while northbound cars pass (11/24 15:01:07, 16:45:29); camera A 11/24: A CL1 88%
   (suspect 14:45:59-14:59:10), whole cars missed 12:09:41 and 14:09:19; camera C 11/25:
   C CL1 72%, C CL2 77% (D covers); 11/25 11:31:21 C/D/E missed a car at GuiLan.

## 9. How to analyse a new log and verify a change

1. Upload: `B3_log_YYYY-MM-DD.txt` and `B3_decisions_YYYY-MM-DD.txt` (UTF-16 or UTF-8).
   Copy them into `traffic-light-shinkong/data/` (or a folder named by `B3_DATA`), keeping
   exactly those names.
2. Camera reliability: run the skill script (see SKILL.md):
   ```bash
   python .claude/skills/b3-camera-log-analysis/scripts/analyze_b3_log.py \
       traffic-light-shinkong/data/B3_log_2026-10-31.txt > /tmp/report.md
   ```
3. Program behaviour (from `traffic-light-shinkong/tools/`):
   ```bash
   python check.py live                 # live decisions: lights at every real exit
   python check.py ..                   # the same in a replay with the engine in ..
   python trace.py .. 2026-10-31 10:05:25 10:05:50 -t   # decisions + messages in a window
   python spans.py 2026-10-31 10:05:25 10:05:50         # raw zone activity in a window
   python summary.py OLD_DIR ..         # red seconds, cars, stops: old vs new engine
   python margins.py OLD_DIR ..         # exits that get less red warning with the new engine
   python rules_test.py ..              # scenario tests: no line may say DANGER
   ```
   OLD_DIR = a folder with an older engine, e.g.
   `mkdir -p /tmp/live && git show 730ab509:traffic-light-shinkong/smart_B3_engine.py > /tmp/live/smart_B3_engine.py`.
4. Before sending any changed .py file: discuss and get consent, then replay all logs
   (check.py 0 flagged, margins.py no exit worse, rules_test.py no DANGER).
5. Append a dated summary to `references/results-history.md`.
6. Report per the user's rule 3: first continue the open discussion, then each
   false/alarm item of the new log in time order, without repeating old points.

## 10. User-side to-do (as of 11/01)

- Register the B4 V22 autostart task (`install_autostart.ps1`, default script and name).
- Consider the signed python.org Python if Windows "Application Control policy has blocked
  this file" for uv's Python again.
- Adjust camera A's angle, then send a log.

## 11. Commit history of this period (engine)

| Commit | What |
|---|---|
| 83e8c00b | keep 0x00 red after a fast northbound car that left before 0x01 green |
| c735c00a | keep a waiting northbound car when the car before it stands at A Box-1 (STAND_S) |
| 730ab509 | F Box-0 straddle only at front 1; C/D pairing uses the path (**installed**) |
| 710e2477 | rejected by the user (16:36 roll-back, 12:40 rear-box) |
| 7396c169 | revert of 710e2477, with the user's approval |
| 6958870f | 11/01 agreed GuiLan exit / HuoShih mouth rules (installed by 11/15) |
| f8d41076 | 11/20 rear-box rule for every car in the lane (installed 11/21 05:50) |
| 08999ed7 | 11/21 shorter gone_s name (Confidence input boxes visible again) |
| ac9df112 | 11/22 parked car two boxes back; GuiLan keep-both after a box roll-back |
| 1c81bcfb | 11/22 keep-both window 3 s |
| 95eea501 | 11/23 GuiLan Box-1 rules + HuoShih mouth rule |
| c0414021 | 11/23 northbound roll-back at HuoShih + no jump into C/D/E Box-1 (installed 11/24) |
| f18909da | 11/26 rules a, b, c, f, i, k (item 19) (**latest**) |
| dbcfbabd, f499a3c0 | analysis notes (results-history.md) |

## 12. Mistakes made before (do not repeat)

- Making fixes without the user's approval (710e2477).
- Using one line message for two cars in an explanation (10/29 17:45:49: two cars cannot
  both cross A Cross-Line-1 in the same message).
- Contradicting yourself ("no car fits yet" vs "lost: no message for 25 s", 10/28 12:40).
- Checking safety only at the exit LINE: also check the moment a southbound car reaches
  C/D/E Box-1 (the cars that rolled back and left later).
- Counting rocking southbound cars as "GuiLan back-outs"; they are turning around.
- Judging with hindsight what the program could not know at that moment.
