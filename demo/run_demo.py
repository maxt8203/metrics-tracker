"""Demo on 8 synthetic weeks. The review step runs only if ANTHROPIC_API_KEY is set.

python -m demo.run_demo"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from tracker.cli import print_summary
from tracker.config import env
from tracker.store import JsonStore
from tracker.synthetic import demo_weeks

OUT = Path(__file__).parent / "output"
LAST_WEEK = date(2026, 3, 2)


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    store = JsonStore(OUT)
    demo_weeks(store, LAST_WEEK)
    print_summary(store, 8)

    from tracker.charts import time_split_page, time_split_svg

    recs = {k: store.get("weeks", k)[0] for k in store.list("weeks")}
    weeks = [(k, r.get("time_split")) for k, r in recs.items()]
    busy = {k: r.get("watch") for k, r in recs.items()}
    (OUT / "time_split.html").write_text(time_split_page(weeks, busy))
    (OUT / "time_split.svg").write_text(time_split_svg(weeks, busy=busy))
    print(f"\nTime-split chart: {OUT / 'time_split.html'}")

    if not env("ANTHROPIC_API_KEY"):
        print("\n(ANTHROPIC_API_KEY not set: skipping the Weekly Review agent.)")
        return
    from agent.review_agent import run_review

    res = run_review(store, LAST_WEEK)
    print("\n" + res.markdown)
    print(f"\n[tool calls: {[c['name'] for c in res.tool_calls]}; usage: {res.usage}]")
    (OUT / "review.md").write_text(res.markdown)


if __name__ == "__main__":
    main()
