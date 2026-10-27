# REVIEW.md

How to review a change to this repo, by a human or a bot. Guiding principle: **a wrong score is worse than a crash.** A crash gets noticed; a plausible wrong number trains the owner to trust a week that wasn't fine.

---

## Severity

**🔴 Important.** Anything that could:
- produce a wrong segment, total or status (e.g. missing data read as 0, the wrong week, a gap week shown GREEN, a watch metric or the time split leaking into the score);
- drop data without a visible signal (no gap reason, no CLI warning);
- lose or double-spend an Oura refresh token;
- leak personal data, or wording about requirements kept outside this repo, into code, tests, docs or commits;
- send new data to a model without updating the README list;
- weaken an AI guardrail (the model computing numbers, categories outside the fixed list, tool or turn caps removed, a failure path that raises).

**🟡 Nit.** Everything else, however strongly held. **Max 5 nits per review**; summarise the rest as "plus N similar".

**Format**
- Open with a tally: `2 important, 3 nits`, or `No factual issues`.
- **Cite `file:line` before asserting runtime behaviour.** Never infer behaviour from a name. No citation, no finding.
- Second review of the same change: Important only, no new nits.
- If you can't run the tests, judge from the test code in the diff and say "only execution can settle this: run `make check`". Never claim tests passed.

---

## Hazard classes

For every diff, name which apply and answer them.

1. **Clock.** Does the result depend on when it runs?
   - Week boundaries are Europe/London; does a DST week (167/169 h) still work?
   - Oura attributes sleep to the wake-up day; does the change assume otherwise?
   - Does "last completed week" shift if run on a Sunday night vs Monday morning?
2. **Missing, partial or sentinel input.** Can any input be absent?
   - `None` must stay unknown: never `0`, `[]`, `False` or a default.
   - A failed read must not look like "nothing recorded" (`aggregate_week` contract).
   - An unknown segment must appear in `gap_reasons`.
3. **Replay and idempotency.**
   - Does running `pull` or `rescore` twice for the same week give the same result?
   - Is the classifier cache keyed so a renamed event is reclassified?
   - Is a rotated Oura token persisted with the ETag before anything else?
4. **Silent drop.** Can an event, collection or week vanish without a signal?
   - A log line or a `print` buried in output isn't enough for a lost data source; it needs a gap reason or a WARNING line.
5. **Ambiguity and precedence.**
   - Can an event match several keywords? First match wins, so is the order right?
   - Do private keywords still run before public ones and before the AI?
   - What happens with none, one or several matches?
6. **Privacy.**
   - Any real names, emails, calendar titles, Oura values or tokens in the diff, fixtures or commit message?
   - Any personal value that belongs in `private_config.py`?
   - Anything new sent to Anthropic?
7. **AI behaviour.**
   - Does every number the agent can cite still come from a tool result?
   - Are the eval graders still able to catch the failure this change could cause?
   - Is the change covered by an eval scenario or an offline harness test?

---

## Scoring-change checklist

A change to a segment rule, weight, target, threshold or status rule is 🔴 unless all of these are in the same change:
- [ ] tests for the new behaviour, with old tests updated (not deleted to make it pass);
- [ ] a PRD decision-log row (`docs/PRD.md` §9) with the reason;
- [ ] the README scoring table and demo output;
- [ ] the agent prompt's segment description (`agent/prompts.py`);
- [ ] eval scenarios' expected statuses re-checked.

---

## Do not report

- Formatting and import order: ruff enforces them in CI.
- Demo output values (synthetic).
- Values in `private_config.example.py` (examples by design).
- Generated paths: `demo/output/`, `tests/agent_evals/results/`.
- **Never quote `.env`, `private_config.py` or token files** in a review, even if they appear in a diff by mistake. Report only that they appeared, as 🔴.
