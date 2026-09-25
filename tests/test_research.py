import copy
import math

import pytest

from senate_market.bayesian.sequential import run_baseline
from senate_market.cli import load_histories, main
from senate_market.demo import synthetic_inputs
from senate_market.evaluation.scores import scores
from senate_market.event_study.panel import build_panel
from senate_market.events.build import build_events, validate_races
from senate_market.features.prices import PriceSeries
from senate_market.io import artifact_ref, read_json, utc, write_json


@pytest.fixture
def inputs():
    catalog, mappings, calls, histories = synthetic_inputs()
    return catalog, validate_races(mappings, catalog), calls, histories


def test_review_and_exact_token_mapping_required(inputs):
    catalog, races, _, _ = inputs
    races[0]["reviewed"] = "false"
    with pytest.raises(ValueError, match="reviewed"):
        validate_races(races, catalog)
    races[0]["reviewed"] = "true"
    races[0]["token_id"] = "999"
    with pytest.raises(ValueError, match="Token/label"):
        validate_races(races, catalog)


def test_batching_uses_times_not_input_order_and_does_not_chain(inputs):
    _, races, calls, _ = inputs
    calls[1]["timestamp"] = "2024-11-06T00:14:00Z"
    calls[2]["timestamp"] = "2024-11-06T00:18:00Z"
    events = build_events(races, list(reversed(calls)), batch_minutes=5)
    assert [len(b["events"]) for b in events["batches"]] == [2, 1]
    assert events["batches"][0]["events"][0]["race_id"] == "PA"


def test_call_beats_late_settlement_and_no_default_fallback(inputs):
    _, races, calls, _ = inputs
    resolution = {
        **calls[0],
        "event_id": "resolution-pa",
        "event_type": "market_resolution",
        "timestamp": "2024-11-07T00:00:00Z",
    }
    events = build_events(races, [*calls, resolution])
    assert len(events["batches"]) == 3
    assert events["known_result_times"]["PA"] == "2024-11-06T00:10:00+00:00"
    assert not build_events(races, [resolution])["batches"]
    assert build_events(races, [resolution], allow_resolution_fallback=True)["batches"]


def test_poll_close_cannot_reveal_eventual_result(inputs):
    _, races, calls, _ = inputs
    calls[0]["event_type"] = "poll_close"
    with pytest.raises(ValueError, match="Only race calls"):
        build_events(races, calls)


def test_calls_cannot_disagree_with_settlement(inputs):
    _, races, calls, _ = inputs
    resolution = {
        **calls[0],
        "event_id": "settled",
        "event_type": "market_resolution",
        "result": "0",
    }
    with pytest.raises(ValueError, match="Conflicting"):
        build_events(races, [*calls, resolution])


def test_asof_excludes_future_and_rejects_stale_prices():
    history = {
        "fidelity_minutes": 1,
        "points": [
            {"timestamp": "2024-11-06T00:10:00Z", "probability": 0.9},
            {"timestamp": "2024-11-06T00:09:00Z", "probability": 0.4},
        ],
    }
    series = PriceSeries(history, "complement")
    at = utc("2024-11-06T00:10:00Z")
    assert series.asof(at, 60, strict=True)["probability"] == 0.6
    assert series.asof(at, 30, strict=True) is None


def test_panel_has_one_row_per_batch_target_and_excludes_resolved_targets(inputs):
    _, races, calls, histories = inputs
    events = build_events(races, calls)
    panel = build_panel(events, histories, windows=[5])
    assert len(panel["responses"]) == 3
    assert panel["responses"][0]["delta_logit"] > 0
    assert all(utc(r["pre_event"]["timestamp"]) < utc(r["batch_start"]) for r in panel["responses"])
    assert any(r["reason"] == "target_result_known_by_window_end" for r in panel["excluded"])


def test_missing_target_call_does_not_mean_unresolved(inputs):
    _, races, calls, histories = inputs
    panel = build_panel(build_events(races, calls[:1]), histories, windows=[5])
    assert not panel["responses"]
    assert {r["reason"] for r in panel["excluded"]} == {"target_unresolved_status_unverified"}


