"""Oura API v2: OAuth login, token refresh and weekly aggregates.

Refresh tokens are single-use, so a new one is saved before anything else."""

from __future__ import annotations

import time
from collections import Counter
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

import requests

from tracker import config
from tracker.store import ConcurrencyError, Store
from tracker.week import week_days

TOKEN_KEY = "oura"
EXPIRY_MARGIN_S = 120


class OuraAuthError(RuntimeError):
    pass


def _client() -> tuple[str, str, str]:
    cid, secret = config.env("OURA_CLIENT_ID"), config.env("OURA_CLIENT_SECRET")
    if not cid or not secret:
        raise OuraAuthError("OURA_CLIENT_ID / OURA_CLIENT_SECRET not set in .env")
    return cid, secret, config.env("OURA_REDIRECT_URI", "http://localhost:8080/callback")


def authorize_url(state: str) -> str:
    cid, _, redirect = _client()
    q = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": redirect,
        "scope": " ".join(config.OURA_SCOPES),
        "state": state,
    }
    return f"{config.OURA_AUTHORIZE_URL}?{urlencode(q)}"


def _token_record(resp: dict, now: float) -> dict:
    if "refresh_token" not in resp or "access_token" not in resp:
        raise OuraAuthError(f"unexpected token response keys: {sorted(resp)}")
    return {
        "access_token": resp["access_token"],
        "refresh_token": resp["refresh_token"],
        "expires_at": now + int(resp.get("expires_in", 0)),
        "scope": resp.get("scope"),
    }


def exchange_code(store: Store, code: str, http=requests, now=time.time) -> None:
    cid, secret, redirect = _client()
    r = http.post(
        config.OURA_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": cid,
            "client_secret": secret,
        },
        timeout=30,
    )
    r.raise_for_status()
    _, etag = store.get("tokens", TOKEN_KEY)
    store.put("tokens", TOKEN_KEY, _token_record(r.json(), now()), if_match=etag)


def login(store: Store) -> None:
    from tracker.sources.oauth_local import capture_code, new_state

    state = new_state()
    code = capture_code(authorize_url(state), _client()[2], state)
    exchange_code(store, code)


def get_access_token(store: Store, http=requests, now=time.time) -> str:
    """Return a valid access token, refreshing it if needed.

    If the refresh is rejected because another run already rotated the token,
    retry once with the stored one."""
    tok, etag = store.get("tokens", TOKEN_KEY)
    if not tok:
        raise OuraAuthError("no Oura token stored - run `python -m tracker.cli auth oura`")
    cid, secret, _ = _client()

    for attempt in range(2):
        if tok["expires_at"] - EXPIRY_MARGIN_S > now():
            return tok["access_token"]
        r = http.post(
            config.OURA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": tok["refresh_token"],
                "client_id": cid,
                "client_secret": secret,
            },
            timeout=30,
        )
        if r.status_code in (400, 401):
            used = tok["refresh_token"]
            tok, etag = store.get("tokens", TOKEN_KEY)
            if attempt == 0 and tok and tok["refresh_token"] != used:
                continue  # someone else rotated it; use theirs
            raise OuraAuthError("refresh rejected - token lost, re-run `python -m tracker.cli auth oura`")
        r.raise_for_status()
        new = _token_record(r.json(), now())
        try:
            store.put("tokens", TOKEN_KEY, new, if_match=etag)  # persist before any other call
        except ConcurrencyError:
            stored, _ = store.get("tokens", TOKEN_KEY)
            return stored["access_token"]
        return new["access_token"]
    raise OuraAuthError("refresh failed after retry")  # unreachable; keeps the type checker honest


TIMEOUT = (5, 30)  # (connect, read) seconds
MAX_TRIES = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Collections pulled each week, and the aggregate fields each one feeds.
COLLECTIONS = ("daily_sleep", "daily_readiness", "workout", "daily_activity", "daily_stress")


class OuraFetchError(RuntimeError):
    """Every collection failed: an empty result would read as 'no data recorded'."""


def _get(http, url: str, params: dict, token: str, sleep=time.sleep):
    """GET with backoff on network errors, 429 and 5xx. Other 4xx fail at once:
    retrying a rejection only repeats it."""
    for attempt in range(1, MAX_TRIES + 1):
        try:
            r = http.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == MAX_TRIES:
                raise
        else:
            if getattr(r, "status_code", 200) not in RETRYABLE_STATUS or attempt == MAX_TRIES:
                r.raise_for_status()
                return r
        sleep(2 ** (attempt - 1))  # 1s, 2s
    raise AssertionError("unreachable")


def fetch(collection: str, start: date, end: date, token: str, http=requests, sleep=time.sleep) -> list[dict]:
    """All documents in `collection` between start and end (pagination handled)."""
    url = f"{config.OURA_API_BASE}/{collection}"
    params: dict[str, Any] = {"start_date": start.isoformat(), "end_date": end.isoformat()}
    out: list[dict] = []
    while True:
        body = _get(http, url, params, token, sleep).json()
        out += body.get("data", [])
        nxt = body.get("next_token")
        if not nxt:
            return out
        params = {**params, "next_token": nxt}


