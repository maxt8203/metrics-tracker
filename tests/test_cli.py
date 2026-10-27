import pytest

from tracker.cli import parse_screen_time


@pytest.mark.parametrize("raw,expected", [("", None), (" ", None), ("3", 3.0), ("3.46", 3.5), ("2h", 2.0), ("0", 0.0)])
def test_valid_screen_time(raw, expected):
    assert parse_screen_time(raw) == expected


@pytest.mark.parametrize("raw", ["-1", "25", "lots", "3x"])
def test_invalid_screen_time_rejected(raw):
    with pytest.raises(ValueError):
        parse_screen_time(raw)
