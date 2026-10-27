from datetime import date
from types import SimpleNamespace

import pytest
import requests

from tracker.sources import oura
from tracker.store import JsonStore

WS = date(2026, 10, 12)


@pytest.fixture(autouse=True)
def oura_env(monkeypatch):
    monkeypatch.setenv("OURA_CLIENT_ID", "cid")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "secret")


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def post(self, url, data, timeout):
        self.posts.append(data)
        status, body = self.responses.pop(0)
        resp = SimpleNamespace(status_code=status, json=lambda: body)
        resp.raise_for_status = lambda: None if status < 400 else (_ for _ in ()).throw(RuntimeError(status))
        return resp


def test_aggregate_filters_to_week_and_counts_non_wear():
    sleep = [
        {"day": "2026-10-12", "score": 70},
        {"day": "2026-10-13", "score": 74},
        {"day": "2026-10-19", "score": 99},
    ]  # next Monday: excluded
    readiness = [{"day": "2026-10-12", "score": 78}, {"day": "2026-10-14", "score": None}]
    workouts = [
        {"day": "2026-10-13", "activity": "strength_training"},
        {"day": "2026-10-15", "activity": "cycling"},
        {"day": "2026-10-16", "activity": "walking"},
        {"day": "2026-10-19", "activity": "strength_training"},  # excluded
    ]
    agg = oura.aggregate_week(WS, sleep, readiness, workouts, gym_activities={"strength_training"})
    assert agg["sleep_avg"] == 72.0
    assert agg["readiness_avg"] == 78.0
    assert agg["non_wear_days"] == 5  # only 12th and 13th have scores
    assert agg["gym_sessions"] == 1  # cycling and walking don't count as gym
    assert agg["workout_activities"] == {"strength_training": 1, "cycling": 1, "walking": 1}
    assert "categories" not in agg  # Oura never feeds variety


def test_aggregate_empty_week():
    agg = oura.aggregate_week(WS, [], [], [])
    assert agg["sleep_avg"] is None and agg["non_wear_days"] == 7 and agg["gym_sessions"] == 0


def test_valid_token_not_refreshed(tmp_path):
    store = JsonStore(tmp_path)
    store.put("tokens", "oura", {"access_token": "A", "refresh_token": "R", "expires_at": 10_000})
    http = FakeHttp([])
    assert oura.get_access_token(store, http=http, now=lambda: 1_000) == "A"
    assert http.posts == []


def test_expired_token_rotates_and_persists_new_refresh_token(tmp_path):
    store = JsonStore(tmp_path)
    store.put("tokens", "oura", {"access_token": "A", "refresh_token": "R1", "expires_at": 0})
    http = FakeHttp([(200, {"access_token": "B", "refresh_token": "R2", "expires_in": 86400})])
    assert oura.get_access_token(store, http=http, now=lambda: 1_000) == "B"
    assert http.posts[0]["refresh_token"] == "R1"
    assert store.get("tokens", "oura")[0]["refresh_token"] == "R2"


def test_rotation_conflict_uses_stored_token(tmp_path, monkeypatch):
    store = JsonStore(tmp_path)
    store.put("tokens", "oura", {"access_token": "A", "refresh_token": "R1", "expires_at": 0})
    http = FakeHttp([(200, {"access_token": "B", "refresh_token": "R2", "expires_in": 86400})])
    real_post = http.post

    def racing_post(*a, **kw):  # another process rotates first
        resp = real_post(*a, **kw)
        store.put("tokens", "oura", {"access_token": "C", "refresh_token": "R3", "expires_at": 99_999})
        return resp

    http.post = racing_post
    assert oura.get_access_token(store, http=http, now=lambda: 1_000) == "C"
    assert store.get("tokens", "oura")[0]["refresh_token"] == "R3"


def test_rejected_refresh_raises_auth_error(tmp_path):
    store = JsonStore(tmp_path)
    store.put("tokens", "oura", {"access_token": "A", "refresh_token": "R1", "expires_at": 0})
    with pytest.raises(oura.OuraAuthError):
        oura.get_access_token(store, http=FakeHttp([(400, {"error": "invalid_grant"})]), now=lambda: 1_000)


# refresh retry when another process rotated the token
def test_rejected_refresh_retries_once_with_rotated_token(tmp_path):
    store = JsonStore(tmp_path)
    store.put("tokens", "oura", {"access_token": "A", "refresh_token": "R1", "expires_at": 0})
    http = FakeHttp(
        [(400, {"error": "invalid_grant"}), (200, {"access_token": "D", "refresh_token": "R4", "expires_in": 86400})]
    )
    real_post = http.post

    def post(*a, **kw):
        resp = real_post(*a, **kw)
        if len(http.posts) == 1:  # someone rotated R1 -> R3 while our call was in flight
            store.put("tokens", "oura", {"access_token": "C", "refresh_token": "R3", "expires_at": 0})
        return resp

    http.post = post
    assert oura.get_access_token(store, http=http, now=lambda: 1_000) == "D"
    assert [p["refresh_token"] for p in http.posts] == ["R1", "R3"]
    assert store.get("tokens", "oura")[0]["refresh_token"] == "R4"


