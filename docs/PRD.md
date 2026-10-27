# PRD: Personal Metrics Tracker

| | |
|---|---|
| **Status** | Prototype (sprint slice built; not yet run on live data) |
| **Owner** | Repository owner (single user) |
| **Last updated** | 20 Oct 2026 |
| **Next milestone** | Demo-able slice by 26 Oct 2026 |

---

## 1. Problem

Habits that matter (sleep, exercise, seeing people, keeping up with messages, doing a range of things) slip quietly in busy work and study weeks. A hand-filled spreadsheet stops being filled in exactly when things slip, so the record goes blank at the moment it would be most useful. Missing data then looks like nothing happened, rather than like a signal.

## 2. Goals and non-goals

**Goals**
- G1. Score every week 0–100 with almost no manual input: Oura and Google Calendar pulled automatically, plus a 1-minute check-in.
- G2. Keep 100 achievable in a normal busy week: every target is a low floor, so staying at 100 is the motivator.
- G3. Treat missing data as a signal: surface gaps explicitly instead of scoring them as zero.
- G4. Turn the numbers into a short weekly review: grounded in the data, with 1–3 low-effort actions.
- G5. Be credible as engineering work: tested scoring, evaluated AI components, clear docs.

**Non-goals**
- Medical, diagnostic or mood judgements of any kind.
- Daily tracking or real-time nudges.
- Multiple users, sharing or a web UI.
- Editing data through the report (reports are one-way exports).

## 3. User

One owner who works full time and studies, already wears an Oura ring, keeps plans in Google Calendar, and wants a weekly view that doesn't depend on remembering to fill it in.

## 4. Scoring model

| Segment | Weight | Source | Rule (target) |
|---|---|---|---|
| Sleep | 15 | Oura sleep + readiness scores | weekly avg ÷ 70 |
| Exercise | 20 | Oura activity score | weekly avg ÷ 70 |
| Stress | 15 | Oura daily stress summary | % of days not "stressful" ÷ 70 |
| Social | 25 | Calendar (check-in override) | any social event → 100 |
| Messages | 10 | Check-in | no important message left >24h → 100 |
| Variety | 15 | Calendar (keywords + AI) | distinct chosen-activity categories ÷ 4 |

Status: RED if total < 60 or the same segment is 0 two weeks running; AMBER if total < 90, any segment is 0, or the week has a data gap; otherwise GREEN.

**Tracked, not scored** (stored and shown; never affects the total or status):

| Metric | Source |
|---|---|
| Gym days | Oura workouts |
| Screen time (h/day) | Check-in (manual; no API exists) |
| Time split: work / social / personal / unplanned hours | Google Calendar; unplanned = waking hours with nothing scheduled |
| Busyness: booked % of waking hours, band (quiet / balanced / packed), packed days | Google Calendar |

## 5. Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | Pull Oura daily sleep, readiness, activity, stress and workouts for a Mon–Sun week (Europe/London, BST/GMT-safe) via OAuth2 with single-use refresh-token rotation. |
| FR-2 | Pull Google Calendar events for the same week from configured calendars only (read-only scope). |
| FR-3 | Classify each event: dedicated social calendar → private keywords → public keywords → cached AI answer → one batched AI call for the rest. Output every event → category → source. |
| FR-4 | AI classification returns only categories from a fixed list (schema-enforced and re-validated); falls back to keywords with a note if unavailable. |
| FR-5 | Weekly check-in: messages Y/N, social override, notes. |
| FR-6 | Score per §4 in Python; unknown inputs score `null`, are listed as gap reasons, and are excluded from the total (rescaled). A gap week is never GREEN. |
| FR-7 | Flag a data gap for: missing check-in, any unknown segment, or ≥3 days without Oura data (configurable). |
| FR-8 | Store weeks, check-ins, events, settings and tokens behind one storage interface with optimistic concurrency on tokens and settings. |
| FR-9 | Weekly Review agent with read-only tools; cites only tool-result numbers; ≤3 actions; fixed markdown sections. |
| FR-10 | Agent hard limits: ≤8 tool calls, ≤10 turns, max-tokens cap, fallback text on any failure. |
| FR-11 | Eval suite: agent scenarios and classifier cases on synthetic data, deterministic graders, reported as pass rates. |
| FR-12 | Demo on synthetic data that runs without credentials. |
| FR-13 | Record watch metrics (gym days, screen time) each week; `None` when not recorded; never part of the score. |
| FR-14 | Compute weekly hours per time-split bucket from calendar events: overlaps counted once (work > social > personal), all-day and marker events skipped, unplanned = waking hours − scheduled; work `None` when no work calendar is configured. |
| FR-16 | Busyness per week: booked % of waking hours, band (quiet < 45% ≤ balanced ≤ 75% < packed, configurable) and packed days (< 2 h free); `None` without the work calendar; never scored. |
| FR-15 | `chart` command: HTML page with a pie for the latest week, one bar per week, and a table view; light and dark. |

