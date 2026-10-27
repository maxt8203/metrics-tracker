import pytest

from tracker.config import Settings
from tracker.store import ConcurrencyError, JsonStore, load_settings, save_settings


@pytest.fixture
def store(tmp_path):
    return JsonStore(tmp_path)


def test_roundtrip(store):
    store.put("weeks", "2026-10-12", {"total": 78})
    value, etag = store.get("weeks", "2026-10-12")
    assert value == {"total": 78} and etag
    assert store.get("weeks", "missing") == (None, None)


def test_etag_mismatch_rejected(store):
    etag1 = store.put("tokens", "oura", {"refresh_token": "a"})
    store.put("tokens", "oura", {"refresh_token": "b"}, if_match=etag1)
    with pytest.raises(ConcurrencyError):
        store.put("tokens", "oura", {"refresh_token": "c"}, if_match=etag1)  # stale
    assert store.get("tokens", "oura")[0] == {"refresh_token": "b"}


def test_if_match_on_missing_record_rejected(store):
    with pytest.raises(ConcurrencyError):
        store.put("tokens", "oura", {}, if_match="nope")


def test_list_sorted(store):
    store.put("weeks", "2026-10-19", {})
    store.put("weeks", "2026-10-12", {})
    assert list(store.list("weeks")) == ["2026-10-12", "2026-10-19"]


def test_unknown_table_rejected(store):
    with pytest.raises(ValueError):
        store.put("nope", "k", {})


def test_settings_default_then_saved(store):
    assert load_settings(store) == Settings()
    save_settings(store, Settings(sleep_target=75))
    assert load_settings(store).sleep_target == 75
