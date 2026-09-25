"""Offline descriptive price audit. Flags are review prompts, not data corrections."""

import math
from html import escape

from senate_market.io import probability, utc


def audit_race(race, history, events, *, jump=0.10, flat_minutes=60, gap_seconds=120):
    if any(not math.isfinite(v) or v <= 0 for v in (jump, flat_minutes, gap_seconds)):
        raise ValueError("Audit thresholds must be positive")
    if race["orientation"] not in {"identity", "complement"}:
        raise ValueError("Unknown probability orientation")
    points = []
    if history is not None:
        if history.get("token_id") != race["token_id"]:
            raise ValueError(f"History token mismatch: {race['race_id']}")
        for point in history["points"]:
            t, p = utc(point["timestamp"]), probability(point["probability"])
            if points and t <= points[-1][0]:
                raise ValueError(f"History timestamps not strictly increasing: {race['race_id']}")
            points.append((t, 1 - p if race["orientation"] == "complement" else p))
    calls = [e for e in events if e["race_id"] == race["race_id"]
             and e["event_type"] == "race_call"]
    jumps, gaps, flats = [], [], []
    run = 0

    def finish_run(end):
        minutes = (points[end][0] - points[run][0]).total_seconds() / 60
        if minutes >= flat_minutes:
            flats.append({"start": points[run][0].isoformat(),
                          "end": points[end][0].isoformat(),
                          "minutes": minutes, "probability": points[run][1]})

    for i in range(1, len(points)):
        t0, p0 = points[i - 1]
        t1, p1 = points[i]
        elapsed = (t1 - t0).total_seconds()
        change = p1 - p0
        if abs(change) >= jump:
            jumps.append({"start": t0.isoformat(), "end": t1.isoformat(),
                          "before": p0, "after": p1, "change": change,
                          "elapsed_seconds": elapsed, "across_gap": elapsed > gap_seconds})
        if elapsed > gap_seconds:
            gaps.append({"start": t0.isoformat(), "end": t1.isoformat(),
                         "seconds": elapsed})
        if p1 != p0 or elapsed > gap_seconds:
            finish_run(i - 1)
            run = i
    if points:
        finish_run(len(points) - 1)
    call_checks = []
    for call in calls:
        t = utc(call["timestamp"])
        before = [p for p in points if p[0] < t]
        pre = before[-1] if before else None
        call_checks.append({"timestamp": t.isoformat(), "result": call["result"],
                            "source_url": call["source_url"],
                            "inside_observed_span": bool(points and points[0][0] <= t
                                                         <= points[-1][0]),
                            "pre_probability": pre[1] if pre else None,
                            "pre_age_seconds": (t - pre[0]).total_seconds() if pre else None})
    summary = {"race_id": race["race_id"], "token_id": race["token_id"],
               "market_id": race["market_id"], "count": len(points),
               "status": "missing_or_unavailable" if history is None else (
                   "observed" if points else "empty"),
               "first": points[0][0].isoformat() if points else None,
               "last": points[-1][0].isoformat() if points else None,
               "min_probability": min((p for _, p in points), default=None),
               "max_probability": max((p for _, p in points), default=None),
               "jumps": jumps, "gaps": gaps, "flat_stretches": flats,
               "calls": call_checks}
    return summary, points


def plot(points, calls, gap_seconds):
    if not points:
        return "<p>No usable price observations.</p>"
    start, end = points[0][0], points[-1][0]
    duration = max((end - start).total_seconds(), 1)

    def x(t):
        return 50 + 900 * (t - start).total_seconds() / duration

    def y(p):
        return 210 - 180 * p

    parts = ['<svg viewBox="0 0 1000 260" role="img" '
             'aria-label="Democratic-win price history; UTC; red dashed AP call">']
    for p in (0, 0.5, 1):
        parts.append(f'<path d="M50 {y(p)} H950" stroke="#ddd"/>'
                     f'<text x="5" y="{y(p) + 4}">{p:.0%}</text>')
    # Points are shown without interpolating across missing intervals. Step lines
    # connect nearby samples for display only; no values are imputed for analysis.
    segment = []
    previous = None
    for t, p in points:
        if previous and (t - previous[0]).total_seconds() > gap_seconds:
            parts.append(f'<path d="{" ".join(segment)}" fill="none" stroke="#1769aa"/>')
            segment = []
        segment.append(f'{"M" if not segment else "H"}{x(t):.2f}'
                       + (f' {y(p):.2f}' if not segment else f' V{y(p):.2f}'))
        previous = (t, p)
    parts.append(f'<path d="{" ".join(segment)}" fill="none" stroke="#1769aa"/>')
    for call in calls:
        t = utc(call["timestamp"])
        if start <= t <= end:
            parts.append(f'<path d="M{x(t):.2f} 20 V215" stroke="#c62828" '
                         'stroke-dasharray="5 4"/>'
                         f'<text x="{min(x(t), 850):.2f}" y="15">AP call</text>')
    for frac in (0, 0.25, 0.5, 0.75, 1):
        t = start + (end - start) * frac
        parts.append(f'<text x="{50 + 900 * frac}" y="240" text-anchor="middle">'
                     f'{t:%m-%d %H:%M}</text>')
    parts.append('</svg>')
    return "".join(parts)