## 6. Non-functional requirements

- **Privacy:** no personal data, tokens or real calendar/Oura data in the repo; personal keywords and thresholds live in gitignored config; check-in notes are never sent to a model.
- **Fail soft:** an AI or API failure never stops scoring; it degrades with a visible note.
- **Cost:** at most one classifier call and one review run per week; prompt caching on; token usage logged per run.
- **Correctness:** scoring, week boundaries and token rotation covered by unit tests; numbers in reviews are machine-checked against tool output.
- **Portability:** storage and compute swappable (JSON + CLI now, Azure Tables + Functions later) without touching scoring.

## 7. User stories (MoSCoW)

Status: ✅ built and tested offline · 🟡 built, not yet run on live data · ⬜ not started

### Must (sprint, by 26 Oct)
| # | Story | Status |
|---|---|---|
| M1 | As the owner, I want my Oura data pulled automatically, so I don't type sleep or activity numbers by hand. | 🟡 |
| M2 | As the owner, I want my calendar read and classified, so social and variety are scored without manual entry. | 🟡 |
| M3 | As the owner, I want unmatched events interpreted by AI within a fixed category list, so I don't have to maintain a keyword for everything. | 🟡 |
| M4 | As the owner, I want a weekly score with clear segment-by-segment reasons, so I can see what drove AMBER or RED. | ✅ |
| M5 | As the owner, I want missing data flagged as a gap rather than scored as zero, so silence is visible. | ✅ |
| M6 | As the owner, I want a 1-minute check-in (messages, social override, notes), so the score stays right when the calendar is wrong. | ✅ |
| M7 | As the owner, I want a short weekly review that only cites real numbers and suggests ≤3 small actions. | 🟡 |
| M8 | As a reviewer of this project, I want eval pass rates for the AI parts, so I can trust they behave. | 🟡 (harness ✅, live run ⬜) |
| M9 | As a reviewer, I want a public repo with README, diagram and a credential-free demo. | 🟡 (repo not pushed) |

### Should (Phase A–B, Nov – early Dec)
| # | Story | Status |
|---|---|---|
| S1 | As the owner, I want trend alerts when weeks stay low or data stops arriving, so I notice a pattern early. | ⬜ |
| S2 | As the owner, I want the weekly run on a timer (Mon 07:00 UK), so it works when I forget. | ⬜ |
| S3 | As the owner, I want a weekly email with the summary, review and an `.xlsx` report. | ⬜ |
| S4 | As the owner, I want data in Azure Table Storage with secrets in Key Vault. | ⬜ |
| S5 | As the owner, I want my earlier spreadsheet weeks imported. | ⬜ |
| S6 | As the owner, I want to see gym days and screen time each week without them affecting my score. | ✅ |
| S8 | As the owner, I want to see how busy each week was against a healthy range, so I avoid both empty, boring weeks and weeks with no free time. | ✅ (band uncalibrated) |
| S7 | As the owner, I want a weekly pie of work / social / personal / unplanned time, so I can manage how I split my week. | ✅ (calendar not yet live) |

### Could (Phase C, Jan – Feb 2027)
| # | Story | Status |
|---|---|---|
| C1 | As the owner, I want to check in from my phone (Microsoft Forms + Power Automate). | ⬜ |
| C2 | As the owner, I want more eval scenarios and agent improvements. | ⬜ |
| C3 | As the owner, I want a coaching agent that proposes calendar blocks, applied only after my approval. | ⬜ |

