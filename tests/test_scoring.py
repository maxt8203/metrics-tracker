import pytest

from tracker.config import SEGMENTS, Settings
from tracker.scoring import WeekInputs, rolling_avg, score_week

PERFECT = dict(sleep_avg=80, activity_avg=80, stress_calm_pct=100, social=True, msg_missed=False, activity_types=4)


def week(**kw) -> WeekInputs:
    return WeekInputs(**{**PERFECT, **kw})


# Oura segments: low goals (70)
@pytest.mark.parametrize("value,expected", [(70, 100), (85, 100), (63, 90), (35, 50), (0, 0)])
def test_sleep_vs_target_70(value, expected):
    assert score_week(week(sleep_avg=value), Settings()).segments["sleep"] == expected


@pytest.mark.parametrize("value,expected", [(70, 100), (56, 80), (14, 20)])
def test_exercise_is_activity_score_vs_target_70(value, expected):
    assert score_week(week(activity_avg=value), Settings()).segments["exercise"] == expected


@pytest.mark.parametrize("calm_pct,expected", [(100, 100), (71, 100), (57, 81), (0, 0)])
def test_stress_is_calm_day_share_vs_target_70(calm_pct, expected):
    # 71% ~ 5 of 7 days not stressful; 57% ~ 4 of 7
    assert score_week(week(stress_calm_pct=calm_pct), Settings()).segments["stress"] == expected


def test_sleep_averages_sleep_and_readiness():
    assert score_week(week(sleep_avg=60, readiness_avg=66), Settings()).segments["sleep"] == 90  # 63/70
    assert score_week(week(sleep_avg=60, readiness_avg=90), Settings()).segments["sleep"] == 100  # 75/70


def test_sleep_uses_whichever_score_exists():
    assert score_week(week(sleep_avg=None, readiness_avg=56), Settings()).segments["sleep"] == 80
    r = score_week(week(sleep_avg=None, readiness_avg=None), Settings())
    assert r.segments["sleep"] is None and "sleep unknown" in r.gap_reasons


def test_targets_are_settings():
    s = Settings(sleep_target=80, exercise_target=60, stress_target=50)
    r = score_week(week(sleep_avg=72, activity_avg=60, stress_calm_pct=50), s)
    assert (r.segments["sleep"], r.segments["exercise"], r.segments["stress"]) == (90, 100, 100)


def test_target_zero_guard():
    assert score_week(week(sleep_avg=10), Settings(sleep_target=0)).segments["sleep"] == 100


# totals and status
def test_default_weights_cover_six_segments_and_sum_to_100():
    s = Settings()
    assert tuple(s.weights) == SEGMENTS and sum(s.weights.values()) == 100


def test_perfect_week_is_green():
    r = score_week(week(), Settings())
    assert r.total == 100 and r.status == "GREEN" and not r.gap_week


def test_weighted_total():
    # sleep 100*15, exercise 90*20, stress 100*15, social 100*25, messages 100*10, variety 0*15 = 8300
    r = score_week(week(sleep_avg=72, activity_avg=63, stress_calm_pct=71, activity_types=0), Settings())
    assert r.total == 83 and r.status == "AMBER"


def test_any_zero_segment_is_amber_even_with_high_total():
    r = score_week(week(msg_missed=True), Settings())
    assert r.total == 90 and r.status == "AMBER"


def test_same_segment_zero_two_weeks_is_red():
    i = week(social=False)
    prev = score_week(i, Settings())
    assert prev.status == "AMBER" and score_week(i, Settings(), prev=prev).status == "RED"


def test_stress_zero_two_weeks_is_red():
    i = week(stress_calm_pct=0)
    assert score_week(i, Settings(), prev=score_week(i, Settings())).status == "RED"


def test_total_below_amber_is_red():
    i = week(sleep_avg=30, activity_avg=30, stress_calm_pct=20, social=False, activity_types=1)
    assert score_week(i, Settings()).status == "RED"


def test_green_threshold_default_is_90():
    r = score_week(week(activity_avg=56, activity_types=3), Settings())  # exercise 80, variety 75
    assert r.total == 92 and r.status == "GREEN"
    r = score_week(week(activity_avg=35, activity_types=3), Settings())  # exercise 50, variety 75
    assert r.total == 86 and r.status == "AMBER"


# gym is not scored
def test_gym_is_not_a_segment():
    # A week without gym can be a good week, so gym never affects the score.
    assert "gym" not in SEGMENTS and "gym" not in Settings().weights
    assert "gym" not in score_week(week(), Settings()).segments


# missing data
def test_missing_checkin_is_gap_not_zero():
    r = score_week(week(msg_missed=None), Settings())
    assert r.segments["messages"] is None and "check-in missing" in r.gap_reasons
    assert r.total == 100 and r.status == "AMBER"  # rescaled total, but a gap is never GREEN


def test_missing_stress_data_is_unknown_not_zero():
    r = score_week(week(stress_calm_pct=None), Settings())
    assert r.segments["stress"] is None and "stress unknown" in r.gap_reasons and r.status == "AMBER"


def test_no_inputs_is_gap_with_no_total():
    r = score_week(WeekInputs(), Settings())
    assert r.total is None and r.status == "NO_DATA" and r.gap_reasons == ["no inputs"]


def test_non_wear_gap_detected():
    r = score_week(week(non_wear_days=3), Settings())
    assert r.gap_reasons == ["oura missing 3 days"] and r.status == "AMBER"


def test_non_wear_below_threshold_is_not_a_gap():
    r = score_week(week(non_wear_days=2), Settings())
    assert not r.gap_week and r.status == "GREEN"


def test_non_wear_threshold_is_a_setting():
    assert score_week(week(non_wear_days=2), Settings(non_wear_gap_days=2)).gap_week


def test_gap_week_does_not_soften_red():
    i = week(
        sleep_avg=30,
        activity_avg=30,
        stress_calm_pct=20,
        social=False,
        activity_types=1,
        msg_missed=None,
    )
    assert score_week(i, Settings()).status == "RED"


# settings validation
@pytest.mark.parametrize(
    "weights",
    [
        {"sleep": 25, "exercise": 20, "stress": 15, "social": 25, "messages": 10, "variety": 15},  # sums to 110
        {"sleep": 15, "exercise": 10, "stress": 15, "gym": 10, "social": 25, "messages": 10, "variety": 15},  # old
        {"health": 40, "gym": 10, "social": 25, "messages": 10, "variety": 15},  # older
    ],
)
def test_invalid_weights_rejected(weights):
    with pytest.raises(ValueError):
        Settings(weights=weights).validate()


def test_rolling_avg_skips_unknown_and_uses_last_four():
    assert rolling_avg([10, 100, 80, None, 60, 70]) == 70
    assert rolling_avg([None, None]) is None
    assert rolling_avg([68]) == 68


def test_busy_band_must_be_ordered():
    with pytest.raises(ValueError):
        Settings(busy_low_pct=80, busy_high_pct=60).validate()
