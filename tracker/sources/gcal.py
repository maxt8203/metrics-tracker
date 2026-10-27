"""Google Calendar: read the week's events and sort them into categories.

Order: work/social calendar -> keywords -> cached AI answers -> AI call.
Note: keep the OAuth app "In production", or refresh tokens expire after 7 days."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from tracker import config
from tracker.store import Store
from tracker.week import week_bounds, week_key

TOKEN_KEY = "gcal"


def _client_config() -> dict:
    path = Path(config.env("GOOGLE_CLIENT_SECRET_FILE", "client_secret.json"))
    if not path.exists():
        raise FileNotFoundError(f"Google OAuth client file not found: {path}")
    return json.loads(path.read_text())


def login(store: Store) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(_client_config(), config.GCAL_SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        raise RuntimeError("Google returned no refresh token; revoke the app's access and retry")
    _, etag = store.get("tokens", TOKEN_KEY)
    store.put("tokens", TOKEN_KEY, {"refresh_token": creds.refresh_token}, if_match=etag)


def _service(store: Store):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    tok, _ = store.get("tokens", TOKEN_KEY)
    if not tok:
        raise RuntimeError("no Google token stored - run `python -m tracker.cli auth gcal`")
    c = _client_config().get("installed") or _client_config().get("web")
    creds = Credentials(
        token=None,
        refresh_token=tok["refresh_token"],
        token_uri=c["token_uri"],
        client_id=c["client_id"],
        client_secret=c["client_secret"],
        scopes=config.GCAL_SCOPES,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _parse(ts: dict) -> datetime:
    if "dateTime" in ts:
        return datetime.fromisoformat(ts["dateTime"].replace("Z", "+00:00"))
    return datetime.combine(date.fromisoformat(ts["date"]), datetime.min.time())


def normalise(raw: dict, calendar_id: str) -> dict:
    start, end = _parse(raw["start"]), _parse(raw["end"])
    return {
        "id": raw["id"],
        "title": raw.get("summary", ""),
        "start": start.isoformat(),
        "duration_min": int((end - start).total_seconds() // 60),
        "all_day": "date" in raw["start"],
        "calendar_id": calendar_id,
    }


def list_events(store: Store, ws: date) -> list[dict]:
    svc = _service(store)
    start, end = week_bounds(ws)
    cal_ids = [c.strip() for c in config.env("GCAL_CALENDAR_IDS", "primary").split(",") if c.strip()]
    for extra in (config.env("GCAL_SOCIAL_CALENDAR_ID"), config.env("GCAL_WORK_CALENDAR_ID")):
        if extra and extra not in cal_ids:
            cal_ids.append(extra)
    events: list[dict] = []
    for cal in cal_ids:
        page = None
        while True:
            resp = (
                svc.events()
                .list(
                    calendarId=cal,
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page,
                )
                .execute()
            )
            events += [normalise(e, cal) for e in resp.get("items", []) if e.get("status") != "cancelled"]
            page = resp.get("nextPageToken")
            if not page:
                break
    return events


def classify(
    events: list[dict],
    keywords=None,
    social_calendar_id: str | None = None,
    work_calendar_id: str | None = None,
) -> list[dict]:
    """Set category and source from the calendar or keywords; None if unmatched."""
    keywords = keywords if keywords is not None else config.KEYWORDS
    out = []
    for e in events:
        title = e["title"].lower()
        cat, src = None, None
        if work_calendar_id and e.get("calendar_id") == work_calendar_id:
            cat, src = "work", "calendar"
        elif social_calendar_id and e.get("calendar_id") == social_calendar_id:
            cat, src = "social", "calendar"
        else:
            for kw, c in keywords:
                if re.search(rf"\b{re.escape(kw)}\b", title):  # "pub" must not match "public"
                    cat, src = c, "keyword"
                    break
        out.append({**e, "category": cat, "source": src})
    return out


def aggregate(classified: list[dict], ws: date | None = None, work_tracked: bool = False) -> dict:
    """Variety/social aggregates; with `ws`, also scheduled minutes per time-split bucket."""
    from tracker.timesplit import booked_minutes_by_day, scheduled_minutes

    cats = {e["category"] for e in classified if e["category"]}
    chosen = [e for e in classified if e["category"] != "work"]
    extra = {}
    if ws is not None:
        extra = {
            "scheduled_min": scheduled_minutes(classified, ws, config.TIME_EXCLUDE_KEYWORDS),
            "booked_by_day_min": booked_minutes_by_day(classified, ws, config.TIME_EXCLUDE_KEYWORDS),
            "work_tracked": work_tracked,
        }
    return {
        **extra,
        "activity_types": len(cats - config.VARIETY_EXCLUDED),
        "categories": sorted(cats - config.VARIETY_EXCLUDED),
        "social": "social" in cats,
        "event_count": len(chosen),
        "unmatched": [e["title"] for e in classified if e["category"] is None],
    }


def apply_cache(classified: list[dict], cached: dict[str, dict]) -> list[dict]:
    """Reuse earlier AI answers for still-unmatched events whose title hasn't changed."""
    out = []
    for e in classified:
        hit = cached.get(e["id"])
        if e["category"] is None and hit and hit.get("source") == "ai" and hit.get("title") == e["title"]:
            e = {**e, "category": hit["category"], "source": "ai"}
        out.append(e)
    return out


def resolve(
    events: list[dict],
    cached: dict[str, dict] | None = None,
    *,
    use_ai: bool = True,
    ai_client=None,
    social_calendar_id: str | None = None,
    work_calendar_id: str | None = None,
) -> tuple[list[dict], list[str]]:
    """Calendar presets -> keywords -> cached AI answers -> one AI call for whatever is left."""
    from tracker.sources.classifier import classify_unmatched

    classified = apply_cache(
        classify(events, social_calendar_id=social_calendar_id, work_calendar_id=work_calendar_id), cached or {}
    )
    notes: list[str] = []
    if use_ai:
        res = classify_unmatched(classified, client=ai_client)
        classified = [
            {**e, "category": res.categories[e["id"]], "source": "ai"}
            if e["category"] is None and e["id"] in res.categories
            else e
            for e in classified
        ]
        notes += res.notes
        if res.called:
            notes.append(f"AI classified {len(res.categories)} event(s), tokens {res.usage}")
    return classified, notes


def pull_week(store: Store, ws: date, *, use_ai: bool = True, ai_client=None) -> tuple[dict, list[dict], list[str]]:
    cached, _ = store.get("events", week_key(ws))
    work_cal = config.env("GCAL_WORK_CALENDAR_ID")
    classified, notes = resolve(
        list_events(store, ws),
        cached,
        use_ai=use_ai,
        ai_client=ai_client,
        social_calendar_id=config.env("GCAL_SOCIAL_CALENDAR_ID"),
        work_calendar_id=work_cal,
    )
    store.put("events", week_key(ws), {e["id"]: e for e in classified})  # cache / audit trail
    if not work_cal:
        notes.append("GCAL_WORK_CALENDAR_ID not set: work time shows as not tracked")
    return aggregate(classified, ws, work_tracked=bool(work_cal)), classified, notes
