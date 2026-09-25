"""Strict as-of prices with explicit staleness bounds; no future interpolation."""

from bisect import bisect_left, bisect_right
from datetime import datetime

from senate_market.io import probability, utc


class PriceSeries:
    def __init__(self, history: dict, orientation: str = "identity"):
        if orientation not in {"identity", "complement"}:
            raise ValueError("Unknown outcome orientation")
        self.fidelity = int(history["fidelity_minutes"])
        if self.fidelity <= 0:
            raise ValueError("Fidelity must be positive")
        observations = {}
        for point in history["points"]:
            timestamp = utc(point["timestamp"])
            p = probability(point["probability"])
            if timestamp in observations and observations[timestamp] != p:
                raise ValueError("Conflicting duplicate price observation")
            observations[timestamp] = p
        self.times = sorted(observations)
        self.values = [
            observations[t] if orientation == "identity" else 1 - observations[t]
            for t in self.times
        ]

    def asof(self, at: datetime, max_age_seconds: int, *, strict: bool = False):
        index = (bisect_left(self.times, at) if strict else bisect_right(self.times, at)) - 1
        if index < 0 or (at - self.times[index]).total_seconds() > max_age_seconds:
            return None
        return {
            "timestamp": self.times[index].isoformat(),
            "probability": self.values[index],
            "age_seconds": (at - self.times[index]).total_seconds(),
        }