### Won't (this release)
- Multi-user support or sharing.
- Daily nudges or notifications.
- Any diagnostic or mood labelling.
- Editing data back from the report.

## 8. Success metrics

| Metric | Target | Current |
|---|---|---|
| Agent eval pass rate (Haiku) | 5/5 | not run |
| Classifier accuracy on labelled cases | ≥ 11/12 | not run |
| Weeks scored from live data | ≥ 2 by 26 Oct | 0 |
| Unattended weekly runs | every week once the timer is live | n/a |
| Model cost per week | measured from `usage` logs; target set after first runs | not measured |

## 9. Decision log

| Date | Decision | Why |
|---|---|---|
| 20 Oct | Green threshold 90 (was 80) | With floor-style targets, 80 let weeks with weak segments pass as GREEN. |
| 20 Oct | A gap week caps at AMBER | A rescaled total over partial data must not look like a clean week. |
| 20 Oct | Calendar is the source of truth for what happened | Keeps the check-in short; skipped plans are deleted or overridden. |
| 20 Oct | Read only calendars of chosen activities | Fixed commitments appear every week regardless and add noise. |
| 20 Oct | Variety from the calendar only; cycling excluded | Variety measures a range of chosen activities, not routine movement. Tested on historical weeks: stricter options blurred busy and quiet weeks. |
| 20 Oct | Gym from Oura only, with a check-in override | One source of truth; override covers unlogged sessions. *(Superseded 25 Oct.)* |
| 20 Oct | Sleep, exercise and stress as separate scored segments (target 70); readiness averaged into sleep | Separate signals are easier to act on; low targets keep 100 achievable. |
| 20 Oct | Private keywords matched before the AI | Fixed commitments map to `ignore`, and those titles never leave the machine. |
| 20 Oct | Declined invites are not filtered | The owner doesn't receive calendar invites; documented as a limitation. |
| 25 Oct | Gym dropped as a scored segment; its 10% moved to Exercise (now 20%); gym count kept as information only; gym check-in questions removed | Weeks without gym can be good weeks; Exercise already reflects movement, including cycling. The review never suggests gym. |
| 26 Oct | Watch metrics (gym days, screen time) tracked but not scored | Worth seeing; scoring them would make 100 harder for things that are nice to have, not essential. |
| 26 Oct | Weekly time split from the calendar (work / social / personal / unplanned), shown as a pie plus weekly bars | Pie answers "this week at a glance" (requested); bars make weeks comparable, which pies can't. |
| 26 Oct | Screen time entered at check-in | iOS and Android expose no screen-time API to apps or Shortcuts. |
| 26 Oct | Work calendar read for time only; its events never reach the AI or variety | Keeps work titles private and work out of the "chosen activities" measure. |
| 26 Oct | Busyness tracked with a two-sided band, not scored yet | Both extremes matter (empty weeks and no free time). The 45–75% band is a reasoned starting guess; scoring it before calibration on 4–6 real weeks would distort the total. Packed days catch a busy stretch hidden in an average week. |

## 10. Assumptions and open questions

- **Oura schema unverified:** field names, gym `activity` values (information only), stress `day_summary` values and whether `daily_stress` needs an extra scope. Resolve with `probe-oura`.
- **Stress definition** (% of non-stressful days) is a proxy; Oura has no 0–100 stress score.
- **Social is binary** and the social calendar always counts; a cancelled plan needs the check-in override.
- **Oura sync lag** could make Sunday look like a non-wear day if the ring hasn't synced by pull time.
- **Time split depends on calendar habits:** unplanned = waking hours (16/day default) − calendar time. If the work calendar holds only meetings, work is understated.
- **Busyness band** (45–75% booked, packed day < 2 h free) is uncalibrated. After 4–6 weeks, set it from the weeks that felt right, then decide whether to make it a scored segment.
- **Weights** (sleep 15, exercise 20, stress 15) are a starting point; revisit after 4–6 weeks of real data.
