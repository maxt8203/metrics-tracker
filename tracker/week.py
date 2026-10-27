"""Week boundaries. A week is Monday 00:00 -> next Monday 00:00, Europe/London."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/London")


def week_start(d: date) -> date:
    """Monday of the week containing `d`."""
    return d - timedelta(days=d.weekday())


def parse_week(s: str) -> date:
    """Parse `YYYY-MM-DD`; any day is snapped to its Monday."""
    return week_start(date.fromisoformat(s))


def week_key(ws: date) -> str:
    return ws.isoformat()


def week_days(ws: date) -> list[date]:
    return [ws + timedelta(days=i) for i in range(7)]


def week_bounds(ws: date) -> tuple[datetime, datetime]:
    """Timezone-aware local-midnight bounds [start, end). Handles BST/GMT changes."""
    start = datetime.combine(ws, time.min, tzinfo=TZ)
    end = datetime.combine(ws + timedelta(days=7), time.min, tzinfo=TZ)
    return start, end


def last_completed_week(today: date | None = None) -> date:
    today = today or datetime.now(TZ).date()
    return week_start(today) - timedelta(days=7)


def previous_weeks(ws: date, n: int) -> list[date]:
    """`n` week starts ending with `ws`, oldest first."""
    return [ws - timedelta(days=7 * i) for i in range(n - 1, -1, -1)]
