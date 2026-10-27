"""Merge sources + check-in -> inputs -> score -> `weeks` row."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tracker.scoring import WeekInputs, WeekScore, rolling_avg, score_week
from tracker.store import Store, load_settings
from tracker.timesplit import busyness, split_hours
from tracker.week import parse_week, week_key


def activity_categories(gcal: dict | None) -> list[str] | None:
    """Calendar categories for the week, or None if the calendar wasn't pulled."""
    return None if not gcal else sorted(set(gcal.get("categories") or []))


def build_inputs(oura: dict | None, gcal: dict | None, checkin: dict | None) -> WeekInputs:
    oura, gcal, checkin = oura or {}, gcal or {}, checkin or {}
    social = checkin.get("social_confirm")
    if social is None and gcal:
        social = gcal.get("social")
    cats = activity_categories(gcal)
    return WeekInputs(
        sleep_avg=oura.get("sleep_avg"),
        readiness_avg=oura.get("readiness_avg"),
        activity_avg=oura.get("activity_avg"),
        stress_calm_pct=oura.get("stress_calm_pct"),
        social=social,
        msg_missed=checkin.get("msg_missed"),
        activity_types=None if cats is None else len(cats),
        non_wear_days=oura.get("non_wear_days") if oura else None,
    )


def watch_metrics(oura: dict | None, checkin: dict | None, busy: dict | None = None) -> dict:
    """Tracked and shown, never scored. None = not recorded (never 0)."""
    busy = busy or {}
    return {
        "gym_days": (oura or {}).get("gym_days"),
        "screen_time_h": (checkin or {}).get("screen_time_h"),
        "booked_pct": busy.get("booked_pct"),
        "busy_band": busy.get("band"),
        "packed_days": busy.get("packed_days"),
    }


def time_split(gcal: dict | None, awake_hours_per_day: float) -> dict | None:
    """Hours per bucket, or None if the calendar wasn't pulled for this week."""
    if not gcal or gcal.get("scheduled_min") is None:
        return None
    return split_hours(gcal["scheduled_min"], awake_hours_per_day, bool(gcal.get("work_tracked")))


def _busyness(gcal: dict | None, s) -> dict | None:
    split = time_split(gcal, s.awake_hours_per_day)
    by_day = (gcal or {}).get("booked_by_day_min")
    return busyness(split, by_day, s.awake_hours_per_day, s.busy_low_pct, s.busy_high_pct, s.packed_day_free_hours)


def _prev_score(store: Store, ws: date) -> WeekScore | None:
    rec, _ = store.get("weeks", week_key(ws - timedelta(days=7)))  # exactly last week, not the last stored
    return WeekScore.from_dict(rec["score"]) if rec and rec.get("score") else None


def rescore(store: Store, ws: date) -> dict:
    """Recompute and save one week from its stored raw data."""
    key = week_key(ws)
    rec, _ = store.get("weeks", key)
    rec = rec or {"week_start": key}
    checkin, _ = store.get("checkins", key)
    inputs = build_inputs(rec.get("oura"), rec.get("gcal"), checkin)
    settings = load_settings(store)
    score = score_week(inputs, settings, prev=_prev_score(store, ws))

    history = [
        store.get("weeks", k)[0]["score"]["total"]
        for k in store.list("weeks")
        if k < key and store.get("weeks", k)[0].get("score")
    ]
    rec.update(
        inputs=inputs.__dict__,
        activity_categories=activity_categories(rec.get("gcal")),
        score=score.to_dict(),
        watch=watch_metrics(rec.get("oura"), checkin, _busyness(rec.get("gcal"), settings)),
        time_split=time_split(rec.get("gcal"), settings.awake_hours_per_day),
        avg4=rolling_avg(history + [score.total]),
        checkin_missing=checkin is None,
        updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    store.put("weeks", key, rec)
    return rec


def rescore_all(store: Store) -> None:
    for key in store.list("weeks"):
        rescore(store, parse_week(key))


def save_source(store: Store, ws: date, source: str, data: dict | None) -> None:
    key = week_key(ws)
    rec, _ = store.get("weeks", key)
    rec = rec or {"week_start": key}
    rec[source] = data
    store.put("weeks", key, rec)
