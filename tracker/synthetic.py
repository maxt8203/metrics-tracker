"""Synthetic weeks for the demo and agent evals. No real data, ever."""

from __future__ import annotations

from datetime import date, timedelta

from tracker.pipeline import rescore, save_source
from tracker.store import Store
from tracker.week import previous_weeks, week_key

GOOD_WEEK = dict(sleep=78, readiness=80, activity=75, calm=86, gym=3, social=True, msg_missed=False, activity_types=4)


def add_week(
    store: Store,
    ws: date,
    *,
    sleep=78,
    readiness=80,
    activity=75,
    calm=86,
    gym=3,
    social=True,
    msg_missed=False,
    activity_types=4,
    non_wear=0,
    screen=3.5,
    hours=(38, 9, 14),
    work_tracked=True,
    oura=True,
    gcal=True,
    checkin=True,
) -> dict:
    save_source(
        store,
        ws,
        "oura",
        {
            "sleep_avg": sleep,
            "readiness_avg": readiness,
            "activity_avg": activity,
            "stress_calm_pct": calm,
            "gym_sessions": gym,
            "gym_days": gym,
            "non_wear_days": non_wear,
            "workout_activities": {"strength_training": gym} if gym else {},
        }
        if oura
        else None,
    )
    save_source(
        store,
        ws,
        "gcal",
        {
            "activity_types": activity_types,
            "social": social,
            "event_count": activity_types + 3,
            "categories": ["gym", "padel", "social", "study"][:activity_types],
            "unmatched": [],
            "scheduled_min": {"work": hours[0] * 60, "social": hours[1] * 60, "personal": hours[2] * 60},
            "booked_by_day_min": _spread(hours),
            "work_tracked": work_tracked,
        }
        if gcal
        else None,
    )
    if checkin:
        store.put(
            "checkins",
            week_key(ws),
            {"msg_missed": msg_missed, "social_confirm": None, "screen_time_h": screen, "notes": ""},
        )
    return rescore(store, ws)


def _spread(hours: tuple[int, int, int]) -> list[int]:
    """Weekly hours -> booked minutes per day: work on weekdays, the rest evenly."""
    work, rest = hours[0] * 60, (hours[1] + hours[2]) * 60
    return [round(work / 5 + rest / 7)] * 5 + [round(rest / 7)] * 2


def seed(store: Store, last_week: date, n: int, overrides: dict[int, dict] | None = None) -> None:
    """`n` weeks ending `last_week`. `overrides[k]` patches the week k weeks before the last (0 = last)."""
    overrides = overrides or {}
    for ws in previous_weeks(last_week, n):
        k = (last_week - ws).days // 7
        add_week(store, ws, **{**GOOD_WEEK, **overrides.get(k, {})})


def demo_weeks(store: Store, last_week: date) -> None:
    """8 varied weeks for the README demo."""
    seed(
        store,
        last_week,
        8,
        {
            7: dict(sleep=66, activity=62, calm=57, gym=2, activity_types=2, screen=4.5, hours=(42, 4, 10)),
            6: dict(sleep=74, activity=70, calm=71, gym=3, activity_types=3, hours=(20, 2, 6)),  # quiet
            5: dict(sleep=76, activity=78, calm=86, gym=3, activity_types=4),
            4: dict(activity=55, gym=1, social=False, activity_types=2, screen=5.2, hours=(45, 0, 8)),
            3: dict(sleep=63, activity=68, calm=43, gym=2, activity_types=3, msg_missed=True),
            2: dict(gym=0, activity_types=2, screen=2.1, hours=(0, 30, 20)),  # trip week
            1: dict(sleep=80, activity=82, calm=100, gym=3, activity_types=4, screen=2.8, hours=(36, 14, 16)),
            0: dict(sleep=77, activity=72, calm=86, gym=2, activity_types=3, hours=(50, 18, 22)),  # packed
        },
    )


def last_monday(today: date | None = None) -> date:
    today = today or date.today()
    return today - timedelta(days=today.weekday()) - timedelta(days=7)
