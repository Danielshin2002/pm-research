import json

import pytest
import requests

from senate_market.ingestion.catalog import discover, normalize_market, senate_candidate
from senate_market.ingestion.client import PublicClient
from senate_market.ingestion.history import fetch_history


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.requests_used = []

    def get(self, base, path, params):
        self.calls.append((base, path, params))
        return next(self.responses)


def market(identifier="1"):
    return {
        "id": identifier,
        "question": "Will Democrats win the Pennsylvania Senate race?",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["123", "456"]',
    }


def test_gamma_normalization_retains_string_ids_and_missing_tokens():
    raw = market()
    assert normalize_market(raw)["outcomes"][0] == {"label": "Yes", "token_id": "123"}
    raw.pop("clobTokenIds")
    assert normalize_market(raw)["has_clob_tokens"] is False
    raw["clobTokenIds"] = '["123"]'
    with pytest.raises(ValueError, match="Ambiguous"):
        normalize_market(raw)


def test_candidate_text_is_only_discovery():
    assert senate_candidate({"question": "Foreign Senate control"})
    assert not senate_candidate({"question": "Presidential election", "description": "senate"})


def page(rows, cursor=None):
    result = {"markets": rows}
    if cursor is not None:
        result["next_cursor"] = cursor
    return result


def test_explicit_open_closed_pagination_and_partial_report():
    client = FakeClient([page([market()], "opaque+/cursor="), page([]), page([])])
    result = discover(client, page_size=1, end_year=2024)
    assert result["pagination_complete"] is True
    assert [call[2]["closed"] for call in client.calls] == ["true", "true", "false"]
    assert client.calls[1][2]["after_cursor"] == "opaque+/cursor="
    assert "after_cursor" not in client.calls[2][2]
    assert all(call[1] == "/markets/keyset" and "offset" not in call[2] for call in client.calls)
    assert "active" not in client.calls[0][2]
    partial = discover(
        FakeClient([page([market()], "more")]), page_size=1, max_pages=1, closed="true"
    )
    assert not partial["pagination_complete"]
    assert partial["scans"][0]["next_cursor"] == "more"


def test_pagination_repetition_is_an_error():
    with pytest.raises(ValueError, match="repeated"):
        discover(
            FakeClient([page([market()], "a"), page([market()], "b")]), page_size=1, closed="true"
        )


def test_short_page_with_cursor_does_not_end_scan():
    client = FakeClient([page([market("1")], "a"), page([market("2")])])
    result = discover(client, page_size=100, closed="true")
    assert len(result["markets"]) == 2
    assert client.calls[1][2]["after_cursor"] == "a"
    assert result["pagination_complete"]


def test_full_final_page_without_cursor_is_complete():
    result = discover(FakeClient([page([market()])]), page_size=1, max_pages=1, closed="true")
    assert result["pagination_complete"]


def test_cursor_loop_rejected_even_with_new_markets():
    with pytest.raises(ValueError, match="repeated.*cursor"):
        discover(FakeClient([page([market("1")], "a"), page([market("2")], "a")]), closed="true")


@pytest.mark.parametrize(
    "payload", [[], {}, {"markets": None}, page([], "more"), {"markets": [], "next_cursor": 1}]
)
def test_malformed_keyset_responses_fail(payload):
    with pytest.raises(ValueError):
        discover(FakeClient([payload]), closed="true")


def test_keyset_past_old_offset_limit_retains_filters():
    pages = [page([market(str(i))], f"cursor-{i}") for i in range(22)] + [page([])]
    client = FakeClient(pages)
    result = discover(client, end_year=2024, closed="true", tag_id="42", slugs=["example"])
    assert result["pagination_complete"]
    assert result["scans"][0]["pages"] == 23
    for _, path, params in client.calls:
        assert path == "/markets/keyset"
        assert "offset" not in params
        assert params["end_date_min"] == "2024-01-01T00:00:00Z"
        assert params["tag_id"] == "42"
        assert params["slug"] == ["example"]


def test_keyset_limit_validated_before_request():
    with pytest.raises(ValueError, match="1..100"):
        discover(FakeClient([]), page_size=500)


def test_history_chunk_boundaries_sorted_deduplicated_and_end_exclusive():
    start = 1730764800  # 2024-11-05T00:00:00Z
    client = FakeClient(
        [
            {"history": [{"t": start + 86400, "p": 0.6}, {"t": start, "p": 0.5}]},
            {"history": [{"t": start + 86400, "p": 0.6}, {"t": start + 172800, "p": 1}]},
        ]
    )
    result = fetch_history(
        client, "123", "2024-11-05T00:00:00Z", "2024-11-07T00:00:00Z", chunk_days=1
    )
    assert result["coverage"]["count"] == 2
    assert result["coverage"]["max_gap_seconds"] == 86400
    assert result["points"][0]["probability"] == 0.5
    assert all("interval" not in call[2] for call in client.calls)


def test_empty_history_not_error_or_zero():
    result = fetch_history(
        FakeClient([{"history": []}]), "123", "2024-11-05T00:00:00Z", "2024-11-06T00:00:00Z"
    )
    assert result["coverage"]["status"] == "empty"
    assert result["coverage"]["first_observation"] is None
    assert result["points"] == []


@pytest.mark.parametrize("payload", [{"error": "bad request"}, {"history": [{"t": 1, "p": 2}]}])
def test_malformed_api_history_is_not_silently_empty(payload):
    with pytest.raises(ValueError):
        fetch_history(FakeClient([payload]), "123", "2024-11-05T00:00:00Z", "2024-11-06T00:00:00Z")


def test_timezone_is_required():
    with pytest.raises(ValueError, match="timezone"):
        fetch_history(FakeClient([]), "123", "2024-11-05", "2024-11-06")


def test_cache_replay_refresh_preserves_original_snapshot(tmp_path, monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return [market()]

    client = PublicClient(tmp_path)
    monkeypatch.setattr(client.session, "get", lambda *a, **k: Response())
    monkeypatch.setattr("senate_market.ingestion.client.time.sleep", lambda _: None)
    first = client.get("https://example.test", "/markets", {"closed": "true"})
    replay = PublicClient(tmp_path, offline=True)
    assert replay.get("https://example.test", "/markets", {"closed": "true"}) == first
    original = client.requests_used[0]["cache_file"]
    assert json.loads(open(original).read())["payload"] == first
    with pytest.raises(ValueError, match="No cached"):
        replay.get("https://example.test", "/missing", {})


def test_conflicting_boundary_prices_fail():
    start = 1730764800
    client = FakeClient(
        [
            {"history": [{"t": start + 86400, "p": 0.6}]},
            {"history": [{"t": start + 86400, "p": 0.7}]},
        ]
    )
    with pytest.raises(ValueError, match="Conflicting"):
        fetch_history(client, "123", "2024-11-05T00:00:00Z", "2024-11-07T00:00:00Z", chunk_days=1)


def test_http_failure_includes_api_reason(tmp_path, monkeypatch):
    response = requests.Response()
    response.status_code = 422
    response.url = "https://example.test/markets"
    response._content = b'{"error":"offset too large, use /markets/keyset"}'
    client = PublicClient(tmp_path)
    monkeypatch.setattr(client.session, "get", lambda *a, **k: response)
    with pytest.raises(requests.HTTPError, match="offset too large"):
        client.get("https://example.test", "/markets", {"offset": 2100})
    assert not list(tmp_path.glob("*.json"))