def html_report(report, plotted):
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width, initial-scale=1">'
             '<title>Senate price-history audit</title><style>'
             'body{font:16px system-ui;max-width:1100px;margin:30px auto;padding:0 20px;'
             'color:#202124}section{border-top:1px solid #bbb;margin-top:30px}'
             'svg{width:100%;font:12px system-ui}table{border-collapse:collapse;width:100%}'
             'td,th{text-align:left;padding:6px;border-bottom:1px solid #ddd}'
             'code{overflow-wrap:anywhere}a{color:#1769aa}</style>'
             '<h1>Senate price-history audit</h1>'
             '<p>Offline review of mapped tokens only. All times UTC. Prices are oriented '
             'to the contract-defined Democratic win. Flags do not prove bad data. '
             'No data are changed or excluded by this audit.</p>'
             '<p>Red dashed lines mark AP calls, not settlements or necessarily the first '
             'public call. Blue step lines connect nearby samples for display only; '
             'long sampling gaps are left blank. Flat samples do not prove no trading.</p>',
             f'<p>Thresholds: adjacent change ≥ {report["thresholds"]["jump"]:.0%} '
             '(absolute probability); identical-price stretch ≥ '
             f'{report["thresholds"]["flat_minutes"]} minutes; sampling gap &gt; '
             f'{report["thresholds"]["gap_seconds"]} seconds.</p>',
             '<table><tr><th>Race</th><th>Samples</th><th>Jumps</th>'
             '<th>Flat stretches</th><th>Gaps</th></tr>']
    for r in report["races"]:
        rid = escape(r["race_id"])
        parts.append(f'<tr><td><a href="#{rid}">{rid}</a></td><td>{r["count"]}</td>'
                     f'<td>{len(r["jumps"])}</td><td>{len(r["flat_stretches"])}</td>'
                     f'<td>{len(r["gaps"])}</td></tr>')
    parts.append('</table>')
    for r in report["races"]:
        rid = escape(r["race_id"])
        parts.append(f'<section id="{rid}"><h2>{rid}</h2><p>Market '
                     f'{escape(r["market_id"])} · {r["count"]} samples · '
                     f'{escape(r["status"])}</p><p>Token: <code>{escape(r["token_id"])}</code></p>')
        parts.append(plot(plotted[r["race_id"]], r["calls"],
                          report["thresholds"]["gap_seconds"]))
        if not r["calls"]:
            parts.append('<p>No verified AP-call timestamp supplied.</p>')
        for c in r["calls"]:
            parts.append(f'<p>AP call: {escape(c["timestamp"])}; result={c["result"]}; '
                         f'pre-call sample={c["pre_probability"]}; '
                         f'age={c["pre_age_seconds"]} seconds; '
                         f'inside observed span={c["inside_observed_span"]}.</p>')
        parts.append('<details><summary>Largest adjacent changes (up to 10)</summary><ul>')
        for j in sorted(r["jumps"], key=lambda v: abs(v["change"]), reverse=True)[:10]:
            parts.append(f'<li>{escape(j["end"])}: {j["before"]:.3f} → {j["after"]:.3f}'
                         f' over {j["elapsed_seconds"]:.0f}s; across gap={j["across_gap"]}</li>')
        parts.append('</ul></details>')
        parts.append('<details><summary>Longest flat stretches (up to 10)</summary><ul>')
        for f in sorted(r["flat_stretches"], key=lambda v: v["minutes"], reverse=True)[:10]:
            parts.append(f'<li>{escape(f["start"])} to {escape(f["end"])}: '
                         f'{f["minutes"]:.1f} minutes at {f["probability"]:.3f}</li>')
        parts.append('</ul></details><details><summary>Largest sampling gaps '
                     '(up to 10)</summary><ul>')
        for g in sorted(r["gaps"], key=lambda v: v["seconds"], reverse=True)[:10]:
            parts.append(f'<li>{escape(g["start"])} to {escape(g["end"])}: '
                         f'{g["seconds"]:.0f} seconds</li>')
        parts.append('</ul></details></section>')
    parts.append('</html>')
    return "\n".join(parts)
