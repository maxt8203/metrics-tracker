"""Run the evals against a real model.

python -m tests.agent_evals.run_evals [--model NAME]"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from agent.prompts import user_prompt
from agent.review_agent import run_review
from tests.agent_evals.graders import grade
from tests.agent_evals.scenarios import REVIEW_WEEK, SCENARIOS, Scenario
from tracker.config import env
from tracker.store import JsonStore

MAX_TOOL_CALLS = 8
RESULTS_DIR = Path(__file__).parent / "results"


def run_scenario(sc: Scenario, model: str, client=None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        store = JsonStore(tmp)
        sc.build(store)
        res = run_review(store, REVIEW_WEEK, model=model, client=client, max_tool_calls=MAX_TOOL_CALLS)
    g = grade(
        res.markdown,
        tool_calls=res.tool_calls,
        prompt=user_prompt(REVIEW_WEEK.isoformat()),
        max_tool_calls=MAX_TOOL_CALLS,
        expect_status=sc.expect_status,
        must_mention=sc.must_mention,
        forbid_in_actions=sc.forbid_in_actions,
    )
    if res.error:
        g["passed"], g["detail"] = False, f"{g['detail']} error={res.error}".strip()
    return {
        "scenario": sc.name,
        "grade": g,
        "review": res.markdown,
        "usage": res.usage,
        "tool_calls": [{"name": c["name"], "input": c["input"]} for c in res.tool_calls],
    }


def run_classifier_eval(model: str, client=None) -> dict:
    from tests.agent_evals.classifier_cases import CASES
    from tracker.sources.classifier import classify_unmatched
    from tracker.sources.gcal import classify

    events = [
        {
            "id": str(i),
            "title": t,
            "start": "2026-03-03T18:00:00+00:00",
            "duration_min": 90,
            "all_day": False,
            "calendar_id": "primary",
        }
        for i, (t, _) in enumerate(CASES)
    ]
    keyword_hits = [e["title"] for e in classify(events) if e["category"]]
    res = classify_unmatched([{**e, "category": None} for e in events], client=client, model=model)
    wrong = [
        (t, want, res.categories.get(str(i))) for i, (t, want) in enumerate(CASES) if res.categories.get(str(i)) != want
    ]
    return {
        "correct": len(CASES) - len(wrong),
        "total": len(CASES),
        "wrong": wrong,
        "keyword_hits": keyword_hits,
        "notes": res.notes,
        "usage": res.usage,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=env("EVAL_MODEL", "claude-haiku-5-5"))
    a = p.parse_args(argv)

    clf = run_classifier_eval(a.model)
    print(f"Calendar classifier: {clf['correct']}/{clf['total']} correct on {a.model}")
    for t, want, got in clf["wrong"]:
        print(f"  MISS  {t!r}: expected {want}, got {got}")
    if clf["keyword_hits"]:
        print(f"  warning: keywords already match {clf['keyword_hits']} - pick other test titles")
    print()

    rows = [run_scenario(sc, a.model) for sc in SCENARIOS]
    passed = sum(r["grade"]["passed"] for r in rows)
    for r in rows:
        g = r["grade"]
        failed = [k for k, v in g.items() if v is False and k != "passed"]
        print(f"{'PASS' if g['passed'] else 'FAIL'}  {r['scenario']:<30} {', '.join(failed)} {g['detail']}")
    tokens = {k: sum(r["usage"][k] for r in rows) for k in rows[0]["usage"]}
    print(f"\nPass rate: {passed}/{len(rows)} on {a.model}")
    print(f"Tokens: {tokens}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{a.model}.json"
    out.write_text(
        json.dumps(
            {"model": a.model, "passed": passed, "total": len(rows), "runs": rows, "classifier": clf},
            indent=2,
            default=str,
        )
    )
    print(f"Saved {out}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
