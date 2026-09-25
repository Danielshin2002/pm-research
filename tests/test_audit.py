from datetime import UTC, datetime, timedelta

import pytest

from senate_market.audit import audit_race, plot


def sample(values, minutes=None):
    start = datetime(2024, 11, 5, tzinfo=UTC)
    minutes = minutes or list(range(len(values)))
    return {"token_id": "123", "points": [
        {"timestamp": (start + timedelta(minutes=m)).isoformat(), "probability": p}
        for m, p in zip(minutes, values, strict=True)]}


RACE = {"race_id": "test", "token_id": "123", "market_id": "1", "orientation": "identity"}


def test_jumps_and_complement():
    r, _ = audit_race({**RACE, "orientation": "complement"}, sample([0.1, 0.5]), [])
    assert r["jumps"][0]["change"] == pytest.approx(-0.4)
    assert r["min_probability"] == 0.5


def test_flat_run_does_not_cross_gap():
    r, _ = audit_race(RACE, sample([0.2] * 4, [0, 1, 100, 101]), [], flat_minutes=1)
    assert len(r["flat_stretches"]) == 2
    assert len(r["gaps"]) == 1
    assert all(f["minutes"] == 1 for f in r["flat_stretches"])


def test_missing_empty_and_invalid():
    assert audit_race(RACE, None, [])[0]["status"] == "missing_or_unavailable"
    assert audit_race(RACE, sample([]), [])[0]["status"] == "empty"
    with pytest.raises(ValueError):
        audit_race(RACE, sample([0.1, 0.2], [1, 1]), [])
    with pytest.raises(ValueError):
        audit_race(RACE, sample([float("nan")]), [])
    with pytest.raises(ValueError):
        audit_race(RACE, {"token_id": "456", "points": []}, [])
    with pytest.raises(ValueError):
        audit_race(RACE, sample([]), [], jump=float("nan"))


def test_pre_call_is_strictly_before_and_flags_outside_span():
    events = [{"race_id": "test", "event_type": "race_call",
               "timestamp": "2024-11-05T00:01:00Z", "result": 1, "source_url": "source"}]
    r, points = audit_race(RACE, sample([0.1, 0.9]), events)
    assert r["calls"][0]["pre_probability"] == 0.1
    assert r["calls"][0]["pre_age_seconds"] == 60
    assert "AP call" in plot(points, r["calls"], 120)
    events[0]["timestamp"] = "2024-11-07T00:00:00Z"
    r, _ = audit_race(RACE, sample([0.1, 0.9]), events)
    assert not r["calls"][0]["inside_observed_span"]
