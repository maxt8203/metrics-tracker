from datetime import date

from tracker.pipeline import build_inputs, rescore, save_source
from tracker.store import JsonStore

W1, W2 = date(2026, 10, 12), date(2026, 10, 19)
OURA = {
    "sleep_avg": 72,
    "readiness_avg": 78,
    "activity_avg": 63,
    "stress_calm_pct": 71,
    "gym_sessions": 1,
    "non_wear_days": 0,
}
GCAL = {"activity_types": 0, "social": True}
CHECKIN = {"msg_missed": False, "social_confirm": None}


def test_checkin_social_overrides_calendar():
    assert build_inputs(None, {"social": False}, {"social_confirm": True}).social is True
    assert build_inputs(None, {"social": True}, {"social_confirm": None}).social is True
    assert build_inputs(None, None, None).social is None


def test_end_to_end_six_segments(tmp_path):
    store = JsonStore(tmp_path)
    save_source(store, W1, "oura", OURA)
    save_source(store, W1, "gcal", GCAL)
    store.put("checkins", W1.isoformat(), CHECKIN)
    rec = rescore(store, W1)
    assert rec["score"]["segments"] == {
        "sleep": 100,
        "exercise": 90,
        "stress": 100,
        "social": 100,
        "messages": 100,
        "variety": 0,
    }
    assert rec["score"]["total"] == 83 and rec["score"]["status"] == "AMBER"
    assert rec["avg4"] == 83 and rec["checkin_missing"] is False


def test_oura_fields_flow_into_inputs():
    i = build_inputs(OURA, None, None)
    assert (i.sleep_avg, i.activity_avg, i.stress_calm_pct) == (72, 63, 71)


def test_variety_zero_two_weeks_running_turns_red(tmp_path):
    store = JsonStore(tmp_path)
    for ws in (W1, W2):
        save_source(store, ws, "oura", OURA)
        save_source(store, ws, "gcal", GCAL)
        store.put("checkins", ws.isoformat(), CHECKIN)
        rescore(store, ws)
    rec, _ = store.get("weeks", W2.isoformat())
    assert rec["score"]["status"] == "RED"


def test_non_wear_marks_gap(tmp_path):
    store = JsonStore(tmp_path)
    save_source(store, W1, "oura", {**OURA, "non_wear_days": 4})
    store.put("checkins", W1.isoformat(), CHECKIN)
    rec = rescore(store, W1)
    assert rec["score"]["gap_week"] and "oura missing 4 days" in rec["score"]["gap_reasons"]


def test_missing_checkin_flagged(tmp_path):
    store = JsonStore(tmp_path)
    save_source(store, W1, "oura", OURA)
    rec = rescore(store, W1)
    assert rec["checkin_missing"] and "check-in missing" in rec["score"]["gap_reasons"]


# variety = calendar only
def test_variety_from_calendar_categories():
    assert build_inputs(None, {"categories": ["padel", "social", "trip"]}, None).activity_types == 3


def test_oura_never_counts_towards_variety():
    oura = {**OURA, "gym_sessions": 3, "workout_activities": {"strength_training": 3, "cycling": 5}}
    assert build_inputs(oura, {"categories": ["social"]}, None).activity_types == 1


def test_variety_unknown_without_calendar():
    assert build_inputs({"gym_sessions": 3}, None, None).activity_types is None


def test_variety_end_to_end_ignores_oura(tmp_path):
    store = JsonStore(tmp_path)
    save_source(store, W1, "oura", {**OURA, "workout_activities": {"cycling": 6}})
    save_source(store, W1, "gcal", {"categories": ["hobby", "social"], "social": True})
    store.put("checkins", W1.isoformat(), CHECKIN)
    rec = rescore(store, W1)
    assert rec["activity_categories"] == ["hobby", "social"]
    assert rec["score"]["segments"]["variety"] == 50


# gym is information only
def test_gym_sessions_never_change_the_score(tmp_path):
    a, b = JsonStore(tmp_path / "a"), JsonStore(tmp_path / "b")
    for store, gym in ((a, 0), (b, 5)):
        save_source(store, W1, "oura", {**OURA, "gym_sessions": gym})
        save_source(store, W1, "gcal", GCAL)
        store.put("checkins", W1.isoformat(), CHECKIN)
    assert rescore(a, W1)["score"] == rescore(b, W1)["score"]
    assert rescore(b, W1)["oura"]["gym_sessions"] == 5  # still recorded


# watch metrics and time split: shown, never scored
def test_watch_metrics_never_change_the_score(tmp_path):
    a, b = JsonStore(tmp_path / "a"), JsonStore(tmp_path / "b")
    for store, (gym, screen) in ((a, (0, 9.0)), (b, (5, 1.0))):
        save_source(store, W1, "oura", {**OURA, "gym_days": gym})
        save_source(store, W1, "gcal", GCAL)
        store.put("checkins", W1.isoformat(), {**CHECKIN, "screen_time_h": screen})
    ra, rb = rescore(a, W1), rescore(b, W1)
    assert ra["score"] == rb["score"]
    assert (rb["watch"]["gym_days"], rb["watch"]["screen_time_h"]) == (5, 1.0)


def test_watch_missing_is_none():
    from tracker.pipeline import watch_metrics

    assert set(watch_metrics(None, None).values()) == {None}


def test_time_split_stored_and_never_scored(tmp_path):
    gcal = {**GCAL, "scheduled_min": {"work": 2400, "social": 600, "personal": 720}, "work_tracked": True}
    a, b = JsonStore(tmp_path / "a"), JsonStore(tmp_path / "b")
    for store, g in ((a, GCAL), (b, gcal)):
        save_source(store, W1, "oura", OURA)
        save_source(store, W1, "gcal", g)
        store.put("checkins", W1.isoformat(), CHECKIN)
    ra, rb = rescore(a, W1), rescore(b, W1)
    assert ra["time_split"] is None  # calendar pulled before the split existed: unknown
    assert rb["time_split"] == {"work": 40.0, "social": 10.0, "personal": 12.0, "unplanned": 50.0}
    assert ra["score"] == rb["score"]


def test_busyness_in_watch_and_never_scored(tmp_path):
    week_min = {"work": 2400, "social": 600, "personal": 720}  # 62 h booked of 112 waking -> 55%
    by_day = [600, 600, 600, 600, 840, 0, 0]  # Fri: 14 h booked -> 2 h free: not packed (needs < 2)
    gcal = {**GCAL, "scheduled_min": week_min, "booked_by_day_min": by_day, "work_tracked": True}
    store = JsonStore(tmp_path)
    save_source(store, W1, "oura", OURA)
    save_source(store, W1, "gcal", gcal)
    store.put("checkins", W1.isoformat(), CHECKIN)
    rec = rescore(store, W1)
    assert (rec["watch"]["booked_pct"], rec["watch"]["busy_band"], rec["watch"]["packed_days"]) == (
        55,
        "balanced",
        0,
    )


def test_busyness_unknown_without_work_calendar(tmp_path):
    gcal = {**GCAL, "scheduled_min": {"work": 0, "social": 600, "personal": 720}, "work_tracked": False}
    store = JsonStore(tmp_path)
    save_source(store, W1, "gcal", gcal)
    rec = rescore(store, W1)
    assert rec["watch"]["booked_pct"] is None and rec["watch"]["busy_band"] is None
