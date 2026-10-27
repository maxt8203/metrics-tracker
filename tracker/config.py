"""Settings and static config. Personal values go in private_config.py (gitignored)."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field

from dotenv import load_dotenv

load_dotenv()

SEGMENTS = ("sleep", "exercise", "stress", "social", "messages", "variety")


@dataclass
class Settings:
    weights: dict[str, int] = field(
        default_factory=lambda: {
            "sleep": 15,
            "exercise": 20,
            "stress": 15,
            "social": 25,
            "messages": 10,
            "variety": 15,
        }
    )
    # Oura targets: low floors so 100 is reachable in a normal week.
    sleep_target: float = 70  # weekly avg of Oura sleep + readiness scores
    exercise_target: float = 70  # weekly avg Oura activity score
    stress_target: float = 70  # % of recorded days not summarised as "stressful"
    variety_target: int = 4
    green_threshold: int = 90
    amber_threshold: int = 60
    non_wear_gap_days: int = 3  # this many days without Oura data marks a data gap
    awake_hours_per_day: float = 16  # time split: unplanned = awake hours - calendar time
    # Busyness band (not scored). Rough starting values, to adjust after a few real weeks.
    busy_low_pct: float = 45  # below: quiet week (> ~62 free waking hours)
    busy_high_pct: float = 75  # above: packed week (< ~28 free waking hours, ~4 h/day)
    packed_day_free_hours: float = 2  # a day with less free waking time than this is packed

    def validate(self) -> None:
        if set(self.weights) != set(SEGMENTS):
            raise ValueError(f"weights must cover exactly {SEGMENTS}, got {sorted(self.weights)}")
        if sum(self.weights.values()) != 100:
            raise ValueError(f"weights must sum to 100, got {sum(self.weights.values())}")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("weights must be non-negative")
        if not 0 <= self.busy_low_pct <= self.busy_high_pct <= 100:
            raise ValueError("need 0 <= busy_low_pct <= busy_high_pct <= 100")
        if not 0 <= self.amber_threshold <= self.green_threshold <= 100:
            raise ValueError("need 0 <= amber_threshold <= green_threshold <= 100")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Settings:
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        s = cls(**known)
        s.validate()
        return s


# Oura
OURA_AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"
OURA_API_BASE = "https://api.ouraring.com/v2/usercollection"
OURA_SCOPES = ["daily", "workout", "personal"]

# Oura workout types that count as gym (not scored, just shown).
# TODO: check the real values with `python -m tracker.cli probe-oura`.
OURA_GYM_ACTIVITIES: set[str] = {"strength_training", "strengthtraining", "weight_training", "weightlifting"}

# Google Calendar
GCAL_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

CATEGORIES = ("gym", "padel", "cycling", "social", "study", "trip", "hobby", "other-sport", "ignore")
# Not counted towards variety: routine (cycling), admin (ignore) and work.
VARIETY_EXCLUDED = {"ignore", "cycling", "work"}

# Keyword -> category. First match wins.
KEYWORDS: list[tuple[str, str]] = [
    ("padel", "padel"),
    ("gym", "gym"),
    ("push day", "gym"),
    ("pull day", "gym"),
    ("leg day", "gym"),
    ("cycling", "cycling"),
    ("ride", "cycling"),
    ("rides", "cycling"),
    ("cycle", "cycling"),
    ("dinner", "social"),
    ("drink", "social"),
    ("drinks", "social"),
    ("pub", "social"),
    ("party", "social"),
    ("lecture", "study"),
    ("seminar", "study"),
    ("revision", "study"),
    ("flight", "trip"),
    ("golf", "other-sport"),
    ("standup", "ignore"),
    ("1:1", "ignore"),
]


def merge_keywords(private: list[tuple[str, str]], base: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Private keywords go first, so they win over the public list and are
    matched before an event could be sent to the AI classifier."""
    bad = [c for _, c in private if c not in CATEGORIES]
    if bad:
        raise ValueError(f"private keywords use unknown categories: {bad}")
    return [(kw.lower(), c) for kw, c in private] + base


# Personal keywords (e.g. names on fixed recurring commitments) live in the
# gitignored private_config.py - see private_config.example.py.
try:
    from private_config import EXTRA_KEYWORDS as _PRIVATE_KEYWORDS  # type: ignore[import-not-found]
except ImportError:
    _PRIVATE_KEYWORDS = []
KEYWORDS = merge_keywords(_PRIVATE_KEYWORDS, KEYWORDS)

# Time split: skip marker events like "phone off" (set in private_config.py).
try:
    from private_config import TIME_EXCLUDE_KEYWORDS  # type: ignore[import-not-found]
except ImportError:
    TIME_EXCLUDE_KEYWORDS: tuple[str, ...] = ()

# Watch metrics: tracked and shown, never scored
# name -> (label, unit)
WATCH_METRICS: dict[str, tuple[str, str]] = {
    "gym_days": ("Gym days", "days"),
    "screen_time_h": ("Screen time", "h/day"),
    "booked_pct": ("Booked", "% waking"),
    "busy_band": ("Busyness", "band"),
    "packed_days": ("Packed days", "days"),
}
MAX_SCREEN_TIME_H = 24


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or default
