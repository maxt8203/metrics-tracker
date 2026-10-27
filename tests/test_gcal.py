from tracker.sources.gcal import aggregate, classify, normalise

EVENTS = [
    {"id": "1", "title": "Padel with Sam", "calendar_id": "primary"},
    {"id": "2", "title": "Gym - push day", "calendar_id": "primary"},
    {"id": "3", "title": "Team standup", "calendar_id": "primary"},
    {"id": "4", "title": "Quiz night", "calendar_id": "social-cal"},
    {"id": "5", "title": "Dentist", "calendar_id": "primary"},
]


def test_keyword_and_social_calendar_classification():
    out = {e["id"]: (e["category"], e["source"]) for e in classify(EVENTS, social_calendar_id="social-cal")}
    assert out == {
        "1": ("padel", "keyword"),
        "2": ("gym", "keyword"),
        "3": ("ignore", "keyword"),
        "4": ("social", "calendar"),
        "5": (None, None),
    }


def test_aggregate_excludes_ignore_and_lists_unmatched():
    agg = aggregate(classify(EVENTS, social_calendar_id="social-cal"))
    assert agg["activity_types"] == 3  # padel, gym, social
    assert agg["social"] is True
    assert agg["unmatched"] == ["Dentist"]


def test_keywords_match_whole_words_only():
    out = classify(
        [
            {"id": "x", "title": "Public holiday admin", "calendar_id": "primary"},
            {"id": "y", "title": "Pub with uni friends", "calendar_id": "primary"},
        ]
    )
    assert [e["category"] for e in out] == [None, "social"]


def test_no_social_when_absent():
    agg = aggregate(classify(EVENTS[:3]))
    assert agg["social"] is False and agg["activity_types"] == 2


def test_normalise_timed_and_all_day():
    timed = normalise(
        {
            "id": "a",
            "summary": "Gym",
            "start": {"dateTime": "2026-10-25T00:30:00+01:00"},
            "end": {"dateTime": "2026-10-25T01:30:00+00:00"},
        },
        "primary",
    )
    assert timed["duration_min"] == 120  # spans the clock change
    all_day = normalise(
        {"id": "b", "summary": "Trip", "start": {"date": "2026-10-24"}, "end": {"date": "2026-10-26"}}, "primary"
    )
    assert all_day["all_day"] and all_day["duration_min"] == 2880


def test_keyword_variants():
    titles = ["Cycling to the coast", "Sunday rides", "Drink with Ana", "Ride home", "Drinks at 7"]
    out = classify([{"id": str(n), "title": t, "calendar_id": "primary"} for n, t in enumerate(titles)])
    assert [e["category"] for e in out] == ["cycling", "cycling", "social", "cycling", "social"]


# private keywords (fixed commitments)
def test_private_keywords_win_over_public_list():
    from tracker.config import KEYWORDS, merge_keywords

    kws = merge_keywords([("Alex", "ignore")], KEYWORDS)
    out = classify(
        [
            {"id": "1", "title": "Dinner with Alex", "calendar_id": "primary"},
            {"id": "2", "title": "Alex", "calendar_id": "primary"},
            {"id": "3", "title": "Dinner with Sam", "calendar_id": "primary"},
        ],
        keywords=kws,
    )
    assert [e["category"] for e in out] == ["ignore", "ignore", "social"]


def test_private_keyword_match_is_never_sent_to_ai():
    from tracker.config import KEYWORDS, merge_keywords
    from tracker.sources import gcal

    kws = merge_keywords([("alex", "ignore")], KEYWORDS)
    sent = []
    client = type("C", (), {"messages": type("M", (), {"create": staticmethod(lambda **kw: sent.append(kw))})()})()
    orig = gcal.config.KEYWORDS
    gcal.config.KEYWORDS = kws
    try:
        events, _ = gcal.resolve(
            [
                {
                    "id": "1",
                    "title": "Alex",
                    "start": "2026-10-13T10:00:00+01:00",
                    "duration_min": 50,
                    "calendar_id": "primary",
                }
            ],
            ai_client=client,
        )
    finally:
        gcal.config.KEYWORDS = orig
    assert events[0]["category"] == "ignore" and sent == []


def test_private_keywords_reject_unknown_category():
    import pytest

    from tracker.config import merge_keywords

    with pytest.raises(ValueError):
        merge_keywords([("alex", "party")], [])


def test_cycling_does_not_count_towards_variety():
    out = classify(
        [
            {"id": "1", "title": "Ride to the coast", "calendar_id": "primary"},
            {"id": "2", "title": "Cinema with Sam", "calendar_id": "primary"},
            {"id": "3", "title": "Dinner with Sam", "calendar_id": "primary"},
        ]
    )
    agg = aggregate(out)
    assert out[0]["category"] == "cycling"  # still classified, so it shows in the audit list
    assert agg["categories"] == ["social"] and agg["activity_types"] == 1


# work calendar: time split only
def test_work_calendar_preset_never_ai_never_variety():
    from tracker.sources import gcal as g

    events = [
        {
            "id": "w",
            "title": "Sprint planning dinner",
            "start": "2026-10-13T09:00:00+01:00",
            "duration_min": 60,
            "calendar_id": "work-cal",
        },
        {
            "id": "p",
            "title": "Padel",
            "start": "2026-10-13T18:00:00+01:00",
            "duration_min": 60,
            "calendar_id": "primary",
        },
    ]
    sent = []
    client = type("C", (), {"messages": type("M", (), {"create": staticmethod(lambda **kw: sent.append(kw))})()})()
    out, _ = g.resolve(events, ai_client=client, work_calendar_id="work-cal")
    assert out[0]["category"] == "work" and out[0]["source"] == "calendar"  # "dinner" keyword ignored
    assert sent == []  # nothing unmatched, so no AI call; work titles never sent
    agg = aggregate(out)
    assert agg["categories"] == ["padel"] and agg["social"] is False and agg["event_count"] == 1


def test_aggregate_with_week_adds_scheduled_minutes():
    from datetime import date

    events = [
        {
            "id": "1",
            "title": "Padel",
            "start": "2026-10-13T18:00:00+01:00",
            "duration_min": 90,
            "all_day": False,
            "category": "padel",
            "source": "keyword",
        }
    ]
    agg = aggregate(events, date(2026, 10, 12), work_tracked=False)
    assert agg["scheduled_min"] == {"work": 0, "social": 0, "personal": 90} and agg["work_tracked"] is False
