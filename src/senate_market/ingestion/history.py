"""Token-level price samples, explicit UTC ranges, and observed coverage diagnostics."""

import math
from datetime import UTC, datetime
from statistics import median

from senate_market.ingestion.client import CLOB
from senate_market.io import probability, utc


def fetch_history(
    client, token_id: str, start: str, end: str, *, fidelity: int = 60, chunk_days: int = 7
) -> dict:
    begin, stop = int(utc(start).timestamp()), int(utc(end).timestamp())
    if begin >= stop or fidelity < 1 or chunk_days < 1:
        raise ValueError("Require start < end, positive fidelity and positive chunk-days")
    if not token_id.isdecimal():
        raise ValueError("A decimal CLOB outcome token ID is required")
    points = {}
    empty_chunks = []
    cursor = begin
    while cursor < stop:
        boundary = min(cursor + chunk_days * 86400, stop)
        payload = client.get(
            CLOB,
            "/prices-history",
            {
                "market": token_id,
                "startTs": cursor,
                "endTs": boundary,
                "fidelity": fidelity,
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("history"), list):
            raise ValueError("CLOB response must contain a history array")
        in_window = 0
        for point in payload["history"]:
            timestamp = float(point["t"])
            if not math.isfinite(timestamp) or not timestamp.is_integer():
                raise ValueError("History timestamp must be finite integer epoch seconds")
            timestamp = int(timestamp)
            p = probability(point["p"])
            if not cursor <= timestamp <= boundary or timestamp >= stop:
                continue
            if timestamp in points and points[timestamp] != p:
                raise ValueError(f"Conflicting prices at timestamp {timestamp} for {token_id}")
            points[timestamp] = p
            in_window += 1
        if not in_window:
            empty_chunks.append([cursor, boundary])
        cursor = boundary
    times = sorted(points)
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]

    def iso(t):
        return datetime.fromtimestamp(t, UTC).isoformat()

    return {
        "schema_version": 1,
        "source": "polymarket_clob_prices_history",
        "token_id": token_id,
        "requested_start": iso(begin),
        "requested_end_exclusive": iso(stop),
        "fidelity_minutes": fidelity,
        "coverage": {
            "status": "observed" if times else "empty",
            "count": len(times),
            "first_observation": iso(times[0]) if times else None,
            "last_observation": iso(times[-1]) if times else None,
            "median_gap_seconds": median(gaps) if gaps else None,
            "max_gap_seconds": max(gaps) if gaps else None,
            "leading_gap_seconds": times[0] - begin if times else None,
            "trailing_gap_seconds": stop - times[-1] if times else None,
            "empty_chunks": empty_chunks,
        },
        "points": [{"timestamp": iso(t), "probability": points[t]} for t in times],
        "requests": client.requests_used.copy(),
        "notes": [
            "Price samples, not OHLCV, bid/ask quotes or historical liquidity.",
            "Observed coverage describes only the requested interval; not market inception.",
            "Empty history is not a zero probability. No interpolation or forward fill.",
        ],
    }
