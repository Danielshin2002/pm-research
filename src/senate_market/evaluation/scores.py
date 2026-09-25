"""Proper scores, to be aggregated over races rather than duplicated event pairs."""

import math

from senate_market.io import probability


def scores(predictions: list[float], results: list[int]) -> dict:
    if not predictions or len(predictions) != len(results):
        raise ValueError("Require nonempty predictions and matching results")
    if any(y not in {0, 1} for y in results):
        raise ValueError("Results must be binary")
    p = [probability(value) for value in predictions]
    clipped = [min(1 - 1e-6, max(1e-6, value)) for value in p]
    return {
        "n": len(p),
        "brier": sum((a - y) ** 2 for a, y in zip(p, results, strict=True)) / len(p),
        "log_loss": -sum(
            y * math.log(a) + (1 - y) * math.log1p(-a)
            for a, y in zip(clipped, results, strict=True)
        )
        / len(p),
        "log_loss_epsilon": 1e-6,
    }
