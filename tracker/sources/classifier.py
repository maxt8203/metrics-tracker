"""Classify calendar events the keyword list missed, with one Haiku call per run.

Answers must be one of the fixed categories. With no API key or on an error,
events just stay unmatched."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from tracker import config

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-5-5"
MAX_EVENTS_PER_CALL = 60
TOOL_NAME = "classify_events"

SYSTEM_PROMPT = """\
You sort personal calendar events into activity categories for a weekly activity tracker.

Categories:
- gym: weights or gym sessions
- padel: padel
- cycling: bike rides
- social: time with friends or family, meals out, parties, dates, calls with friends
- study: lectures, seminars, revision, coursework, exams
- trip: travel away from home, holidays, days out
- hobby: a personal hobby or class (music, cooking, art, language practice, etc.)
- other-sport: any other sport or exercise (golf, running, swimming, football, etc.)
- ignore: work meetings, admin, appointments, reminders, travel logistics, anything else

Rules: pick exactly one category per event. Judge from the title, time and duration only. \
If unsure, choose ignore. Classify every event you are given, using its id exactly.\
"""


def _tool_schema() -> dict:
    return {
        "name": TOOL_NAME,
        "description": "Record one category for each calendar event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "category": {"type": "string", "enum": list(config.CATEGORIES)},
                        },
                        "required": ["id", "category"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["results"],
            "additionalProperties": False,
        },
    }


@dataclass
class ClassifyResult:
    categories: dict[str, str] = field(default_factory=dict)  # event id -> category
    called: bool = False
    rejected: list[dict] = field(default_factory=list)  # model answers we discarded
    notes: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


def _payload(events: list[dict]) -> str:
    return json.dumps(
        [
            {
                "id": e["id"],
                "title": e["title"],
                "start": e["start"],
                "duration_min": e["duration_min"],
                "all_day": e.get("all_day", False),
            }
            for e in events
        ],
        ensure_ascii=False,
    )


def _default_client():
    import anthropic

    return anthropic.Anthropic()


def classify_unmatched(events: list[dict], *, client=None, model: str | None = None) -> ClassifyResult:
    """Classify events whose `category` is None. Never raises."""
    res = ClassifyResult()
    todo = [e for e in events if e.get("category") is None]
    if not todo:
        return res
    if client is None and not config.env("ANTHROPIC_API_KEY"):
        res.notes.append(f"AI classifier skipped (no ANTHROPIC_API_KEY): {len(todo)} event(s) left unmatched")
        return res
    if len(todo) > MAX_EVENTS_PER_CALL:
        res.notes.append(f"{len(todo) - MAX_EVENTS_PER_CALL} event(s) over the per-call cap left unmatched")
        todo = todo[:MAX_EVENTS_PER_CALL]

    model = model or config.env("CLASSIFIER_MODEL", DEFAULT_MODEL)
    try:
        client = client or _default_client()
        resp = client.messages.create(
            model=model,
            max_tokens=200 + 40 * len(todo),
            system=SYSTEM_PROMPT,
            tools=[_tool_schema()],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": _payload(todo)}],
        )
        res.called = True
        res.usage = {k: getattr(resp.usage, k, 0) or 0 for k in ("input_tokens", "output_tokens")}
        block = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
        if block is None:
            raise ValueError("model returned no tool call")
        answers = (block.input or {}).get("results", [])
    except Exception as e:  # noqa: BLE001 - classification is optional
        log.warning("classifier failed: %s", e)
        res.notes.append(f"AI classifier failed ({type(e).__name__}); keyword-only this week")
        return res

    wanted = {e["id"] for e in todo}
    for a in answers:
        eid, cat = a.get("id"), a.get("category")
        if eid in wanted and cat in config.CATEGORIES and eid not in res.categories:
            res.categories[eid] = cat
        else:
            res.rejected.append(a)
    if res.rejected:
        res.notes.append(f"discarded {len(res.rejected)} invalid AI answer(s)")
    missed = len(wanted) - len(res.categories)
    if missed:
        res.notes.append(f"AI left {missed} event(s) unclassified")
    return res
