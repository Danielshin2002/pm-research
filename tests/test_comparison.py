import pytest

from senate_market.evaluation.comparison import compare


def inputs():
    provenance = {"events": {"sha256": "event"}, "histories": [{"sha256": "history"}]}
    posterior = {"model": "fixed_loading_grid_reference", "inputs": provenance,
                 "baseline_time": "2024-11-05T12:00:00Z",
                 "anchors": {"target": {"used_probability": 0.4}},
                 "trajectory": [
                     {"batch_id": "b1", "available_at": "2024-11-06T00:00:00Z",
                      "predictions": {"target": 0.5}},
                     {"batch_id": "b2", "available_at": "2024-11-06T01:00:00Z",
                      "predictions": {"target": 0.55}}]}
    panel = {"inputs": provenance, "responses": [
        {"batch_id": "b2", "target_race_id": "target", "window_minutes": 5,
         "batch_end": "2024-11-06T01:00:00Z", "horizon": "2024-11-06T01:05:00Z",
         "pre_event": {"probability": 0.6},
         "post_event": {"probability": 0.62, "timestamp": "2024-11-06T01:04:00Z"}}]}
    return panel, posterior


def test_uses_previous_batch_even_when_absent_from_panel():
    panel, posterior = inputs()
    result = compare(panel, posterior)
    assert result["rows"][0]["model_change"] == pytest.approx(0.05)
    assert result["summary_by_window"][0]["mae_pp"] == pytest.approx(3)
    assert result["summary_by_window"][0]["no_change_mae_pp"] == pytest.approx(2)


def test_first_batch_uses_anchor():
    panel, posterior = inputs()
    posterior["trajectory"] = posterior["trajectory"][1:]
    assert compare(panel, posterior)["rows"][0]["model_change"] == pytest.approx(0.15)


def test_rejects_provenance_mismatch():
    panel, posterior = inputs()
    panel["inputs"] = {**panel["inputs"], "events": {"sha256": "different"}}
    with pytest.raises(ValueError, match="different events"):
        compare(panel, posterior)


def test_rejects_timing_mismatch_and_duplicate_rows():
    panel, posterior = inputs()
    panel["responses"][0]["batch_end"] = "2024-11-06T02:00:00Z"
    with pytest.raises(ValueError, match="timing mismatch"):
        compare(panel, posterior)
    panel, posterior = inputs()
    panel["responses"] *= 2
    with pytest.raises(ValueError, match="Duplicate panel"):
        compare(panel, posterior)


def test_excludes_missing_prediction():
    panel, posterior = inputs()
    posterior["trajectory"][1]["predictions"] = {}
    result = compare(panel, posterior)
    assert not result["rows"]
    assert result["excluded"][0]["reason"] == "no_unresolved_model_prediction"
