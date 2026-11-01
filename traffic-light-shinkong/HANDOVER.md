# ShinKong B3 smart traffic light: handover (as of 2026-11-01)

This file carries everything agreed in the first Claude account's sessions (10/19 to 11/01),
so the work can continue in another account. **Claude: read this whole file first, then
`smart_B3_engine.py`, then `.claude/skills/b3-camera-log-analysis/SKILL.md` and
`references/results-history.md`, before you answer the user.**

Branch with the latest work: `claude/traffic-light-cycle-refactor-4isbz8`.

---

## 1. The user's working rules (binding, in the user's own words)

1. "If you want to make any changes, discuss them with me first and obtain my approval
   before proceeding; do not make any fix until I have given my consent."
2. "Don't rush to do any fix, discuss with me first!"
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
- **Installed engine:** 730ab509 (since 10/29 00:15; it ran through 10/31).
- **Latest engine:** 6958870f, sent to the user on 11/01, **not installed yet** (as of 11/01).
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
| hold_s / fade_to_s | 5 / 25 | silent car keeps its score / fades to the cut-off |
| occupied_s | 2.5 | a box counts as occupied this long after its last message |
| quiet_from / quiet_to | 23 / 8 | no silence alarm 23:00-08:00 |
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

1. **Rear-box rule** (item 4 of 11/01): a box just behind the boxes a car covers is that
   car's rear. On 10/31 five fast southbound cars (08:33:47, 09:21:52, 10:01:43,
   10:07:33, 11:28:27) had their front at B Box-0/B Box-1 while their rear still reported
   A Box-1 in the same second; that A Box-1 made a phantom car which took the car's own
   A Cross-Line-1 (lost after 25 s, extra red only). The rule removes them; replay
   10/26-10/31: no real exit warned later. The user asked for a detailed explanation and
   side effects; experiment kept outside git (not in 6958870f).
2. **Keep-both on the B Cross-Lines** (the 3 remaining one-message-two-cars cases above).
3. **10/28 12:40 leftover**: after the A Cross-Line-2 "backwards" the car's A Box-2 reads
   as "back in the lane", so 0x02/0x03 stays red until 12:40:44 (extra red only).
4. **Camera B in the morning** (07:30-08:40 on 10/31): B/C/D silent until 07:38 (E 07:32),
   B missed a car at 07:59:22, B fired alone 07:41:57 and 5 times 08:05-08:35.
5. A log **after camera A's angle is adjusted**.

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

- Install 6958870f (`smart_B3_engine.py`) on the B3-PC and restart the task.
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
| 6958870f | 11/01 agreed GuiLan exit / HuoShih mouth rules (**latest, not installed**) |
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
