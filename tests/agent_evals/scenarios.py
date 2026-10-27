"""Eval scenarios: synthetic 6-week histories with a known correct reading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from tracker.store import Store
from tracker.synthetic import seed

REVIEW_WEEK = date(2026, 3, 2)


@dataclass
class Scenario:
    name: str
    overrides: dict[int, dict]
    expect_status: str
    must_mention: list[list[str]] = field(default_factory=list)  # each inner list: any-of
    forbid_in_actions: list[str] = field(default_factory=list)

    def build(self, store: Store) -> None:
        seed(store, REVIEW_WEEK, 6, self.overrides)


SCENARIOS = [
    Scenario("green_week", {}, "GREEN"),
    Scenario(
        "amber_one_segment_zero",
        {0: dict(social=False)},
        "AMBER",
        must_mention=[["social"]],
    ),
    Scenario(
        "red_same_segment_zero_twice",
        {0: dict(msg_missed=True), 1: dict(msg_missed=True)},
        "RED",
        must_mention=[["message"]],
    ),
    Scenario(
        "missing_oura_data",
        {0: dict(oura=False)},
        "AMBER",  # known segments all 100, but a gap week is capped at AMBER
        must_mention=[["oura"], ["sleep"], ["unknown", "missing", "no data", "gap"]],
    ),
    Scenario(
        "variety_dip_no_gym",
        {0: dict(gym=0, activity_types=2)},
        "GREEN",  # variety 50 -> total 92; gym 0 is information only
        must_mention=[["variety"]],
        forbid_in_actions=["gym"],  # prompt rule: never suggest gym
    ),
]