def test_rejected_refresh_uses_rotated_token_if_still_valid(tmp_path):
    store = JsonStore(tmp_path)
    store.put("tokens", "oura", {"access_token": "A", "refresh_token": "R1", "expires_at": 0})
    http = FakeHttp([(401, {})])
    real_post = http.post

    def post(*a, **kw):
        resp = real_post(*a, **kw)
        store.put("tokens", "oura", {"access_token": "C", "refresh_token": "R3", "expires_at": 99_999})
        return resp

    http.post = post
    assert oura.get_access_token(store, http=http, now=lambda: 1_000) == "C"
    assert len(http.posts) == 1


def test_rejected_refresh_unchanged_token_does_not_retry(tmp_path):
    store = JsonStore(tmp_path)
    store.put("tokens", "oura", {"access_token": "A", "refresh_token": "R1", "expires_at": 0})
    http = FakeHttp([(400, {}), (200, {})])
    with pytest.raises(oura.OuraAuthError):
        oura.get_access_token(store, http=http, now=lambda: 1_000)
    assert len(http.posts) == 1


# probe
class FakeGetHttp:
    """`fail` maps collection -> status code (or an exception instance) returned every time;
    `flaky` maps collection -> number of initial 503s before succeeding."""

    def __init__(self, data: dict, fail=None, flaky=None):
        self.data, self.gets = data, []
        self.fail = fail if isinstance(fail, dict) else dict.fromkeys(fail or (), 403)
        self.flaky = dict(flaky or {})

    def get(self, url, params, headers, timeout):
        name = url.rsplit("/", 1)[-1]
        self.gets.append(name)
        status = self.fail.get(name)
        if isinstance(status, Exception):
            raise status
        if status is None and self.flaky.get(name, 0) > 0:
            self.flaky[name] -= 1
            status = 503
        if status:

            def boom(status=status):
                raise requests.HTTPError(f"{status} for {name}")

            return SimpleNamespace(status_code=status, json=lambda: {}, raise_for_status=boom)
        return SimpleNamespace(
            status_code=200, json=lambda: {"data": self.data.get(name, [])}, raise_for_status=lambda: None
        )


def _valid_token_store(tmp_path):
    store = JsonStore(tmp_path)
    store.put("tokens", "oura", {"access_token": "A", "refresh_token": "R", "expires_at": 9e12})
    return store


def test_probe_fetches_workouts_once_and_reports_activities(tmp_path):
    http = FakeGetHttp(
        {
            "workout": [
                {"day": "2026-10-13", "activity": "strength_training", "source": "manual"},
                {"day": "2026-10-14", "activity": "cycling", "source": "autodetected"},
            ],
            "daily_sleep": [{"day": "2026-10-12", "score": 70, "id": "x"}],
        }
    )
    report = oura.probe(_valid_token_store(tmp_path), WS, http=http)
    assert http.gets.count("workout") == 1
    assert report["workout"]["activities"] == ["cycling", "strength_training"]
    assert report["workout"]["sources"] == ["autodetected", "manual"]
    assert report["daily_sleep"]["fields"] == ["day", "id", "score"]


def test_probe_survives_workout_error(tmp_path):
    http = FakeGetHttp({}, fail={"workout", "daily_stress"})
    report = oura.probe(_valid_token_store(tmp_path), WS, http=http)
    assert "403" in report["workout"]["error"] and "activities" not in report["workout"]
    assert "403" in report["daily_stress"]["error"]
    assert report["daily_sleep"]["count"] == 0
    assert http.gets.count("workout") == 1


# activity ("exercise") and stress
def test_activity_and_stress_aggregates():
    activity = [
        {"day": "2026-10-12", "score": 60},
        {"day": "2026-10-13", "score": 80},
        {"day": "2026-10-19", "score": 10},
    ]  # next week: excluded
    stress = [
        {"day": f"2026-10-{d}", "day_summary": s}
        for d, s in [
            (12, "restored"),
            (13, "normal"),
            (14, "stressful"),
            (15, "normal"),
            (16, "stressful"),
            (17, None),
            (19, "stressful"),
        ]
    ]
    agg = oura.aggregate_week(WS, [], [], [], activity=activity, stress=stress)
    assert agg["activity_avg"] == 70.0 and agg["activity_days"] == 2
    assert agg["stress_days"] == 5 and agg["stressful_days"] == 2  # None day and next week excluded
    assert agg["stress_calm_pct"] == 60


def test_no_stress_data_is_unknown():
    agg = oura.aggregate_week(WS, [], [], [], activity=[], stress=[{"day": "2026-10-12", "day_summary": None}])
    assert agg["stress_calm_pct"] is None and agg["activity_avg"] is None


def test_pull_week_fetches_all_five_collections(tmp_path):
    http = FakeGetHttp(
        {
            "daily_activity": [{"day": "2026-10-12", "score": 77}],
            "daily_stress": [{"day": "2026-10-12", "day_summary": "normal"}],
        }
    )
    agg = oura.pull_week(_valid_token_store(tmp_path), WS, http=http, sleep=lambda s: None)
    assert sorted(http.gets) == ["daily_activity", "daily_readiness", "daily_sleep", "daily_stress", "workout"]
    assert agg["activity_avg"] == 77.0 and agg["stress_calm_pct"] == 100


