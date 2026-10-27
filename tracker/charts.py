"""Time-split charts: a pie for the latest week and a bar per week, as SVG or an HTML page."""

from __future__ import annotations

import math
from datetime import date
from html import escape

from tracker.timesplit import BUCKETS

LABELS = {"work": "Work", "social": "Social", "personal": "Personal", "unplanned": "Unplanned"}

# Literal colours for the static README SVG (light theme).
LIGHT = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "muted": "#898781",
    "work": "#2a78d6",
    "social": "#eb6834",
    "personal": "#1baf7a",
    "unplanned": "#c3c2b7",
    "on_fill": "#ffffff",
    "on_neutral": "#0b0b0b",
}
# CSS-variable colours for the HTML page (light/dark swap in one place).
CSS_VARS = {k: f"var(--{k.replace('_', '-')})" for k in LIGHT}

MIN_LABEL_SHARE = 0.09  # direct labels only where they fit
BAR_H, BAR_GAP_Y, GAP = 22, 14, 2


def _shares(split: dict) -> list[tuple[str, float]]:
    """(bucket, hours) for tracked buckets with time, in fixed order."""
    return [(b, split[b]) for b in BUCKETS if split.get(b)]


def _week_label(ws: str) -> str:
    return f"{date.fromisoformat(ws):%-d %b}"


def _pct(h: float, total: float) -> str:
    return f"{round(100 * h / total)}%"


def _tip(ws: str, bucket: str, hours: float, total: float) -> str:
    return escape(f"Week of {_week_label(ws)} · {LABELS[bucket]}: {hours:g} h ({_pct(hours, total)})")


def pie(ws: str, split: dict, c: dict, cx: float, cy: float, r: float) -> str:
    parts = _shares(split)
    total = sum(h for _, h in parts)
    if not total:
        return ""
    out, angle = [], -math.pi / 2
    for b, h in parts:
        sweep = 2 * math.pi * h / total
        a0, a1 = angle, angle + sweep
        if sweep >= 2 * math.pi - 1e-9:  # a single bucket: full circle
            shape = f'<circle cx="{cx}" cy="{cy}" r="{r}"'
        else:
            x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            large = 1 if sweep > math.pi else 0
            d = f"M{cx:.1f},{cy:.1f} L{x0:.1f},{y0:.1f} A{r},{r} 0 {large} 1 {x1:.1f},{y1:.1f} Z"
            shape = f'<path d="{d}"'
        # Surface-coloured stroke = the 2px gap between slices.
        out.append(
            f'{shape} fill="{c[b]}" stroke="{c["surface"]}" stroke-width="{GAP}" stroke-linejoin="round">'
            f"<title>{_tip(ws, b, h, total)}</title></{'circle' if shape.startswith('<circle') else 'path'}>"
        )
        if h / total >= MIN_LABEL_SHARE:
            mid = (a0 + a1) / 2
            lx, ly = cx + 0.62 * r * math.cos(mid), cy + 0.62 * r * math.sin(mid)
            ink = c["on_neutral"] if b == "unplanned" else c["on_fill"]
            out.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" fill="{ink}" font-size="13" font-weight="600" '
                f'text-anchor="middle" dominant-baseline="central" pointer-events="none">{_pct(h, total)}</text>'
            )
        angle = a1
    return "\n".join(out)