def _day(doc: dict) -> str | None:
    return doc.get("day") or (doc.get("start_datetime") or "")[:10] or None


def _in_week(docs: list[dict], ws: date) -> list[dict]:
    days = {d.isoformat() for d in week_days(ws)}
    return [d for d in docs if _day(d) in days]


# TODO: check the real day_summary values with probe-oura.
STRESSFUL = "stressful"


def aggregate_week(
    ws: date,
    sleep: list[dict] | None,
    readiness: list[dict] | None,
    workouts: list[dict] | None,
    activity: list[dict] | None = None,
    stress: list[dict] | None = None,
    gym_activities: set[str] | None = None,
) -> dict:
    """Weekly averages and counts. A collection passed as None couldn't be read,
    so its fields come back None."""
    gym_activities = gym_activities if gym_activities is not None else config.OURA_GYM_ACTIVITIES

    def week(docs):
        return None if docs is None else _in_week(docs, ws)

    def scored(docs):
        return None if docs is None else [d for d in docs if d.get("score") is not None]

    def avg(docs):
        docs = scored(docs)
        return round(sum(d["score"] for d in docs) / len(docs), 1) if docs else None

    def count(docs):
        docs = scored(docs)
        return None if docs is None else len(docs)

    sleep, readiness, workouts = week(sleep), week(readiness), week(workouts)
    activity, stress = week(activity), week(stress)

    # Can't count non-wear days unless both sleep and readiness were read.
    non_wear = None
    if sleep is not None and readiness is not None:
        non_wear = 7 - len({_day(d) for d in scored(sleep) + scored(readiness)})

    gym_sessions = gym_days = activities = None
    if workouts is not None:
        activities = dict(Counter(str(w.get("activity", "unknown")).lower() for w in workouts))
        gym_sessions = sum(n for a, n in activities.items() if a in gym_activities)
        # Two sessions on one day are one gym day.
        gym_days = len({_day(w) for w in workouts if str(w.get("activity", "")).lower() in gym_activities})

    stress_days = stressful = calm_pct = None
    if stress is not None:
        summaries = [str(d["day_summary"]).lower() for d in stress if d.get("day_summary")]
        stress_days, stressful = len(summaries), sum(1 for x in summaries if x == STRESSFUL)
        calm_pct = round((stress_days - stressful) / stress_days * 100) if stress_days else None

    return {
        "sleep_avg": avg(sleep),
        "readiness_avg": avg(readiness),
        "activity_avg": avg(activity),
        "sleep_days": count(sleep),
        "readiness_days": count(readiness),
        "activity_days": count(activity),
        "non_wear_days": non_wear,
        "stress_days": stress_days,
        "stressful_days": stressful,
        "stress_calm_pct": calm_pct,
        "gym_sessions": gym_sessions,
        "gym_days": gym_days,
        "workout_activities": activities,
    }


def pull_week(store: Store, ws: date, http=None, sleep=time.sleep) -> dict:
    """Pull and aggregate one week. A failed collection leaves its fields
    unknown and is listed in `failed_collections`; if all fail, raise."""
    http = http or requests.Session()  # one connection pool for the run
    token = get_access_token(store, http=http)
    end = ws + timedelta(days=7)  # padded; aggregate_week trims to the week
    docs: dict[str, list[dict] | None] = {}
    failed: list[str] = []
    for name in COLLECTIONS:
        try:
            docs[name] = fetch(name, ws, end, token, http, sleep)
        except requests.RequestException as e:
            docs[name] = None
            failed.append(f"{name}: {e}")
    if len(failed) == len(COLLECTIONS):
        raise OuraFetchError("every Oura collection failed: " + "; ".join(failed))
    agg = aggregate_week(
        ws,
        sleep=docs["daily_sleep"],
        readiness=docs["daily_readiness"],
        workouts=docs["workout"],
        activity=docs["daily_activity"],
        stress=docs["daily_stress"],
    )
    agg["failed_collections"] = failed
    return agg


def probe(store: Store, ws: date, http=requests) -> dict:
    """Field names (not values) per collection, plus distinct workout activities.
    Use this to confirm the real schema before trusting the mapping."""
    token = get_access_token(store, http=http)
    end = ws + timedelta(days=6)
    report: dict[str, Any] = {}
    for name in ("daily_sleep", "daily_readiness", "daily_activity", "daily_stress", "workout"):
        try:
            docs = fetch(name, ws, end, token, http)  # each collection fetched once
        except requests.RequestException as e:
            report[name] = {"error": str(e)}
            continue
        report[name] = {
            "count": len(docs),
            "days": sorted({_day(d) for d in docs if _day(d)}),
            "fields": sorted({k for d in docs for k in d}),
        }
        if name == "daily_stress":
            report[name]["day_summaries"] = sorted({str(d.get("day_summary")) for d in docs})
        if name == "workout":
            report[name]["activities"] = sorted({str(w.get("activity")) for w in docs})
            report[name]["sources"] = sorted({str(w.get("source")) for w in docs})
    return report
