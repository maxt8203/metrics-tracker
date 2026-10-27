"""Weekly time split (work / social / personal / unplanned) and busyness. Not scored.

Overlapping events count once. All-day events and marker events are skipped.
Unplanned = waking hours minus calendar time."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tracker.week import TZ, week_bounds

BUCKETS = ("work", "social", "personal", "unplanned")
_PRIORITY = {"work": 3, "social": 2, "personal": 1}


def bucket_for(event: dict) -> str:
    """work (work calendar), social (social category), else personal."""
    if event.get("category") == "work":
        return "work"
    if event.get("category") == "social":
        return "social"
    return "personal"


def _fill_slots(events: list[dict], ws: date, exclude: tuple[str, ...]) -> tuple[list[int], datetime]:
    """One slot per real minute of the week; each holds the priority of the bucket that owns it (0 = free)."""
    start, end = (b.astimezone(UTC) for b in week_bounds(ws))
    week_min = int((end - start).total_seconds() // 60)  # 10020/10080/10140 around clock changes
    slots = [0] * week_min
    excl = tuple(x.lower() for x in exclude)
    for e in events:
        if e.get("all_day") or e.get("duration_min", 0) <= 0:
            continue
        if any(x in e.get("title", "").lower() for x in excl):
            continue
        s = datetime.fromisoformat(e["start"]).astimezone(UTC)
        a = max(0, int((s - start).total_seconds() // 60))
        b = min(week_min, int((s + timedelta(minutes=e["duration_min"]) - start).total_seconds() // 60))
        p = _PRIORITY[bucket_for(e)]
        for m in range(a, b):
            if slots[m] < p:
                slots[m] = p
    return slots, start


def scheduled_minutes(events: list[dict], ws: date, exclude: tuple[str, ...] = ()) -> dict[str, int]:
    """Minutes per bucket within the week, overlaps resolved by priority."""
    slots, _ = _fill_slots(events, ws, exclude)
    owner = {p: b for b, p in _PRIORITY.items()}
    out = dict.fromkeys(_PRIORITY, 0)
    for p in slots:
        if p:
            out[owner[p]] += 1
    return out


def booked_minutes_by_day(events: list[dict], ws: date, exclude: tuple[str, ...] = ()) -> list[int]:
    """Booked minutes (any bucket, overlaps once) for each local day Mon..Sun."""
    slots, start = _fill_slots(events, ws, exclude)
    out = [0] * 7
    for m, p in enumerate(slots):
        if p:
            day = (start + timedelta(minutes=m)).astimezone(TZ).date()
            out[(day - ws).days] += 1
    return out


def split_hours(scheduled: dict[str, int], awake_hours_per_day: float, work_tracked: bool) -> dict[str, float | None]:
    """Hours per bucket. Unplanned = waking hours minus scheduled time, floored at 0."""
    awake = awake_hours_per_day * 7 * 60
    used = sum(scheduled.values())
    hours = {k: round(v / 60, 1) for k, v in scheduled.items()}
    if not work_tracked:
        hours["work"] = None
    hours["unplanned"] = round(max(0.0, awake - used) / 60, 1)
    return {k: hours[k] for k in BUCKETS}


BANDS = ("quiet", "balanced", "packed")


def busyness(
    split: dict | None,
    booked_by_day: list[int] | None,
    awake_hours_per_day: float,
    low_pct: float,
    high_pct: float,
    packed_day_free_hours: float,
) -> dict | None:
    """Booked % of waking hours, band and packed days. None if work isn't tracked."""
    if not split or split.get("work") is None:
        return None
    booked = sum(split[b] for b in ("work", "social", "personal"))
    pct = round(min(100.0, 100 * booked / (awake_hours_per_day * 7)))
    band = "quiet" if pct < low_pct else "packed" if pct > high_pct else "balanced"
    packed = None
    if booked_by_day is not None:
        packed = sum(1 for m in booked_by_day if awake_hours_per_day * 60 - m < packed_day_free_hours * 60)
    return {"booked_pct": pct, "band": band, "packed_days": packed}
