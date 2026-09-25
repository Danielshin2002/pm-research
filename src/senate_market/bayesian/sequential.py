"""Calibrated market priors and batch Bayesian updates for a single latent factor."""

import math

from senate_market.features.prices import PriceSeries
from senate_market.io import utc


def sigmoid(x):
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


def normalized(log_weights):
    peak = max(log_weights)
    weights = [math.exp(w - peak) for w in log_weights]
    total = sum(weights)
    return [w / total for w in weights]


def run_baseline(
    events: dict,
    histories: dict[str, dict],
    baseline_time: str,
    *,
    max_age_seconds: int = 120,
    loading: float = 1.0,
) -> dict:
    """Fixed N(0,1) prior, fixed common loading, conditional Bernoulli likelihoods.

    Integrate each predictive probability over theta. Intercepts are calibrated so
    prior predictive means equal the frozen market probabilities (up to clipping).
    """
    if not math.isfinite(loading) or not 0 < loading <= 5 or max_age_seconds < 0:
        raise ValueError("Require 0 < loading <= 5 and nonnegative price age")
    groups = {(r["cycle"], r["election_type"]) for r in events["races"]}
    if len(groups) != 1 or not events["batches"]:
        raise ValueError("Reference model needs one cycle/election type and at least one batch")
    t0 = utc(baseline_time)
    if any(t0 >= utc(t) for t in events["known_result_times"].values()):
        raise ValueError("Baseline must precede every known result")
    theta = [-6 + i * 12 / 400 for i in range(401)]
    log_weights = [-x * x / 2 for x in theta]
    prior = normalized(log_weights)
    probabilities, anchors = {}, {}
    for race in events["races"]:
        history = histories.get(race["token_id"])
        if history is None or history["token_id"] != race["token_id"]:
            raise ValueError(f"Missing/mismatched baseline history for {race['race_id']}")
        quote = PriceSeries(history, race["orientation"]).asof(t0, max_age_seconds, strict=True)
        if quote is None:
            raise ValueError(f"Missing/stale frozen baseline for {race['race_id']}")
        p0 = min(1 - 1e-6, max(1e-6, quote["probability"]))
        low, high = -50.0, 50.0
        for _ in range(90):
            mid = (low + high) / 2
            expectation = sum(
                w * sigmoid(mid + loading * x) for w, x in zip(prior, theta, strict=True)
            )
            if expectation < p0:
                low = mid
            else:
                high = mid
        intercept = (low + high) / 2
        probabilities[race["race_id"]] = [sigmoid(intercept + loading * x) for x in theta]
        anchors[race["race_id"]] = {**quote, "used_probability": p0, "intercept": intercept}

    trajectory, observed = [], set()
    for batch in sorted(events["batches"], key=lambda b: b["start"]):
        for event in batch["events"]:
            race_id, result = event["race_id"], event["result"]
            if race_id in observed or result not in {0, 1}:
                raise ValueError("Each binary race result may enter the posterior only once")
            for index, p in enumerate(probabilities[race_id]):
                likelihood = p if result else 1 - p
                log_weights[index] += math.log(max(likelihood, 1e-300))
            observed.add(race_id)
        weights = normalized(log_weights)
        mean = sum(x * w for x, w in zip(theta, weights, strict=True))
        predictions = {
            r: sum(p * w for p, w in zip(values, weights, strict=True))
            for r, values in probabilities.items()
            if r not in observed
            and (
                r not in events["known_result_times"]
                or utc(events["known_result_times"][r]) > utc(batch["end"])
            )
        }
        trajectory.append(
            {
                "batch_id": batch["batch_id"],
                "available_at": batch["end"],
                "theta_mean": mean,
                "theta_sd": math.sqrt(
                    sum(w * (x - mean) ** 2 for x, w in zip(theta, weights, strict=True))
                ),
                "weights": weights,
                "predictions": predictions,
            }
        )
    return {
        "model": "fixed_loading_grid_reference",
        "baseline_time": t0.isoformat(),
        "loading": loading,
        "theta_grid": theta,
        "prior_weights": prior,
        "anchors": anchors,
        "trajectory": trajectory,
        "notes": [
            "Reference calculation; loadings are assumptions, not fitted effects.",
            "Conditional independence given theta; static factor within one cycle/type.",
            "All market priors are frozen before the first result; never re-anchor.",
            "No causal or out-of-sample performance claim follows from this output.",
        ],
    }
