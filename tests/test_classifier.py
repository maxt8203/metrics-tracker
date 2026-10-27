"""Calendar AI classifier: offline tests with a scripted model."""

from types import SimpleNamespace as NS

import pytest

from tracker.sources.classifier import MAX_EVENTS_PER_CALL, TOOL_NAME, classify_unmatched
from tracker.sources.gcal import aggregate, resolve


def ev(id_, title):
    return {
        "id": id_,
        "title": title,
        "start": "2026-10-13T19:00:00+01:00",
        "duration_min": 90,
        "all_day": False,
        "calendar_id": "primary",
    }


EVENTS = [ev("1", "Padel with Sam"), ev("2", "Board games at Jo's"), ev("3", "Pottery class"), ev("4", "Car MOT")]


class FakeClient:
    def __init__(self, answers=None, error=None, no_tool=False):
        self.answers, self.error, self.no_tool, self.calls = answers or [], error, no_tool, []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        content = (
            [NS(type="text", text="hi")]
            if self.no_tool
            else [NS(type="tool_use", id="t", name=TOOL_NAME, input={"results": self.answers})]
        )
        return NS(content=content, usage=NS(input_tokens=300, output_tokens=60))


GOOD = [{"id": "2", "category": "social"}, {"id": "3", "category": "hobby"}, {"id": "4", "category": "ignore"}]


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_only_unmatched_events_sent_and_variety_counts_ai_categories():
    client = FakeClient(GOOD)
    events, notes = resolve(EVENTS, ai_client=client)
    sent = client.calls[0]["messages"][0]["content"]
    assert "Padel" not in sent and "Pottery" in sent  # keyword match not sent
    assert client.calls[0]["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert {e["id"]: (e["category"], e["source"]) for e in events} == {
        "1": ("padel", "keyword"),
        "2": ("social", "ai"),
        "3": ("hobby", "ai"),
        "4": ("ignore", "ai"),
    }
    agg = aggregate(events)
    assert agg["activity_types"] == 3 and agg["social"] and agg["unmatched"] == []
    assert any("AI classified 3" in n for n in notes)


def test_schema_restricts_categories_to_fixed_list():
    client = FakeClient(GOOD)
    classify_unmatched([{**e, "category": None} for e in EVENTS], client=client)
    item = client.calls[0]["tools"][0]["input_schema"]["properties"]["results"]["items"]
    assert "ignore" in item["properties"]["category"]["enum"]


def test_invalid_answers_rejected():
    answers = [
        {"id": "2", "category": "party"},  # not in list
        {"id": "99", "category": "social"},  # not requested
        {"id": "1", "category": "social"},  # keyword-matched, not requested
        {"id": "3", "category": "hobby"},
        {"id": "3", "category": "study"},
    ]  # duplicate: first wins
    events, notes = resolve(EVENTS, ai_client=FakeClient(answers))
    cats = {e["id"]: e["category"] for e in events}
    assert cats == {"1": "padel", "2": None, "3": "hobby", "4": None}
    assert any("discarded 4" in n for n in notes) and any("left 2" in n for n in notes)


def test_no_call_when_everything_matches():
    client = FakeClient()
    resolve([ev("1", "Padel"), ev("2", "Gym")], ai_client=client)
    assert client.calls == []


def test_no_api_key_falls_back_to_keywords():
    events, notes = resolve(EVENTS)  # no client, no key
    assert [e["category"] for e in events] == ["padel", None, None, None]
    assert "no ANTHROPIC_API_KEY" in notes[0]


@pytest.mark.parametrize("client", [FakeClient(error=ConnectionError("down")), FakeClient(no_tool=True)])
def test_api_failure_falls_back_to_keywords(client):
    events, notes = resolve(EVENTS, ai_client=client)
    assert [e["category"] for e in events] == ["padel", None, None, None]
    assert "keyword-only" in notes[0]


def test_no_ai_flag_skips_call():
    client = FakeClient(GOOD)
    resolve(EVENTS, use_ai=False, ai_client=client)
    assert client.calls == []


def test_cache_reused_and_rename_reclassified():
    first, _ = resolve(EVENTS, ai_client=FakeClient(GOOD))
    cached = {e["id"]: e for e in first}

    client = FakeClient()
    again, _ = resolve(EVENTS, cached, ai_client=client)
    assert client.calls == [] and again == first  # free re-run

    renamed = [*EVENTS[:2], ev("3", "Spanish conversation club"), EVENTS[3]]
    client = FakeClient([{"id": "3", "category": "hobby"}])
    resolve(renamed, cached, ai_client=client)
    sent = client.calls[0]["messages"][0]["content"]
    assert "Spanish" in sent and "Board games" not in sent  # only the renamed event


def test_batch_cap():
    many = [{**ev(str(i), f"Thing {i}"), "category": None} for i in range(MAX_EVENTS_PER_CALL + 5)]
    client = FakeClient([])
    res = classify_unmatched(many, client=client)
    assert client.calls[0]["messages"][0]["content"].count('"id"') == MAX_EVENTS_PER_CALL
    assert any("5 event(s) over" in n for n in res.notes)


def test_classifier_eval_cases_are_not_keyword_matches():
    from tests.agent_evals.classifier_cases import CASES
    from tracker.sources.gcal import classify

    hits = [
        e["title"] for e in classify([{"id": t, "title": t, "calendar_id": "p"} for t, _ in CASES]) if e["category"]
    ]
    assert hits == [], hits


def test_classifier_eval_harness_scores_correctly():
    from tests.agent_evals.classifier_cases import CASES
    from tests.agent_evals.run_evals import run_classifier_eval

    answers = [{"id": str(i), "category": c} for i, (_, c) in enumerate(CASES)]
    answers[0]["category"] = "hobby"  # one deliberate miss
    r = run_classifier_eval("fake", client=FakeClient(answers))
    assert (r["correct"], r["total"]) == (len(CASES) - 1, len(CASES)) and r["wrong"][0][2] == "hobby"
