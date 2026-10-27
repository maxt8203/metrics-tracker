"""Agent loop and graders, tested with a scripted fake model (no API calls)."""

import json
import os
from types import SimpleNamespace as NS

import pytest

from agent.review_agent import run_review
from agent.tools import ToolContext, run_tool
from tests.agent_evals.graders import actions, grade, ungrounded_numbers
from tests.agent_evals.run_evals import run_scenario
from tests.agent_evals.scenarios import REVIEW_WEEK, SCENARIOS
from tracker.store import JsonStore

AMBER = next(s for s in SCENARIOS if s.name == "amber_one_segment_zero")

GOOD_REVIEW = """## Status
AMBER at 75: social scored 0 this week; every other segment was 100.

## Trends
- Totals were 100 for the previous 5 weeks.

## Next week
- Put one social plan in the calendar early in the week.

## Data quality
- None
"""


def usage(i=100, o=50):
    return NS(input_tokens=i, output_tokens=o, cache_creation_input_tokens=0, cache_read_input_tokens=0)


def tool_use(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


class ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        content, stop = self.responses.pop(0)
        return NS(content=content, stop_reason=stop, usage=usage())


@pytest.fixture
def amber_store(tmp_path):
    store = JsonStore(tmp_path)
    AMBER.build(store)
    return store


def test_loop_runs_tools_then_returns_review(amber_store):
    client = ScriptedClient(
        [
            ([tool_use("t1", "get_history", {"n_weeks": 6})], "tool_use"),
            ([tool_use("t2", "get_week", {"week_start": REVIEW_WEEK.isoformat()})], "tool_use"),
            ([NS(type="text", text=GOOD_REVIEW)], "end_turn"),
        ]
    )
    res = run_review(amber_store, REVIEW_WEEK, model="fake", client=client)
    assert res.error is None and res.markdown == GOOD_REVIEW.strip()
    assert [c["name"] for c in res.tool_calls] == ["get_history", "get_week"]
    assert res.usage["input_tokens"] == 300
    # caching markers on system prompt and last tool
    assert client.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert client.calls[0]["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    # tool output reached the model
    sent = client.calls[1]["messages"][2]["content"][0]  # user turn carrying tool results
    assert sent["tool_use_id"] == "t1" and json.loads(sent["content"])["weeks"][-1]["total"] == 75


def test_tool_cap_forces_final_answer(amber_store):
    looping = [([tool_use(f"t{i}", "get_settings", {})], "tool_use") for i in range(3)]
    client = ScriptedClient(looping + [([NS(type="text", text="done")], "end_turn")])
    res = run_review(amber_store, REVIEW_WEEK, model="fake", client=client, max_tool_calls=2)
    assert len(res.tool_calls) == 3 and res.tool_calls[2]["is_error"]  # third call refused
    assert "tool_choice" not in client.calls[1]
    assert client.calls[2]["tool_choice"] == {"type": "none"}


def test_unknown_tool_is_error_and_recorded(amber_store):
    client = ScriptedClient(
        [
            ([tool_use("t1", "delete_everything", {})], "tool_use"),
            ([NS(type="text", text="x")], "end_turn"),
        ]
    )
    res = run_review(amber_store, REVIEW_WEEK, model="fake", client=client)
    assert res.out_of_set_calls == ["delete_everything"] and res.tool_calls[0]["is_error"]


def test_api_failure_degrades_gracefully(amber_store):
    def boom(**kw):
        raise ConnectionError("network down")

    res = run_review(amber_store, REVIEW_WEEK, model="fake", client=NS(messages=NS(create=boom)))
    assert "unavailable" in res.markdown and "ConnectionError" in res.error


def test_tools_reject_future_and_bad_input(amber_store):
    ctx = ToolContext(amber_store, REVIEW_WEEK)
    assert run_tool(ctx, "get_week", {"week_start": "2099-01-05"})[1] is True
    assert run_tool(ctx, "get_history", {"n_weeks": 99})[1] is True
    assert run_tool(ctx, "get_week", {"nope": 1})[1] is True
    out, err = run_tool(ctx, "get_history", {"n_weeks": 8})
    rows = json.loads(out)["weeks"]
    assert not err and len(rows) == 8 and rows[0]["missing"] and rows[-1]["total"] == 75


def test_scripted_scenario_passes_all_graders():
    client = ScriptedClient(
        [
            ([tool_use("t1", "get_history", {"n_weeks": 6})], "tool_use"),
            ([NS(type="text", text=GOOD_REVIEW)], "end_turn"),
        ]
    )
    row = run_scenario(AMBER, "fake", client=client)
    assert row["grade"]["passed"], row["grade"]


def test_graders_catch_bad_review():
    bad = GOOD_REVIEW.replace("75", "71").replace(
        "- Put one", "- Do 4 gym sessions.\n- Call a friend.\n- Sleep more.\n- Put one"
    )
    g = grade(
        bad,
        tool_calls=[{"name": "get_week", "input": {}, "output": '{"total": 75}'}],
        prompt="",
        max_tool_calls=8,
        expect_status="AMBER",
        must_mention=[["social"]],
        forbid_in_actions=["gym"],
    )
    assert not g["numbers_grounded"] and not g["actions_1_to_3"] and not g["no_forbidden_actions"]


def test_number_normalisation_and_actions_parser():
    assert ungrounded_numbers("score 72 and 72.0", ['{"sleep_avg": 72.0}']) == set()
    assert ungrounded_numbers("down for 3 straight weeks, now 64", ['{"total": 70}']) == {"64"}
    assert actions(GOOD_REVIEW) == ["- Put one social plan in the calendar early in the week."]


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s.name)
def test_live_eval(sc):
    row = run_scenario(sc, os.environ.get("EVAL_MODEL", "claude-haiku-5-5"))
    assert row["grade"]["passed"], (row["grade"], row["review"])


def test_max_turns_forces_text_on_last_turn(amber_store):
    turns = [([tool_use(f"t{i}", "get_settings", {})], "tool_use") for i in range(2)]
    client = ScriptedClient(turns + [([NS(type="text", text="final")], "end_turn")])
    res = run_review(amber_store, REVIEW_WEEK, model="fake", client=client, max_turns=3)
    assert res.markdown == "final" and res.error is None
    assert "tool_choice" not in client.calls[1] and client.calls[2]["tool_choice"] == {"type": "none"}


def test_max_turns_exhausted_degrades_gracefully(amber_store):
    # A model that ignores tool_choice and keeps asking for tools.
    turns = [([tool_use(f"t{i}", "get_settings", {})], "tool_use") for i in range(3)]
    res = run_review(amber_store, REVIEW_WEEK, model="fake", client=ScriptedClient(turns), max_turns=3)
    assert "max_turns (3)" in res.error and "unavailable" in res.markdown
