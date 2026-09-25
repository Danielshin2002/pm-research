"""Deliberately synthetic example, with no external requests or empirical claims."""

from datetime import timedelta
from pathlib import Path

from senate_market.bayesian.sequential import run_baseline
from senate_market.event_study.panel import build_panel
from senate_market.events.build import build_events, validate_races
from senate_market.ingestion.catalog import normalize_market
from senate_market.io import utc, write_json


def synthetic_inputs():
    catalog, mappings, observations = [], [], {}
    for index, state in enumerate(["PA", "WI", "MI"], 1):
        token = str(index * 10)
        catalog.append(
            normalize_market(
                {
                    "id": str(index),
                    "question": f"SYNTHETIC Democratic {state} Senate win?",
                    "outcomes": ["Yes", "No"],
                    "clobTokenIds": [token, str(index * 10 + 1)],
                }
            )
        )
        mappings.append(
            {
                "race_id": state,
                "state": state,
                "cycle": "2024",
                "senate_class": "1",
                "election_type": "general",
                "election_date": "2024-11-05",
                "market_id": str(index),
                "token_id": token,
                "outcome_label": "Yes",
                "orientation": "identity",
                "source_url": "synthetic://example",
                "reviewed": "true",
            }
        )
        start = utc("2024-11-06T00:00:00Z")
        observations[token] = {
            "token_id": token,
            "fidelity_minutes": 1,
            "synthetic": True,
            "points": [
                {
                    "timestamp": (start + timedelta(minutes=i)).isoformat(),
                    "probability": 0.4 + index * 0.05 + (0.05 if i > 10 else 0),
                }
                for i in range(181)
            ],
        }
    calls = [
        {
            "event_id": f"call-{state}",
            "race_id": state,
            "event_type": "race_call",
            "timestamp": time,
            "time_precision": "second",
            "result": result,
            "source_url": "synthetic://example",
        }
        for state, time, result in [
            ("PA", "2024-11-06T00:10:00Z", "1"),
            ("WI", "2024-11-06T02:00:00Z", "0"),
            ("MI", "2024-11-06T03:00:00Z", "1"),
        ]
    ]
    return (
        {"markets": catalog, "pagination_complete": True, "synthetic": True},
        mappings,
        calls,
        observations,
    )


def run_demo(directory: Path) -> None:
    catalog, mappings, calls, histories = synthetic_inputs()
    events = build_events(validate_races(mappings, catalog), calls)
    panel = build_panel(events, histories, windows=[5, 30, 60])
    posterior = run_baseline(events, histories, "2024-11-06T00:05:00Z")
    write_json(directory / "catalog.json", catalog)
    for token, history in histories.items():
        write_json(directory / "history" / f"{token}.json", history)
    for name, result in [("events", events), ("panel", panel), ("posterior", posterior)]:
        write_json(directory / f"{name}.json", {"synthetic": True, **result})
