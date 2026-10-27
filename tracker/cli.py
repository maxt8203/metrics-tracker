"""Command line entry point: `python -m tracker.cli <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from tracker.config import MAX_SCREEN_TIME_H, SEGMENTS, WATCH_METRICS
from tracker.pipeline import rescore, rescore_all, save_source
from tracker.store import Store, load_settings, open_store
from tracker.week import last_completed_week, parse_week, week_key


def _week(arg: str | None):
    return parse_week(arg) if arg else last_completed_week()


def cmd_auth(store: Store, a) -> None:
    if a.provider == "oura":
        from tracker.sources import oura

        oura.login(store)
    else:
        from tracker.sources import gcal

        gcal.login(store)
    print(f"{a.provider}: token stored.")


def cmd_probe_oura(store: Store, a) -> None:
    from tracker.sources import oura

    print(json.dumps(oura.probe(store, _week(a.week)), indent=2))


def cmd_pull(store: Store, a) -> None:
    ws = _week(a.week)
    if not a.no_oura:
        from tracker.sources import oura

        agg = oura.pull_week(store, ws)
        save_source(store, ws, "oura", agg)
        print("oura: pulled")
        for f in agg["failed_collections"]:
            print(f"  WARNING: could not read {f} - those fields are unknown this week, not zero")
    if not a.no_gcal:
        from tracker.sources import gcal

        agg, events, notes = gcal.pull_week(store, ws, use_ai=not a.no_ai)
        save_source(store, ws, "gcal", agg)
        print(f"gcal: {len(events)} events")
        for n in notes:
            print(f"  note: {n}")
        for e in events:
            cat, src = e["category"] or "UNMATCHED", e["source"] or "-"
            print(f"  {e['start'][:10]}  {e['title'][:40]:<40} -> {cat:<11} ({src})")
    rescore(store, ws)
    print_summary(store, 1, ws)


def _ask_yn(prompt: str, default: bool | None = None) -> bool | None:
    raw = input(prompt).strip().lower()
    if not raw:
        return default
    return raw.startswith("y")


def parse_screen_time(raw: str) -> float | None:
    """Blank -> None (not recorded); otherwise hours per day, 0-24."""
    raw = raw.strip().lower().removesuffix("h").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        raise ValueError("enter hours per day, e.g. 3.5, or leave blank") from None
    if not 0 <= v <= MAX_SCREEN_TIME_H:
        raise ValueError(f"enter a value between 0 and {MAX_SCREEN_TIME_H}")
    return round(v, 1)


def _ask_screen_time() -> float | None:
    while True:
        try:
            return parse_screen_time(input("Average daily screen time this week, hours (blank = skip): "))
        except ValueError as e:
            print(f"  {e}")


def cmd_checkin(store: Store, a) -> None:
    ws = _week(a.week)
    print(f"Check-in for week of {ws:%a %d %b %Y}")
    msg = None
    while msg is None:
        msg = _ask_yn("Any important message left unanswered >24h? (y/n): ")
    social = _ask_yn("Social this week? (y/n, blank = use calendar): ")
    screen = _ask_screen_time()
    notes = input("Notes (optional): ").strip()
    store.put(
        "checkins",
        week_key(ws),
        {
            "msg_missed": msg,
            "social_confirm": social,
            "screen_time_h": screen,
            "notes": notes,
            "submitted_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
    rescore(store, ws)
    print_summary(store, 1, ws)


def print_summary(store: Store, n: int, until=None) -> None:
    s = load_settings(store)
    keys = [k for k in store.list("weeks") if until is None or k <= week_key(until)][-n:]
    if not keys:
        print("No weeks stored yet.")
        return
    head = (
        f"{'week':<11} {'total':>5} {'status':<7} " + " ".join(f"{k[:6]:>6}" for k in SEGMENTS) + f" {'avg4':>5}  gaps"
    )
    print(head)
    print("-" * len(head))
    for k in keys:
        rec, _ = store.get("weeks", k)
        sc = rec.get("score")
        if not sc:
            print(f"{k:<11} (not scored)")
            continue
        segs = " ".join(f"{'-' if sc['segments'][seg] is None else sc['segments'][seg]:>6}" for seg in SEGMENTS)
        total = "-" if sc["total"] is None else sc["total"]
        avg4 = "-" if rec.get("avg4") is None else rec["avg4"]
        print(f"{k:<11} {total:>5} {sc['status']:<7} {segs} {avg4:>5}  {', '.join(sc['gap_reasons'])}")
    print(f"\nThresholds: green >= {s.green_threshold}, amber >= {s.amber_threshold}")
    print(f"Oura targets: sleep {s.sleep_target}, exercise {s.exercise_target}, stress {s.stress_target}")
    _print_info_tables(store, keys)


def _fmt(v) -> str:
    if v is None:
        return "-"
    return v if isinstance(v, str) else f"{v:g}"


def _print_info_tables(store: Store, keys: list[str]) -> None:
    """Watch metrics and time split: shown, never scored."""
    from tracker.timesplit import BUCKETS

    recs = [(k, store.get("weeks", k)[0]) for k in keys]
    s = load_settings(store)
    print(
        f"\nWatch (not scored). Busyness: quiet < {s.busy_low_pct:g}% booked < balanced < {s.busy_high_pct:g}% "
        f"< packed; packed day = < {s.packed_day_free_hours:g} h free"
    )
    print(f"{'week':<11} " + " ".join(f"{f'{lbl} ({unit})':>21}" for lbl, unit in WATCH_METRICS.values()))
    for k, rec in recs:
        w = rec.get("watch") or {}
        print(f"{k:<11} " + " ".join(f"{_fmt(w.get(m)):>21}" for m in WATCH_METRICS))
    if any(rec.get("time_split") for _, rec in recs):
        print("\nTime split, hours (not scored; `chart` for the pie)")
        print(f"{'week':<11} " + " ".join(f"{b:>10}" for b in BUCKETS))
        for k, rec in recs:
            t = rec.get("time_split")
            if t:
                print(f"{k:<11} " + " ".join(f"{('n/t' if t[b] is None else _fmt(t[b])):>10}" for b in BUCKETS))


def cmd_summary(store: Store, a) -> None:
    if a.rescore:
        rescore_all(store)
    print_summary(store, a.weeks)


def cmd_chart(store: Store, a) -> None:
    from pathlib import Path

    from tracker.charts import time_split_page

    keys = list(store.list("weeks"))[-a.weeks :]
    recs = {k: store.get("weeks", k)[0] for k in keys}
    weeks = [(k, recs[k].get("time_split")) for k in keys]
    busy = {k: recs[k].get("watch") for k in keys}
    s = load_settings(store)
    band = (
        f"Busyness: quiet < {s.busy_low_pct:g}% of waking hours booked, packed > {s.busy_high_pct:g}%; "
        f"a packed day has < {s.packed_day_free_hours:g} h free."
    )
    out = Path(a.out) if a.out else Path(getattr(store, "root", Path("data"))) / "charts" / "time_split.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(time_split_page(weeks, busy, band))
    print(f"Wrote {out}")


def cmd_review(store: Store, a) -> None:
    from agent.review_agent import run_review

    result = run_review(store, _week(a.week), model=a.model)
    print(result.markdown)
    print(f"\n[tool calls: {len(result.tool_calls)}; usage: {result.usage}]", file=sys.stderr)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="tracker")
    p.add_argument("--data-dir", help="store directory (default: TRACKER_DATA_DIR or ./data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("auth", help="first-time OAuth login")
    sp.add_argument("provider", choices=["oura", "gcal"])
    sp.set_defaults(fn=cmd_auth)

    sp = sub.add_parser("probe-oura", help="print real Oura field names for a week")
    sp.add_argument("--week")
    sp.set_defaults(fn=cmd_probe_oura)

    sp = sub.add_parser("pull", help="pull sources for a week and score it")
    sp.add_argument("--week", help="any date in the week (default: last completed week)")
    sp.add_argument("--no-oura", action="store_true")
    sp.add_argument("--no-gcal", action="store_true")
    sp.add_argument("--no-ai", action="store_true", help="keyword-only calendar classification")
    sp.set_defaults(fn=cmd_pull)

    sp = sub.add_parser("checkin", help="weekly manual check-in")
    sp.add_argument("--week")
    sp.set_defaults(fn=cmd_checkin)

    sp = sub.add_parser("summary", help="score table for recent weeks")
    sp.add_argument("--weeks", type=int, default=8)
    sp.add_argument("--rescore", action="store_true", help="recompute all weeks first")
    sp.set_defaults(fn=cmd_summary)

    sp = sub.add_parser("chart", help="time-split chart (HTML: pie for the latest week + bars per week)")
    sp.add_argument("--weeks", type=int, default=8)
    sp.add_argument("--out", help="output path (default: <data-dir>/charts/time_split.html)")
    sp.set_defaults(fn=cmd_chart)

    sp = sub.add_parser("review", help="run the Weekly Review agent")
    sp.add_argument("--week")
    sp.add_argument("--model")
    sp.set_defaults(fn=cmd_review)

    a = p.parse_args(argv)
    a.fn(open_store(a.data_dir), a)


if __name__ == "__main__":
    main()
