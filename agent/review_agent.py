"""Weekly review agent: a tool-use loop with limits on tool calls and turns."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import date

from agent.prompts import SYSTEM_PROMPT, user_prompt
from agent.tools import TOOL_NAMES, TOOL_SCHEMAS, ToolContext, run_tool
from tracker.config import env
from tracker.store import Store
from tracker.week import week_key

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5-5"
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


@dataclass
class ReviewResult:
    markdown: str
    model: str
    tool_calls: list[dict] = field(default_factory=list)  # {"name", "input", "output", "is_error"}
    usage: dict[str, int] = field(default_factory=lambda: dict.fromkeys(USAGE_KEYS, 0))
    error: str | None = None
    stop_reason: str | None = None

    @property
    def out_of_set_calls(self) -> list[str]:
        return [c["name"] for c in self.tool_calls if c["name"] not in TOOL_NAMES]

    @property
    def tool_outputs(self) -> list[str]:
        return [c["output"] for c in self.tool_calls]


def _cached_tools() -> list[dict]:
    tools = copy.deepcopy(TOOL_SCHEMAS)
    tools[-1]["cache_control"] = {"type": "ephemeral"}  # caches system + all tools
    return tools


def _add_usage(total: dict, usage) -> None:
    for k in USAGE_KEYS:
        total[k] += getattr(usage, k, 0) or 0


def _text(content) -> str:
    return "\n".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


def _default_client():
    import anthropic

    return anthropic.Anthropic()


def run_review(
    store: Store,
    ws: date,
    *,
    model: str | None = None,
    client=None,
    max_tool_calls: int = 8,
    max_turns: int = 10,
    max_tokens: int = 1200,
) -> ReviewResult:
    model = model or env("REVIEW_MODEL", DEFAULT_MODEL)
    result = ReviewResult(markdown="", model=model)
    ctx = ToolContext(store=store, review_week=ws)
    messages: list[dict] = [{"role": "user", "content": user_prompt(week_key(ws))}]
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    tools = _cached_tools()

    try:
        client = client or _default_client()
        for turn in range(max_turns):
            kwargs = dict(model=model, max_tokens=max_tokens, system=system, tools=tools, messages=messages)
            if len(result.tool_calls) >= max_tool_calls or turn == max_turns - 1:
                kwargs["tool_choice"] = {"type": "none"}  # last chance: must answer in text
            resp = client.messages.create(**kwargs)
            _add_usage(result.usage, resp.usage)
            result.stop_reason = resp.stop_reason
            messages.append({"role": "assistant", "content": resp.content})

            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            if resp.stop_reason != "tool_use" or not tool_uses:
                result.markdown = _text(resp.content)
                if resp.stop_reason == "max_tokens":
                    result.error = "hit max_tokens; review may be truncated"
                break

            results = []
            for b in tool_uses:
                if len(result.tool_calls) >= max_tool_calls:
                    output, is_err = '{"error": "tool budget used up; write the review now"}', True
                else:
                    output, is_err = run_tool(ctx, b.name, b.input)
                result.tool_calls.append({"name": b.name, "input": b.input, "output": output, "is_error": is_err})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": output, "is_error": is_err})
            messages.append({"role": "user", "content": results})
        else:
            result.error = f"max_turns ({max_turns}) reached without a final review"
            result.markdown = "_Weekly review unavailable this week. Scores above are unaffected._"
    except Exception as e:  # noqa: BLE001 - the weekly run shouldn't fail because of the review
        log.exception("review failed")
        result.error = f"{type(e).__name__}: {e}"
        result.markdown = result.markdown or "_Weekly review unavailable this week. Scores above are unaffected._"

    log.info("review usage %s tool_calls=%d", result.usage, len(result.tool_calls))
    return result
