"""Gamma discovery is a candidate inventory, not a reviewed election universe."""

import json
import re
from collections.abc import Callable

from senate_market.ingestion.client import GAMMA


def array(value) -> list:
    if value is None or value == "":
        return []
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, list):
        raise ValueError("Expected a JSON array")
    return result


def normalize_market(raw: dict) -> dict:
    market_id = str(raw["id"])
    labels = array(raw.get("outcomes"))
    tokens = array(raw.get("clobTokenIds"))
    if tokens and (len(tokens) != len(labels) or len(set(tokens)) != len(tokens)):
        raise ValueError(f"Ambiguous outcome/token mapping for market {market_id}")
    return {
        "market_id": market_id,
        "condition_id": raw.get("conditionId"),
        "question": raw.get("question"),
        "slug": raw.get("slug"),
        "description": raw.get("description"),
        "events": [
            {"event_id": str(e["id"]), "title": e.get("title"), "slug": e.get("slug")}
            for e in (raw.get("events") or [])
        ],
        "outcomes": [
            {"label": str(label), "token_id": str(tokens[i]) if tokens else None}
            for i, label in enumerate(labels)
        ],
        "has_clob_tokens": bool(tokens),
        "closed": raw.get("closed"),
        "active": raw.get("active"),
        "archived": raw.get("archived"),
        "created_at": raw.get("createdAt"),
        "start_date": raw.get("startDate"),
        "end_date": raw.get("endDate"),
        "gamma_closed_time": raw.get("closedTime"),
        "resolution_source": raw.get("resolutionSource"),
        "review_status": "unreviewed",
    }


def senate_candidate(raw: dict) -> bool:
    text = " ".join(
        [
            raw.get("question") or "",
            raw.get("slug") or "",
            *[e.get("title") or "" for e in (raw.get("events") or [])],
        ]
    )
    return bool(re.search(r"\bsenat(?:e|or|orial)\b", text, re.IGNORECASE))


def discover(
    client,
    *,
    end_year: int | None = None,
    page_size: int = 100,
    max_pages: int = 50,
    closed: str = "all",
    tag_id: str | None = None,
    slugs: list[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict:
    if not 1 <= page_size <= 100 or max_pages < 1:
        raise ValueError("page-size must be 1..100 and max-pages must be positive")
    states = [True, False] if closed == "all" else [closed == "true"]
    markets = {}
    scans = []
    for state in states:
        exhausted = False
        seen = set()
        cursor = None
        seen_cursors = set()
        for _page in range(max_pages):
            params = {
                "limit": page_size,
                "closed": str(state).lower(),
                "order": "id",
                "ascending": "true",
            }
            if cursor is not None:
                params["after_cursor"] = cursor
            if end_year:
                params.update(
                    end_date_min=f"{end_year}-01-01T00:00:00Z",
                    end_date_max=f"{end_year}-12-31T23:59:59Z",
                )
            if tag_id:
                params["tag_id"] = tag_id
            if slugs:
                params["slug"] = slugs
            payload = client.get(GAMMA, "/markets/keyset", params)
            if not isinstance(payload, dict) or not isinstance(payload.get("markets"), list):
                raise ValueError("Gamma /markets/keyset response must contain a markets array")
            rows = payload["markets"]
            next_cursor = payload.get("next_cursor")
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise ValueError("Gamma next_cursor must be a string or null")
            if next_cursor and (next_cursor in seen_cursors or not rows):
                raise ValueError("Gamma pagination returned a repeated or non-advancing cursor")
            ids = {str(row["id"]) for row in rows}
            if rows and not ids - seen:
                raise ValueError("Gamma pagination repeated a page without new markets")
            seen.update(ids)
            for row in rows:
                if slugs or senate_candidate(row):
                    markets[str(row["id"])] = normalize_market(row)
            if progress:
                progress(
                    f"closed={str(state).lower()} page={_page + 1}: "
                    f"{len(seen)} markets scanned, {len(markets)} candidates"
                )
            # Follow the opaque cursor even for a short page. The endpoint omits
            # next_cursor on its last page; never send offset to this endpoint.
            cursor = next_cursor or None
            if cursor is None:
                exhausted = True
                break
            seen_cursors.add(cursor)
        scans.append(
            {
                "closed": state,
                "pages": _page + 1,
                "scanned": len(seen),
                "exhausted": exhausted,
                "next_cursor": cursor,
            }
        )
    return {
        "schema_version": 1,
        "source": "polymarket_gamma",
        "pagination_method": "keyset",
        "scope": {
            "end_year_filter": end_year,
            "closed": closed,
            "tag_id": tag_id,
            "slugs": slugs or [],
            "classification": "senate title/slug candidates",
        },
        "pagination_complete": all(s["exhausted"] for s in scans),
        "scans": scans,
        "markets": list(markets.values()),
        "requests": client.requests_used,
        "notes": [
            "End-date filtering is not election-cycle classification.",
            "Includes possible chamber-control, primary, foreign and state-senate markets.",
            "Review race/outcome mappings before analysis; no historical coverage guaranteed.",
        ],
    }
