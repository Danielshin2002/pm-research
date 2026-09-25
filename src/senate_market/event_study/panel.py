"""Construct batch-target-window responses and preserve every exclusion reason."""

import math
from datetime import timedelta

from senate_market.features.prices import PriceSeries
from senate_market.io import utc


def logit(p: float, epsilon: float = 1e-6) -> float:
    p = min(1 - epsilon, max(epsilon, p))
    return math.log(p / (1 - p))


def build_panel(
    events: dict,
    histories: dict[str, dict],
    *,
    windows: list[int],
    max_age_seconds: int = 120,
    contamination_minutes: int = 5,
    exclude_contaminated: bool = True,
) -> dict:
    if not windows or any(w <= 0 for w in windows) or max_age_seconds < 0:
        raise ValueError("Windows must be positive; staleness tolerance must be nonnegative")
    if contamination_minutes < 0:
        raise ValueError("Contamination buffer must be nonnegative")
    races = {r["race_id"]: r for r in events["races"]}
    series = {}
    for race_id, race in races.items():
        history = histories.get(race["token_id"])
        if history is not None:
            if history["token_id"] != race["token_id"]:
                raise ValueError("History token does not match mapping")
            series[race_id] = PriceSeries(history, race["orientation"])
    responses, excluded = [], []
    for batch in events["batches"]:
        start, end = utc(batch["start"]), utc(batch["end"])
        source_ids = {e["race_id"] for e in batch["events"]}
        event_ids = {e["event_id"] for e in batch["events"]}
        surprises = []
        for source in batch["events"]:
            prices = series.get(source["race_id"])
            before = prices.asof(start, max_age_seconds, strict=True) if prices else None
            surprises.append(
                {
                    "race_id": source["race_id"],
                    "result": source["result"],
                    "pre_event": before,
                    "surprise": source["result"] - before["probability"] if before else None,
                }
            )
        for race_id, race in races.items():
            if race_id in source_ids or (race["cycle"], race["election_type"]) != (
                batch["cycle"],
                batch["election_type"],
            ):
                continue
            for window in sorted(set(windows)):
                key = {
                    "batch_id": batch["batch_id"],
                    "target_race_id": race_id,
                    "window_minutes": window,
                }
                horizon = end + timedelta(minutes=window)
                buffer = timedelta(minutes=contamination_minutes)
                overlaps = [
                    e["event_id"]
                    for e in events["events"]
                    if e["event_id"] not in event_ids
                    and e["event_type"] != "poll_close"
                    and start - buffer <= utc(e["timestamp"]) <= horizon
                ]
                reason = None
                cutoff = events["known_result_times"].get(race_id)
                prices = series.get(race_id)
                if cutoff and utc(cutoff) <= horizon:
                    reason = "target_result_known_by_window_end"
                elif not cutoff and (
                    not race.get("unresolved_through") or utc(race["unresolved_through"]) < horizon
                ):
                    reason = "target_unresolved_status_unverified"
                elif any(s["surprise"] is None for s in surprises):
                    reason = "missing_or_stale_source_pre_price"
                elif prices is None:
                    reason = "missing_target_history"
                elif max([prices.fidelity, *[series[s].fidelity for s in source_ids]]) > window:
                    reason = "history_too_coarse_for_window"
                elif overlaps and exclude_contaminated:
                    reason = "overlapping_information"
                before = prices.asof(start, max_age_seconds, strict=True) if prices else None
                after = prices.asof(horizon, max_age_seconds) if prices else None
                if reason is None and (not before or not after or utc(after["timestamp"]) <= end):
                    reason = "missing_or_stale_target_price"
                if reason:
                    excluded.append({**key, "reason": reason, "overlapping_event_ids": overlaps})
                    continue
                responses.append(
                    {
                        **key,
                        "cycle": race["cycle"],
                        "state": race["state"],
                        "batch_start": batch["start"],
                        "batch_end": batch["end"],
                        "horizon": horizon.isoformat(),
                        "source_surprises": surprises,
                        "pre_event": before,
                        "post_event": after,
                        "delta_logit": logit(after["probability"]) - logit(before["probability"]),
                        "overlapping_event_ids": overlaps,
                        "contaminated": bool(overlaps),
                    }
                )
    return {
        "schema_version": 1,
        "responses": responses,
        "excluded": excluded,
        "config": {
            "windows_minutes": windows,
            "max_age_seconds": max_age_seconds,
            "contamination_minutes": contamination_minutes,
            "exclude_contaminated": exclude_contaminated,
            "logit_epsilon": 1e-6,
        },
        "notes": [
            "Descriptive responses, not identified causal effects.",
            "Pre-prices precede batch start; horizons are measured from batch end.",
            "One row per batch-target-window; multiple source surprises remain a vector.",
        ],
    }