def bars(weeks: list[tuple[str, dict]], c: dict, x: float, y: float, w: float) -> tuple[str, float]:
    """One 100% stacked bar per week. Returns (svg, height used)."""
    label_w = 56
    out, row_y = [], y
    for ws, split in weeks:
        parts = _shares(split)
        total = sum(h for _, h in parts)
        out.append(
            f'<text x="{x}" y="{row_y + BAR_H / 2:.1f}" fill="{c["ink2"]}" font-size="12" '
            f'dominant-baseline="central">{_week_label(ws)}</text>'
        )
        bx, avail = x + label_w, w - label_w
        usable = avail - GAP * (len(parts) - 1)
        for i, (b, h) in enumerate(parts):
            seg = usable * h / total
            last = i == len(parts) - 1
            if last:  # 4px rounded data-end, square at the baseline
                rr = min(4, seg / 2)
                d = (
                    f"M{bx:.1f},{row_y} h{seg - rr:.1f} a{rr},{rr} 0 0 1 {rr},{rr} v{BAR_H - 2 * rr} "
                    f"a{rr},{rr} 0 0 1 {-rr},{rr} h{-(seg - rr):.1f} Z"
                )
            else:
                d = f"M{bx:.1f},{row_y} h{seg:.1f} v{BAR_H} h{-seg:.1f} Z"
            out.append(f'<path d="{d}" fill="{c[b]}"><title>{_tip(ws, b, h, total)}</title></path>')
            if h / total >= MIN_LABEL_SHARE and seg >= 34:
                ink = c["on_neutral"] if b == "unplanned" else c["on_fill"]
                out.append(
                    f'<text x="{bx + seg / 2:.1f}" y="{row_y + BAR_H / 2:.1f}" fill="{ink}" font-size="11" '
                    f'font-weight="600" text-anchor="middle" dominant-baseline="central" '
                    f'pointer-events="none">{_pct(h, total)}</text>'
                )
            bx += seg + GAP
        row_y += BAR_H + BAR_GAP_Y
    return "\n".join(out), row_y - y


def legend(c: dict, x: float, y: float, buckets: list[str]) -> str:
    out, lx = [], x
    for b in buckets:
        out.append(f'<rect x="{lx}" y="{y - 5}" width="10" height="10" rx="2" fill="{c[b]}"/>')
        out.append(
            f'<text x="{lx + 15}" y="{y}" fill="{c["ink2"]}" font-size="12" dominant-baseline="central">'
            f"{LABELS[b]}</text>"
        )
        lx += 15 + 6.6 * len(LABELS[b]) + 20
    return "\n".join(out)


def _busy_text(w: dict | None, short: bool = False) -> str:
    """'Booked 55% · balanced' (+ packed days), or '' when unknown."""
    if not w or w.get("booked_pct") is None:
        return ""
    if short:
        return f"{w['booked_pct']}% · {w['busy_band']}"
    pd = w.get("packed_days")
    extra = f" · {pd} packed day{'s' if pd != 1 else ''}" if pd else ""
    return f"Booked {w['booked_pct']}% · {w['busy_band']}{extra}"


def time_split_svg(
    weeks: list[tuple[str, dict]], c: dict = LIGHT, width: int = 560, busy: dict[str, dict] | None = None
) -> str:
    """Pie (latest week) + stacked bars (all weeks). `weeks` oldest first; None splits skipped.

    `busy` (optional) maps week -> watch metrics; adds the busyness label per week."""
    busy = busy or {}
    weeks = [(ws, s) for ws, s in weeks if s]
    if not weeks:
        return ""
    latest_ws, latest = weeks[-1]
    shown = [b for b in BUCKETS if any(s.get(b) for _, s in weeks)]
    r, pad = 92, 16
    body = [
        f'<text x="{pad}" y="24" fill="{c["ink"]}" font-size="15" font-weight="600">'
        f"Week of {_week_label(latest_ws)}</text>",
        f'<text x="{width - pad}" y="24" fill="{c["ink2"]}" font-size="12" text-anchor="end">'
        f"{escape(_busy_text(busy.get(latest_ws)))}</text>",
        legend(c, pad, 50, shown),
        pie(latest_ws, latest, c, width / 2, 76 + r, r),
    ]
    bars_y = 76 + 2 * r + 40
    body.append(f'<text x="{pad}" y="{bars_y - 14}" fill="{c["ink"]}" font-size="13" font-weight="600">By week</text>')
    tag_w = 96 if any(_busy_text(busy.get(ws)) for ws, _ in weeks) else 0
    svg_bars, used = bars(weeks, c, pad, bars_y, width - 2 * pad - tag_w)
    body.append(svg_bars)
    if tag_w:
        for i, (ws, _) in enumerate(weeks):
            ty = bars_y + i * (BAR_H + BAR_GAP_Y) + BAR_H / 2
            body.append(
                f'<text x="{width - pad}" y="{ty:.1f}" fill="{c["ink2"]}" font-size="11" text-anchor="end" '
                f'dominant-baseline="central">{escape(_busy_text(busy.get(ws), short=True))}</text>'
            )
    notes = []
    if any(s.get("work") is None for _, s in weeks):
        notes.append("Work not tracked for some weeks: their unplanned time includes work.")
    note_y = bars_y + used + 6
    for i, n in enumerate(notes):
        body.append(f'<text x="{pad}" y="{note_y + 16 * i}" fill="{c["muted"]}" font-size="11">{escape(n)}</text>')
    height = note_y + 16 * len(notes) + pad
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height:.0f}" width="100%" '
        f'role="img" aria-label="Time split by week" font-family="system-ui, -apple-system, Segoe UI, sans-serif">'
        f'<rect width="{width}" height="{height:.0f}" fill="{c["surface"]}" rx="8"/>\n' + "\n".join(body) + "\n</svg>"
    )


