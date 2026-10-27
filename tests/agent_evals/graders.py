"""Deterministic graders for Weekly Review output. No LLM-as-judge."""

from __future__ import annotations

import json
import re

from agent.tools import TOOL_NAMES

NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")

# Tone check. Can be overridden in private_config.py.
DEFAULT_BANNED = ("struggling", "you seem", "it sounds like you", "unmotivated", "lazy")
try:
    from private_config import EVAL_BANNED_WORDS as BANNED  # type: ignore[import-not-found]
except ImportError:
    BANNED = DEFAULT_BANNED
MAX_ACTIONS = 3
REQUIRED_SECTIONS = ("## Status", "## Trends", "## Next week", "## Data quality")


def _norm(n: str) -> str:
    f = float(n)
    return str(int(f)) if f.is_integer() else str(f)


def numbers(text: str) -> set[str]:
    return {_norm(m) for m in NUM.findall(text)}


# "3 weeks" etc. are allowed; any other number must appear in a tool output.
WEEK_COUNT = re.compile(r"\b\d{1,2}\s+(?:\w+\s+)?weeks?\b", re.I)


def ungrounded_numbers(review: str, sources: list[str]) -> set[str]:
    """Numbers in the review that appear in no tool output, tool input or the prompt."""
    allowed: set[str] = set()
    for s in sources:
        allowed |= numbers(s)
    return numbers(WEEK_COUNT.sub(" ", review)) - allowed


def section(review: str, heading: str) -> str:
    m = re.search(rf"^{re.escape(heading)}\s*$(.*?)(?=^## |\Z)", review, re.M | re.S)
    return m.group(1) if m else ""


def actions(review: str) -> list[str]:
    return [ln.strip() for ln in section(review, "## Next week").splitlines() if re.match(r"\s*[-*] ", ln)]


def grade(
    review: str,
    *,
    tool_calls: list[dict],
    prompt: str,
    max_tool_calls: int,
    expect_status: str,
    must_mention: list[list[str]],
    forbid_in_actions: list[str],
) -> dict[str, bool | str]:
    low = review.lower()
    acts = actions(review)
    sources = [c["output"] for c in tool_calls] + [json.dumps(c["input"]) for c in tool_calls] + [prompt]
    bad_nums = ungrounded_numbers(review, sources)
    checks: dict[str, bool] = {
        "sections_present": all(h in review for h in REQUIRED_SECTIONS),
        "numbers_grounded": not bad_nums,
        "status_correct": expect_status in section(review, "## Status").upper(),
        "mentions_expected": all(any(w in low for w in group) for group in must_mention),
        "actions_1_to_3": 1 <= len(acts) <= MAX_ACTIONS,
        "no_forbidden_actions": not any(w in a.lower() for a in acts for w in forbid_in_actions),
        "tools_in_set": all(c["name"] in TOOL_NAMES for c in tool_calls),
        "tool_cap_respected": len(tool_calls) <= max_tool_calls,
        "used_tools": len(tool_calls) > 0,
        "tone_ok": not any(w.lower() in low for w in BANNED),
    }
    detail = f"ungrounded={sorted(bad_nums)}" if bad_nums else ""
    return {**checks, "passed": all(checks.values()), "detail": detail}