# partial failure: unknown, never zero
NO_SLEEP = lambda s: None  # noqa: E731


def test_failed_collection_is_unknown_not_zero(tmp_path):
    http = FakeGetHttp(
        {"daily_sleep": [{"day": "2026-10-12", "score": 70}], "daily_readiness": [{"day": "2026-10-12", "score": 80}]},
        fail={"daily_stress": 403, "workout": 403},
    )
    agg = oura.pull_week(_valid_token_store(tmp_path), WS, http=http, sleep=NO_SLEEP)
    assert agg["sleep_avg"] == 70.0  # other collections still used
    assert agg["stress_calm_pct"] is None and agg["stress_days"] is None
    assert agg["gym_sessions"] is None  # unreadable workouts must not read as 0 sessions
    assert [f.split(":")[0] for f in agg["failed_collections"]] == ["workout", "daily_stress"]


def test_unreadable_readiness_makes_non_wear_unknown(tmp_path):
    http = FakeGetHttp({"daily_sleep": [{"day": "2026-10-12", "score": 70}]}, fail={"daily_readiness": 500})
    agg = oura.pull_week(_valid_token_store(tmp_path), WS, http=http, sleep=NO_SLEEP)
    assert agg["non_wear_days"] is None  # can't count non-wear without both sources


def test_every_collection_failing_raises(tmp_path):
    http = FakeGetHttp({}, fail=dict.fromkeys(oura.COLLECTIONS, 403))
    with pytest.raises(oura.OuraFetchError):
        oura.pull_week(_valid_token_store(tmp_path), WS, http=http, sleep=NO_SLEEP)


def test_failed_workouts_do_not_affect_the_score():
    from tracker.config import Settings
    from tracker.pipeline import build_inputs
    from tracker.scoring import score_week

    agg = oura.aggregate_week(WS, [], [], None)  # workouts unreadable
    assert agg["gym_sessions"] is None  # unknown, not 0 (information only)
    r = score_week(build_inputs(agg, None, {"msg_missed": False}), Settings())
    assert "gym" not in r.segments and not any("gym" in g for g in r.gap_reasons)


# retries
def test_retries_5xx_then_succeeds():
    http, waits = FakeGetHttp({"daily_sleep": [{"day": "2026-10-12", "score": 70}]}, flaky={"daily_sleep": 2}), []
    docs = oura.fetch("daily_sleep", WS, WS, "tok", http, sleep=waits.append)
    assert len(docs) == 1 and http.gets.count("daily_sleep") == 3 and waits == [1, 2]


def test_gives_up_after_max_tries():
    http = FakeGetHttp({}, flaky={"daily_sleep": 10})
    with pytest.raises(requests.HTTPError):
        oura.fetch("daily_sleep", WS, WS, "tok", http, sleep=NO_SLEEP)
    assert http.gets.count("daily_sleep") == oura.MAX_TRIES


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_does_not_retry_4xx(status):
    http = FakeGetHttp({}, fail={"daily_sleep": status})
    with pytest.raises(requests.HTTPError):
        oura.fetch("daily_sleep", WS, WS, "tok", http, sleep=NO_SLEEP)
    assert http.gets.count("daily_sleep") == 1


def test_retries_network_errors():
    http = FakeGetHttp({}, fail={"daily_sleep": requests.ConnectionError("reset")})
    with pytest.raises(requests.ConnectionError):
        oura.fetch("daily_sleep", WS, WS, "tok", http, sleep=NO_SLEEP)
    assert http.gets.count("daily_sleep") == oura.MAX_TRIES


def test_429_is_retried():
    http = FakeGetHttp({}, fail={"daily_sleep": 429})
    with pytest.raises(requests.HTTPError):
        oura.fetch("daily_sleep", WS, WS, "tok", http, sleep=NO_SLEEP)
    assert http.gets.count("daily_sleep") == oura.MAX_TRIES


def test_requests_use_connect_read_timeout_tuple():
    seen = []
    http = FakeGetHttp({})
    real = http.get
    http.get = lambda url, params, headers, timeout: (seen.append(timeout), real(url, params, headers, timeout))[1]
    oura.fetch("daily_sleep", WS, WS, "tok", http)
    assert seen == [oura.TIMEOUT] and len(oura.TIMEOUT) == 2


def test_gym_days_counts_distinct_days():
    workouts = [
        {"day": "2026-10-13", "activity": "strength_training"},
        {"day": "2026-10-13", "activity": "strength_training"},  # same day: one gym day
        {"day": "2026-10-15", "activity": "strength_training"},
        {"day": "2026-10-16", "activity": "cycling"},
    ]
    agg = oura.aggregate_week(WS, [], [], workouts, gym_activities={"strength_training"})
    assert agg["gym_sessions"] == 3 and agg["gym_days"] == 2
    assert oura.aggregate_week(WS, [], [], None)["gym_days"] is None  # unreadable: unknown
