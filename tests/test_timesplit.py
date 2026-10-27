from datetime import date

import pytest

from tracker.timesplit import booked_minutes_by_day, busyness, scheduled_minutes, split_hours

WS = date(2026, 10, 12)  # normal week
DST_WS = date(2026, 10, 19)  # clocks go back Sun 25 Oct


def ev(start, minutes, category=None, title="x", all_day=False):
    return {"start": start, "duration_min": minutes, "category": category, "title": title, "all_day": all_day}


def test_buckets_from_category():
    events = [
        ev("2026-10-12T09:00:00+01:00", 480, "work"),
        ev("2026-10-12T19:00:00+01:00", 120, "social"),
        ev("2026-10-13T18:00:00+01:00", 60, "padel"),
        ev("2026-10-13T20:00:00+01:00", 30, "ignore"),  # admin is still personal time
    ]
    assert scheduled_minutes(events, WS) == {"work": 480, "social": 120, "personal": 90}


def test_overlaps_count_once_and_higher_priority_wins():
    events = [
        ev("2026-10-12T17:00:00+01:00", 120, "work"),  # 17-19
        ev("2026-10-12T18:00:00+01:00", 120, "social"),  # 18-20, 1h overlaps work
        ev("2026-10-12T18:30:00+01:00", 30, "padel"),  # inside both
    ]
    assert scheduled_minutes(events, WS) == {"work": 120, "social": 60, "personal": 0}


def test_events_clipped_to_the_week():
    events = [
        ev("2026-10-11T23:00:00+01:00", 120),  # Sun before: only 1h inside
        ev("2026-10-18T23:30:00+01:00", 60),  # last Sun: only 30 min inside
    ]
    assert scheduled_minutes(events, WS)["personal"] == 90


def test_all_day_and_excluded_markers_skipped():
    events = [
        ev("2026-10-12T00:00:00", 2880, "trip", all_day=True),
        ev("2026-10-12T22:00:00+01:00", 60, title="Phone off"),
        ev("2026-10-12T19:00:00+01:00", 60, title="Dinner"),
    ]
    assert scheduled_minutes(events, WS, exclude=("phone off",))["personal"] == 60


def test_dst_week_counts_real_minutes():
    # 00:30 BST -> 01:30 GMT on 25 Oct is 2 real hours.
    events = [ev("2026-10-25T00:30:00+01:00", 120)]
    assert scheduled_minutes(events, DST_WS)["personal"] == 120


def test_split_hours_and_unplanned():
    h = split_hours({"work": 40 * 60, "social": 10 * 60, "personal": 12 * 60}, 16, work_tracked=True)
    assert h == {"work": 40.0, "social": 10.0, "personal": 12.0, "unplanned": 50.0}  # 112 - 62


def test_work_not_tracked_is_none_not_zero():
    h = split_hours({"work": 0, "social": 60, "personal": 0}, 16, work_tracked=False)
    assert h["work"] is None and h["unplanned"] == 111.0


def test_unplanned_never_negative():
    assert split_hours({"work": 200 * 60, "social": 0, "personal": 0}, 16, True)["unplanned"] == 0.0


# busyness (information only)
SPLIT = {"work": 40.0, "social": 10.0, "personal": 12.0, "unplanned": 50.0}  # 62 of 112 h booked


@pytest.mark.parametrize(
    "booked,band",
    [(40.0, "quiet"), (50.0, "balanced"), (62.0, "balanced"), (84.0, "balanced"), (90.0, "packed")],
)
def test_busyness_bands(booked, band):
    split = {"work": booked, "social": 0.0, "personal": 0.0, "unplanned": 112 - booked}
    assert busyness(split, None, 16, 45, 75, 2)["band"] == band


def test_busyness_pct_and_packed_days():
    by_day = [15 * 60, 14 * 60 + 1, 14 * 60, 8 * 60, 0, 0, 0]  # free: 1 h, 1h59, 2 h, 8 h ...
    b = busyness(SPLIT, by_day, 16, 45, 75, 2)
    assert b == {"booked_pct": 55, "band": "balanced", "packed_days": 2}


def test_busyness_unknown_without_work_or_split():
    assert busyness({**SPLIT, "work": None}, None, 16, 45, 75, 2) is None
    assert busyness(None, None, 16, 45, 75, 2) is None


def test_busyness_capped_at_100():
    assert busyness({**SPLIT, "work": 200.0}, None, 16, 45, 75, 2)["booked_pct"] == 100


def test_booked_by_day_uses_local_days_and_counts_overlap_once():
    events = [
        ev("2026-10-12T23:00:00+01:00", 120, "social"),  # Mon 23:00 -> Tue 01:00: 60 + 60
        ev("2026-10-12T23:30:00+01:00", 30),  # overlaps: not double-counted
        ev("2026-10-18T10:00:00+01:00", 90, "work"),
    ]
    assert booked_minutes_by_day(events, WS) == [60, 60, 0, 0, 0, 0, 90]


def test_booked_by_day_dst_week():
    # Sun 25 Oct: 00:30 BST -> 01:30 GMT is 2 real hours, all on Sunday.
    assert booked_minutes_by_day([ev("2026-10-25T00:30:00+01:00", 120)], DST_WS)[6] == 120
