from tracker.charts import time_split_page, time_split_svg

SPLIT = {"work": 38.0, "social": 9.0, "personal": 14.0, "unplanned": 51.0}


def test_svg_has_pie_bars_legend_and_tooltips():
    svg = time_split_svg([("2026-10-12", SPLIT), ("2026-10-19", SPLIT)])
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert svg.count("<title>") == 4 + 2 * 4  # 4 slices + 4 segments x 2 weeks
    for label in ("Work", "Social", "Personal", "Unplanned", "34%"):
        assert label in svg


def test_skips_weeks_without_data_and_handles_empty():
    assert time_split_svg([("2026-10-12", None)]) == ""
    assert "No calendar data yet" in time_split_page([("2026-10-12", None)])


def test_untracked_work_is_noted_not_drawn():
    svg = time_split_svg([("2026-10-12", {**SPLIT, "work": None})])
    assert "Work not tracked" in svg and ">Work<" not in svg


def test_single_bucket_week_draws_full_circle():
    svg = time_split_svg([("2026-10-12", {"work": None, "social": 0, "personal": 0, "unplanned": 112.0})])
    assert "<circle" in svg


def test_page_has_table_view_and_dark_mode():
    page = time_split_page([("2026-10-12", {**SPLIT, "work": None})])
    assert "<table>" in page and "not tracked" in page and "prefers-color-scheme: dark" in page


def test_busyness_shown_when_given():
    busy = {"2026-10-12": {"booked_pct": 80, "busy_band": "packed", "packed_days": 3}}
    svg = time_split_svg([("2026-10-12", SPLIT)], busy=busy)
    assert "Booked 80% · packed · 3 packed days" in svg and "80% · packed" in svg
    page = time_split_page([("2026-10-12", SPLIT)], busy)
    assert "<td>80%</td><td>packed</td><td>3</td>" in page


def test_busyness_unknown_shows_nothing():
    svg = time_split_svg([("2026-10-12", SPLIT)], busy={"2026-10-12": {"booked_pct": None}})
    assert "Booked" not in svg
