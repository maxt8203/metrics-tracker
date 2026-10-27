from datetime import UTC, date, timedelta

from tracker.week import last_completed_week, parse_week, previous_weeks, week_bounds, week_start


def test_week_start_snaps_to_monday():
    assert week_start(date(2026, 10, 18)) == date(2026, 10, 12)  # Sunday
    assert week_start(date(2026, 10, 12)) == date(2026, 10, 12)  # Monday
    assert parse_week("2026-10-21") == date(2026, 10, 19)


def test_week_spanning_bst_to_gmt_is_169_hours():
    # Clocks go back 01:00 GMT on Sun 25 Oct 2026, so this week is an hour longer.
    start, end = week_bounds(date(2026, 10, 19))
    assert start.utcoffset() == timedelta(hours=1)
    assert end.utcoffset() == timedelta(hours=0)
    # Same-tzinfo subtraction ignores offsets in Python, so compare in UTC.
    assert (end.astimezone(UTC) - start.astimezone(UTC)) == timedelta(hours=169)
    assert start.isoformat() == "2026-10-19T00:00:00+01:00"
    assert end.isoformat() == "2026-10-26T00:00:00+00:00"


def test_normal_week_is_168_hours():
    start, end = week_bounds(date(2026, 10, 12))
    assert (end.astimezone(UTC) - start.astimezone(UTC)) == timedelta(hours=168)


def test_last_completed_week():
    assert last_completed_week(date(2026, 10, 20)) == date(2026, 10, 12)
    assert last_completed_week(date(2026, 10, 26)) == date(2026, 10, 19)


def test_previous_weeks_oldest_first():
    assert previous_weeks(date(2026, 10, 19), 3) == [date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)]
