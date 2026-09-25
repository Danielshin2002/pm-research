"""Descriptive comparison of batch model updates with observed market changes."""

import math
from collections import defaultdict

from senate_market.io import probability, utc


def compare(panel, posterior):
    if posterior.get("model") != "fixed_loading_grid_reference":
        raise ValueError("Expected fixed-loading reference posterior")
    # Batch IDs restart on each run: IDs alone are not sufficient provenance.
    for kind in ("events", "histories"):
        left, right = panel.get("inputs", {}).get(kind), posterior.get("inputs", {}).get(kind)
        if not left or not right:
            raise ValueError(f"Missing {kind} provenance")
        if kind == "events":
            same = left["sha256"] == right["sha256"]
        else:
            same = sorted(x["sha256"] for x in left) == sorted(x["sha256"] for x in right)
        if not same:
            raise ValueError(f"Panel and posterior use different {kind} inputs")
    previous = {r: probability(a["used_probability"]) for r, a in posterior["anchors"].items()}
    updates = {}
    last_time = utc(posterior["baseline_time"])
    for step in posterior["trajectory"]:
        batch = step["batch_id"]
        when = utc(step["available_at"])
        if batch in updates or when < last_time:
            raise ValueError("Duplicate or out-of-order posterior batch")
        after = {r: probability(p) for r, p in step["predictions"].items()}
        updates[batch] = (previous, after, when)
        previous, last_time = after, when
    rows, excluded, seen = [], [], set()
    for response in panel["responses"]:
        batch, target = response["batch_id"], response["target_race_id"]
        key = {"batch_id": batch, "target_race_id": target,
               "window_minutes": response["window_minutes"]}
        unique = (batch, target, response["window_minutes"])
        if unique in seen:
            raise ValueError("Duplicate panel response")
        seen.add(unique)
        if batch not in updates:
            raise ValueError(f"No posterior update for {batch}")
        before, after, when = updates[batch]
        if when != utc(response["batch_end"]):
            raise ValueError(f"Batch timing mismatch for {batch}")
        if utc(response["post_event"]["timestamp"]) <= when:
            raise ValueError("Market post sample must follow complete batch availability")
        if target not in before or target not in after:
            excluded.append({**key, "reason": "no_unresolved_model_prediction"})
            continue
        market_before = probability(response["pre_event"]["probability"])
        market_after = probability(response["post_event"]["probability"])
        predicted = after[target] - before[target]
        observed = market_after - market_before
        rows.append({**key, "available_at": when.isoformat(),
                     "horizon": response["horizon"],
                     "model_before": before[target], "model_after": after[target],
                     "market_before": market_before, "market_after": market_after,
                     "model_change": predicted, "market_change": observed,
                     "change_error": predicted - observed,
                     "contaminated": response.get("contaminated", False)})
    groups = defaultdict(list)
    for row in rows:
        groups[row["window_minutes"]].append(row)
    summaries = []
    for window, group in sorted(groups.items()):
        n = len(group)
        summaries.append({"window_minutes": window, "n": n,
                          "batches": len({r["batch_id"] for r in group}),
                          "targets": len({r["target_race_id"] for r in group}),
                          "mae_pp": 100 * sum(abs(r["change_error"]) for r in group) / n,
                          "rmse_pp": 100 * math.sqrt(
                              sum(r["change_error"] ** 2 for r in group) / n),
                          "no_change_mae_pp": 100 * sum(
                              abs(r["market_change"]) for r in group) / n,
                          "zero_market_changes": sum(
                              abs(r["market_change"]) < 1e-12 for r in group)})
    return {"schema_version": 1, "rows": rows, "excluded": excluded,
            "summary_by_window": summaries,
            "notes": [
                "Descriptive alignment, not an out-of-sample election forecast evaluation.",
                "Model change is current minus preceding posterior predictive probability; "
                "first batch uses frozen baseline. Market change uses panel pre/post samples.",
                "Each batch update is available only at batch end; it uses that batch's results.",
                "Model change is identical across horizons; this is not a time-decay model.",
                "No-change benchmark predicts zero market change. Errors are percentage points.",
                "Rows repeat races and batches: not independent observations. No significance "
                "tests or pooled-across-window performance claims are made.",
                "Retains panel selection and data-quality limitations; no flagged prices removed.",
            ]}


def markdown_report(result):
    lines = ["# Model versus market: exploratory comparison", "",
             f"Matched rows: {len(result['rows'])}. Additional exclusions: "
             f"{len(result['excluded'])}.", "",
             "Errors compare probability changes, not eventual election outcomes. "
             "Lower MAE means closer agreement with observed market changes.", "",
             "| Window (min) | Rows | Batches | Model MAE (pp) | No-change MAE (pp) |",
             "| --- | --- | --- | --- | --- |"]
    for s in result["summary_by_window"]:
        lines.append(f"| {s['window_minutes']} | {s['n']} | {s['batches']} | "
                     f"{s['mae_pp']:.3f} | {s['no_change_mae_pp']:.3f} |")
    lines.extend(["", "## Interpretation limits", ""])
    lines.extend(f"- {note}" for note in result["notes"])
    return "\n".join(lines) + "\n"