def _table(weeks: list[tuple[str, dict]], busy: dict[str, dict] | None = None) -> str:
    busy = busy or {}
    head = (
        "".join(f"<th>{LABELS[b]} (h)</th>" for b in BUCKETS) + "<th>Booked</th><th>Busyness</th><th>Packed days</th>"
    )
    rows = []
    for ws, s in weeks:
        if not s:
            continue
        cells = "".join(f"<td>{'not tracked' if s.get(b) is None else f'{s[b]:g}'}</td>" for b in BUCKETS)
        w = busy.get(ws) or {}
        pct = "-" if w.get("booked_pct") is None else f"{w['booked_pct']}%"
        band = w.get("busy_band") or "-"
        pd = "-" if w.get("packed_days") is None else w["packed_days"]
        cells += f"<td>{pct}</td><td>{band}</td><td>{pd}</td>"
        rows.append(f"<tr><th scope='row'>{_week_label(ws)}</th>{cells}</tr>")
    return f"<table><thead><tr><th>Week</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


_DARK = {
    "surface": "#1a1a19",
    "ink": "#f0efec",
    "ink2": "#c3c2b7",
    "muted": "#898781",
    "work": "#3987e5",
    "social": "#d95926",
    "personal": "#199e70",
    "unplanned": "#4b4a46",
    "on_fill": "#ffffff",
    "on_neutral": "#f0efec",
}


def _vars(c: dict) -> str:
    return "".join(f"--{k.replace('_', '-')}:{v};" for k, v in c.items())


def time_split_page(weeks: list[tuple[str, dict]], busy: dict[str, dict] | None = None, band: str = "") -> str:
    """Standalone HTML page (light/dark) with the chart and a table view."""
    svg = time_split_svg(weeks, CSS_VARS, busy=busy)
    if not svg:
        svg = "<p>No calendar data yet. Run <code>pull</code> for a week first.</p>"
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Time split</title>
<style>
:root {{ color-scheme: light; {_vars(LIGHT)} --page:#f9f9f7; --line:#e1e0d9; }}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{ color-scheme: dark; {_vars(_DARK)} --page:#0d0d0d; --line:#2c2c2a; }}
}}
:root[data-theme="dark"] {{ color-scheme: dark; {_vars(_DARK)} --page:#0d0d0d; --line:#2c2c2a; }}
body {{ margin:0; padding:16px; background:var(--page); color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:600px; margin:0 auto; }}
h1 {{ font-size:18px; margin:4px 0 4px; }}
p.sub {{ color:var(--ink2); font-size:13px; margin:0 0 12px; }}
details {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; margin-top:16px; font-size:13px;
  font-variant-numeric:tabular-nums; }}
th, td {{ padding:6px 4px; border-bottom:1px solid var(--line); text-align:right; }}
th:first-child, td:first-child {{ text-align:left; white-space:nowrap; }}
thead th {{ color:var(--ink2); font-weight:600; }}
</style></head>
<body><main>
<h1>Time split</h1>
<p class="sub">Calendar time per week. Unplanned = waking hours with nothing in the calendar.
Information only: not part of the score. {escape(band)}</p>
{svg}
<details><summary>Table view</summary>{_table(weeks, busy)}</details>
</main></body></html>
"""