def test_contaminated_windows_flagged_or_excluded(inputs):
    _, races, calls, histories = inputs
    news = {
        "event_id": "news",
        "race_id": "",
        "event_type": "other_news",
        "timestamp": "2024-11-06T00:12:00Z",
        "time_precision": "second",
        "source_url": "synthetic://news",
    }
    events = build_events(races, [*calls, news])
    panel = build_panel(events, histories, windows=[5])
    assert any(r["reason"] == "overlapping_information" for r in panel["excluded"])
    kept = build_panel(events, histories, windows=[5], exclude_contaminated=False)
    assert any(r["contaminated"] for r in kept["responses"])


def test_coarse_history_rejects_five_minute_window(inputs):
    _, races, calls, histories = inputs
    for h in histories.values():
        h["fidelity_minutes"] = 60
    panel = build_panel(build_events(races, calls), histories, windows=[5])
    assert not panel["responses"]
    assert any(e["reason"] == "history_too_coarse_for_window" for e in panel["excluded"])


def test_bayesian_prior_calibration_update_direction_and_frozen_anchors(inputs):
    _, races, calls, histories = inputs
    events = build_events(races, calls)
    result = run_baseline(events, histories, "2024-11-06T00:05:00Z")
    assert result["trajectory"][0]["theta_mean"] > 0
    assert (
        result["trajectory"][0]["predictions"]["WI"] > result["anchors"]["WI"]["used_probability"]
    )
    assert sum(result["trajectory"][0]["weights"]) == pytest.approx(1)
    assert "PA" not in result["trajectory"][0]["predictions"]
    # Change all post-baseline prices: a frozen-prior result must remain identical.
    for history in histories.values():
        for point in history["points"]:
            if utc(point["timestamp"]) >= utc("2024-11-06T00:05:00Z"):
                point["probability"] = 0.99
    assert run_baseline(events, histories, "2024-11-06T00:05:00Z") == result
    from senate_market.bayesian.sequential import sigmoid

    for anchor in result["anchors"].values():
        mean = sum(
            w * sigmoid(anchor["intercept"] + x)
            for w, x in zip(result["prior_weights"], result["theta_grid"], strict=True)
        )
        assert mean == pytest.approx(anchor["used_probability"])


def test_simultaneous_bayesian_updates_are_order_invariant(inputs):
    _, races, calls, histories = inputs
    calls[1]["timestamp"] = calls[0]["timestamp"]
    events = build_events(races, calls)
    reversed_events = copy.deepcopy(events)
    reversed_events["batches"][0]["events"].reverse()
    a = run_baseline(events, histories, "2024-11-06T00:05:00Z")
    b = run_baseline(reversed_events, histories, "2024-11-06T00:05:00Z")
    assert a["trajectory"][0]["theta_mean"] == pytest.approx(b["trajectory"][0]["theta_mean"])


def test_reference_model_rejects_post_result_baseline(inputs):
    _, races, calls, histories = inputs
    with pytest.raises(ValueError, match="precede"):
        run_baseline(build_events(races, calls), histories, "2024-11-06T00:10:00Z")


def test_scores_are_finite_for_extreme_prices():
    result = scores([0, 1], [0, 1])
    assert result["brier"] == 0
    assert math.isfinite(result["log_loss"])


def test_history_error_manifest_prevents_stale_output_reuse(inputs, tmp_path):
    _, races, calls, histories = inputs
    write_json(tmp_path / "10.json", histories["10"])
    write_json(tmp_path / "coverage.json", {"tokens": [{"token_id": "10", "status": "error"}]})
    assert load_histories(build_events(races, calls), tmp_path) == {}


def test_cli_demo_runs_offline_and_outputs_are_synthetic(tmp_path):
    assert main(["demo", "--output-dir", str(tmp_path)]) == 0
    assert read_json(tmp_path / "panel.json")["synthetic"]
    assert read_json(tmp_path / "panel.json")["responses"]
    assert read_json(tmp_path / "posterior.json")["trajectory"]


def test_coverage_hash_detects_replaced_history(inputs, tmp_path):
    _, races, calls, histories = inputs
    destination = tmp_path / "10.json"
    write_json(destination, histories["10"])
    write_json(
        tmp_path / "coverage.json",
        {
            "tokens": [
                {"token_id": "10", "status": "observed", "artifact": artifact_ref(destination)}
            ]
        },
    )
    histories["10"]["points"][0]["probability"] = 0.99
    write_json(destination, histories["10"])
    with pytest.raises(ValueError, match="differs from coverage"):
        load_histories(build_events(races, calls), tmp_path)
