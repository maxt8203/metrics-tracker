"""Read-only tools for the review agent. All numbers come from scoring.py."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from tracker.store import Store, load_settings
from tracker.week import parse_week, previous_weeks, week_key

MAX_HISTORY = 12

TOOL_SCHEMAS = [
    {
        "name": "get_settings",
        "description": "Scoring settings: segment weights, targets and the GREEN/AMBER thresholds.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_week",
        "description": (
            "Full record for one week: inputs, per-segment scores (0-100, null = unknown), total, "
            "status, 4-week average, data gaps, watch metrics and time split (information only, "
            "not scored), Oura and calendar aggregates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"week_start": {"type": "string", "description": "Monday, YYYY-MM-DD"}},
            "required": ["week_start"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_history",
        "description": (
            f"Compact rows (total, status, segments, gaps) for the last n weeks up to and including "
            f"the review week, oldest first. Max {MAX_HISTORY}. Missing weeks are listed as missing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"n_weeks": {"type": "integer", "minimum": 1, "maximum": MAX_HISTORY}},
            "required": ["n_weeks"],
            "additionalProperties": False,
        },
    },
]
TOOL_NAMES = {t["name"] for t in TOOL_SCHEMAS}


class ToolError(Exception):
    pass


@dataclass
class ToolContext:
    store: Store
    review_week: date


def _week_view(rec: dict) -> dict:
    keep = (
        "week_start",
        "inputs",
        "score",
        "avg4",
        "checkin_missing",
        "activity_categories",
        "watch",
        "time_split",
        "oura",
        "gcal",
    )
    return {k: rec.get(k) for k in keep}


def get_settings(ctx: ToolContext) -> dict:
    s = load_settings(ctx.store)
    return {k: v for k, v in s.to_dict().items()}


def get_week(ctx: ToolContext, week_start: str) -> dict:
    try:
        ws = parse_week(week_start)
    except ValueError as e:
        raise ToolError(f"bad week_start {week_start!r}: {e}") from e
    if ws > ctx.review_week:
        raise ToolError("cannot read weeks after the review week")
    rec, _ = ctx.store.get("weeks", week_key(ws))
    return _week_view(rec) if rec else {"week_start": week_key(ws), "missing": True}


def get_history(ctx: ToolContext, n_weeks: int) -> dict:
    if not isinstance(n_weeks, int) or not 1 <= n_weeks <= MAX_HISTORY:
        raise ToolError(f"n_weeks must be an integer 1-{MAX_HISTORY}")
    rows = []
    for ws in previous_weeks(ctx.review_week, n_weeks):
        rec, _ = ctx.store.get("weeks", week_key(ws))
        if not rec or not rec.get("score"):
            rows.append({"week_start": week_key(ws), "missing": True})
            continue
        sc = rec["score"]
        rows.append(
            {
                "week_start": week_key(ws),
                "total": sc["total"],
                "status": sc["status"],
                "segments": sc["segments"],
                "avg4": rec.get("avg4"),
                "gaps": sc["gap_reasons"],
                "watch": rec.get("watch"),
                "time_split": rec.get("time_split"),
            }
        )
    return {"weeks": rows}


_DISPATCH = {"get_settings": get_settings, "get_week": get_week, "get_history": get_history}


def run_tool(ctx: ToolContext, name: str, args: dict) -> tuple[str, bool]:
    """Returns (json_output, is_error)."""
    if name not in _DISPATCH:
        return json.dumps({"error": f"unknown tool {name!r}"}), True
    try:
        return json.dumps(_DISPATCH[name](ctx, **(args or {})), default=str), False
    except (ToolError, TypeError) as e:
        return json.dumps({"error": str(e)}), True
