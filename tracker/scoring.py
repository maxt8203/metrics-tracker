"""Weekly scoring.

An unknown input scores None, not 0. The week is flagged as a gap and the
total uses only the known parts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from tracker.config import SEGMENTS, Settings


@dataclass
class WeekInputs:
    sleep_avg: float | None = None  # weekly avg Oura sleep score
    readiness_avg: float | None = None  # weekly avg Oura readiness score (averaged into sleep)
    activity_avg: float | None = None  # weekly avg Oura activity score ("exercise")
    stress_calm_pct: float | None = None  # % of recorded days not "stressful"
    social: bool | None = None  # any social event, or confirmed at check-in
    msg_missed: bool | None = None  # None = no check-in
    activity_types: int | None = None  # distinct chosen-activity categories (calendar)
    non_wear_days: int | None = None  # days in the week with no Oura sleep/readiness score

    def is_empty(self) -> bool:
        return all(
            v is None
            for v in (
                self.sleep_avg,
                self.readiness_avg,
                self.activity_avg,
                self.stress_calm_pct,
                self.social,
                self.msg_missed,
                self.activity_types,
            )
        )


@dataclass
class WeekScore:
    segments: dict[str, int | None]
    total: int | None
    status: str  # GREEN | AMBER | RED | NO_DATA
    gap_week: bool
    gap_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> WeekScore:
        return cls(**d)


def _pct(value: float, target: float) -> int:
    if target <= 0:
        return 100
    return round(min(value / target, 1) * 100)


def _target(value: float | None, target: float) -> int | None:
    return None if value is None else _pct(value, target)


def sleep_score(i: WeekInputs, s: Settings) -> int | None:
    """Sleep & recovery: average of the Oura sleep and readiness scores (whichever exist)."""
    vals = [v for v in (i.sleep_avg, i.readiness_avg) if v is not None]
    return _target(sum(vals) / len(vals) if vals else None, s.sleep_target)


def exercise_score(i: WeekInputs, s: Settings) -> int | None:
    return _target(i.activity_avg, s.exercise_target)


def stress_score(i: WeekInputs, s: Settings) -> int | None:
    return _target(i.stress_calm_pct, s.stress_target)


def social_score(i: WeekInputs) -> int | None:
    return None if i.social is None else (100 if i.social else 0)


def messages_score(i: WeekInputs) -> int | None:
    return None if i.msg_missed is None else (0 if i.msg_missed else 100)


def variety_score(i: WeekInputs, s: Settings) -> int | None:
    return None if i.activity_types is None else _pct(i.activity_types, s.variety_target)


def score_segments(i: WeekInputs, s: Settings) -> dict[str, int | None]:
    return {
        "sleep": sleep_score(i, s),
        "exercise": exercise_score(i, s),
        "stress": stress_score(i, s),
        "social": social_score(i),
        "messages": messages_score(i),
        "variety": variety_score(i, s),
    }


def total_score(segments: dict[str, int | None], s: Settings) -> int | None:
    known = {k: v for k, v in segments.items() if v is not None}
    weight = sum(s.weights[k] for k in known)
    if weight == 0:
        return None
    return round(sum(v * s.weights[k] for k, v in known.items()) / weight)


def status_for(
    segments: dict[str, int | None], total: int | None, prev: WeekScore | None, s: Settings, gap_week: bool = False
) -> str:
    """A gap week is never GREEN: a total over partial data must not look like a clean week."""
    if total is None:
        return "NO_DATA"
    zero_now = {k for k, v in segments.items() if v == 0}
    zero_prev = {k for k, v in (prev.segments if prev else {}).items() if v == 0}
    if total < s.amber_threshold or zero_now & zero_prev:
        return "RED"
    if total < s.green_threshold or zero_now or gap_week:
        return "AMBER"
    return "GREEN"


def gap_reasons(i: WeekInputs, segments: dict[str, int | None], s: Settings) -> list[str]:
    if i.is_empty():
        return ["no inputs"]
    reasons = []
    if i.msg_missed is None:
        reasons.append("check-in missing")
    reasons += [f"{k} unknown" for k in SEGMENTS if segments[k] is None and k != "messages"]
    if i.non_wear_days is not None and i.non_wear_days >= s.non_wear_gap_days:
        reasons.append(f"oura missing {i.non_wear_days} days")
    return reasons


def score_week(i: WeekInputs, s: Settings, prev: WeekScore | None = None) -> WeekScore:
    s.validate()
    segments = score_segments(i, s)
    total = total_score(segments, s)
    reasons = gap_reasons(i, segments, s)
    return WeekScore(
        segments=segments,
        total=total,
        status=status_for(segments, total, prev, s, gap_week=bool(reasons)),
        gap_week=bool(reasons),
        gap_reasons=reasons,
    )


def rolling_avg(totals: list[int | None], n: int = 4) -> int | None:
    """Mean of the last <= n known totals."""
    recent = [t for t in totals[-n:] if t is not None]
    return round(sum(recent) / len(recent)) if recent else None
