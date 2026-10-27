# CLAUDE.md

Personal weekly metrics tracker: Oura + Google Calendar + a short check-in → a 0–100 weekly score across 6 segments → a grounded AI weekly review. Requirements and decisions: `docs/PRD.md`. Setup and design: `README.md`.

Signatures are in the source. This file holds the contracts, rules and traps that aren't.

---

## Commands

```bash
make install   # runtime + dev deps
make check     # lint + format check + tests (what CI runs; must pass before every commit)
make format    # apply ruff fixes and formatting
make demo      # synthetic end-to-end run, no credentials
make evals     # LIVE model calls, costs tokens: only when asked
```

`python -m tracker.cli {auth,probe-oura,pull,checkin,summary,review} --help` for the CLI.

---

## Rules (do not break)

1. **Python owns every number.** Scores, totals, averages and statuses come from `scoring.py`. The review agent explains; it never computes. Don't add a tool or prompt that asks it to.
2. **Missing input is unknown, never zero.** `None` = couldn't read or not provided; `[]` / `0` = read fine and nothing there. An unknown segment scores `None`, is listed in `gap_reasons`, and is excluded from the total.
3. **A gap week is never GREEN.** A rescaled total over partial data must not look like a clean week.
4. **Oura partial failure:** a collection that can't be read leaves its fields `None` and is listed in `failed_collections`; if every collection fails, raise `OuraFetchError`. Never turn a failed read into `0` (e.g. 0 gym sessions).
5. **Variety comes from the calendar only.** Oura never feeds it; `cycling` and `ignore` don't count (`VARIETY_EXCLUDED`).
6. **Gym is not scored.** The Oura gym count is information only; don't add it back to the score or let the review suggest gym. (Owner decision, 25 Oct.)
7. **Tracked ≠ scored.** Watch metrics (`WATCH_METRICS`, incl. busyness) and the time split are stored and shown, never part of the total or status. `None` = not recorded, never 0. Work time is `None` without a work calendar.
8. **The calendar is the source of truth for what happened.** Only calendars of chosen activities are read (`GCAL_CALENDAR_IDS`); fixed commitments are left out.
9. **Classification order is load-bearing:** social calendar → private keywords → public keywords → cached AI answer → one AI call. Private keywords run first so those titles never reach the model. AI answers must be in `CATEGORIES`; anything else is discarded.
10. **Oura refresh tokens are single-use.** Persist the new token with the ETag *before* any other call. Never run two pulls at once (the JSON store's lock is in-process only).
11. **Tests never call live APIs.** Mock at the module boundary; inject `http`, `client`, `now` and `sleep`. Live calls happen only via `make evals`.
12. **Scoring changes travel together:** tests, the PRD decision log (§9), the README scoring table, the agent prompt's segment description, and the README demo output.

---

## Public repo rules

- **No personal data, ever:** no `.env`, tokens, `client_secret*.json`, exported data, real Oura or calendar data, names or email addresses. Tests and demos use synthetic data and neutral names.
- **Private requirements, if present, are in `private/`** (gitignored). Read them when working on alerting; never copy their content into tracked files.
- **Personal values go in `private_config.py`** (gitignored; see `private_config.example.py`): `EXTRA_KEYWORDS`, `EVAL_BANNED_WORDS`. Some requirements live outside this repo. Don't add thresholds, names or wording for them to code, tests, docs or commit messages; describe alerting only as "trend alerts".
- **Data sent to a model** is listed in the README (Limitations). Update that list if a change sends anything new. Check-in notes are never sent.

---

## Contracts and traps

- `oura.aggregate_week(...)`: a collection passed as `None` means unreadable, so its fields come back `None`. `non_wear_days` needs **both** sleep and readiness; if either is unreadable it's `None`.
- `oura._get`: retries network errors, 429 and 5xx (up to `MAX_TRIES`); any other 4xx fails at once. Timeout is `(connect, read)`.
- `timesplit.scheduled_minutes`: overlaps resolved by priority work > social > personal; all-day and `TIME_EXCLUDE_KEYWORDS` events skipped. Exclude keywords are **substring** matches (so emoji work), unlike calendar keywords, which are whole-word.
- `timesplit.busyness`: `None` when the split is unknown **or work isn't tracked** (an untracked work calendar would make every week look quiet). `booked_pct` is capped at 100; `packed_days` uses local days (Europe/London).
- Work-calendar events are preset to category `work` in `gcal.classify`: never sent to the AI, never counted in variety or `event_count`.
- `classifier.classify_unmatched`: never raises. No API key or an API error → empty result plus a note (keyword-only).
- `review_agent.run_review`: never raises; on failure returns fallback markdown with `error` set. Caps: 8 tool calls, 10 turns; the last turn is forced to text.
- `gcal.apply_cache`: reuses an AI answer only if the event's **title is unchanged**.
- `Settings.from_dict`: raises on invalid weights. Deliberate: wrong weights mean wrong scores, so fail loudly rather than fall back.
- `config.env()`: an empty string counts as unset.
- `scoring.status_for`: "same segment 0 two weeks running" compares with **exactly** the previous week; if that week is missing, the rule can't fire.
- **Week boundaries:** Monday 00:00 → next Monday 00:00, Europe/London. The week containing a clock change is 167 or 169 hours. Subtracting two aware datetimes with the same `ZoneInfo` ignores the offset, so convert to UTC first.
- **Oura `day`:** sleep is attributed to the wake-up day, so Sunday night lands in the next week. Oura data filtered client-side by `day`, so it doesn't matter whether `end_date` is inclusive.
- **Eval grader:** the grounding check exempts week counts ("3 weeks"); every other number must appear in a tool output or input.
- **Prompt caching** only applies above the model's minimum cacheable length; a short prompt may not cache.

## Unverified (confirm with `probe-oura`, then update the README table)

- Field names for all five Oura collections.
- `OURA_GYM_ACTIVITIES` values (gym count is information only; never scored).
- `daily_stress.day_summary` values and whether it needs an extra OAuth scope.

## Known, accepted gaps

- Declined or unanswered invites still count (the owner receives none).
- Oura sync lag can make Sunday look unworn if the ring hasn't synced by pull time.
- A skipped plan still counts unless deleted (social can be overridden at check-in).

---

## Working style

- British English. Concise, direct; lists over prose; labelled steps for multi-step instructions.
- Never fake data or capability. If something can't be verified, say so and how to verify it.
- Ask before changing a scoring rule, weight, target or threshold; flag, don't silently "fix".
- Conventional commit subjects: `fix(oura): …`, `feat(gcal): …`, `test: …`, `docs: …`, `chore: …`.
- Tests are proportionate: a one-line change gets one short test. Name the bug in a regression test.
- Comments explain *why* and what breaks if changed, not what the line does.
- Docs change in the same commit as the behaviour they describe, and state the current truth (no "UPDATE:" narratives).
