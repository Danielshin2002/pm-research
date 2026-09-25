"""Never infer party, election outcome, or race-call time from Gamma prices."""

from datetime import date, timedelta

from senate_market.io import probability, utc

STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
EVENT_TYPES = {"poll_close", "first_returns", "race_call", "market_resolution", "other_news"}


def validate_races(rows: list[dict], catalog: dict) -> list[dict]:
    if not rows:
        raise ValueError("Race mapping is empty; review real markets before analysis")
    markets = {m["market_id"]: m for m in catalog["markets"]}
    races, ids, tokens = [], set(), set()
    for row in rows:
        required = (
            "race_id",
            "cycle",
            "senate_class",
            "state",
            "election_type",
            "market_id",
            "token_id",
            "outcome_label",
            "orientation",
            "source_url",
            "election_date",
        )
        if any(not row.get(key) for key in required):
            raise ValueError(f"Missing required mapping fields: {row.get('race_id')}")
        if row.get("reviewed", "").lower() != "true":
            raise ValueError(f"Race {row['race_id']} requires reviewed=true")
        race = dict(row)
        race["cycle"], race["senate_class"] = int(row["cycle"]), int(row["senate_class"])
        if race["state"] not in STATES or race["senate_class"] not in {1, 2, 3}:
            raise ValueError(f"Invalid state or Senate class: {row['race_id']}")
        if race["election_type"] not in {"general", "special", "primary", "runoff"}:
            raise ValueError("Election type must be general, special, primary or runoff")
        date.fromisoformat(race["election_date"])
        if not race["token_id"].isdecimal():
            raise ValueError("Token ID must be decimal")
        if race.get("unresolved_through"):
            race["unresolved_through"] = utc(race["unresolved_through"]).isoformat()
        if race["orientation"] not in {"identity", "complement"}:
            raise ValueError(
                "Orientation must be identity or complement to Democratic-win probability"
            )
        market = markets.get(race["market_id"])
        if not market or not any(
            o["token_id"] == race["token_id"] and o["label"] == race["outcome_label"]
            for o in market["outcomes"]
        ):
            raise ValueError(f"Token/label does not match Gamma catalog: {race['race_id']}")
        if race["race_id"] in ids or race["token_id"] in tokens:
            raise ValueError("Each race and selected token must appear only once")
        ids.add(race["race_id"])
        tokens.add(race["token_id"])
        races.append(race)
    return races


def build_events(
    races: list[dict],
    rows: list[dict],
    *,
    batch_minutes: int = 5,
    allow_resolution_fallback: bool = False,
) -> dict:
    if batch_minutes < 0:
        raise ValueError("batch-minutes must be nonnegative")
    by_race = {r["race_id"]: r for r in races}
    events, ids, terminal = [], set(), {}
    for row in rows:
        required = ("event_id", "event_type", "timestamp", "time_precision", "source_url")
        if any(not row.get(k) for k in required):
            raise ValueError("Events need an ID, type, timezone timestamp, precision and source")
        if row["event_id"] in ids:
            raise ValueError("Duplicate event ID")
        ids.add(row["event_id"])
        if row["event_type"] not in EVENT_TYPES or row["time_precision"] not in {
            "second",
            "minute",
        }:
            raise ValueError("Unknown event type or insufficient timestamp precision")
        race_id = row.get("race_id", "")
        if race_id not in by_race and row["event_type"] != "other_news":
            raise ValueError(f"Unknown race for event {row['event_id']}")
        event = {**row, "timestamp": utc(row["timestamp"]).isoformat(), "result": None}
        if row.get("result", "") != "":
            result = probability(row["result"])
            if result not in {0, 1} or row["event_type"] not in {"race_call", "market_resolution"}:
                raise ValueError(
                    "Only race calls/resolutions can carry a binary Democratic-win result"
                )
            event["result"] = int(result)
            key = (race_id, row["event_type"])
            if key in terminal:
                raise ValueError(
                    "Multiple calls/resolutions for one race require manual adjudication"
                )
            terminal[key] = event
        elif row["event_type"] in {"race_call", "market_resolution"}:
            raise ValueError("A call/resolution event requires a verified binary result")
        events.append(event)
    events.sort(key=lambda e: (e["timestamp"], e["event_id"]))
    selected, cutoffs = [], {}
    for race in races:
        race_id = race["race_id"]
        call = terminal.get((race_id, "race_call"))
        resolution = terminal.get((race_id, "market_resolution"))
        if call and resolution and call["result"] != resolution["result"]:
            raise ValueError(f"Conflicting call and settlement result for {race_id}")
        known = [e for e in (call, resolution) if e]
        if known:
            cutoffs[race_id] = min(e["timestamp"] for e in known)
        chosen = call or (resolution if allow_resolution_fallback else None)
        if chosen:
            selected.append(
                {**chosen, "cycle": race["cycle"], "election_type": race["election_type"]}
            )
    selected.sort(key=lambda e: (e["timestamp"], e["event_id"]))
    batches, current = [], {}
    for event in selected:
        group = (event["cycle"], event["election_type"])
        batch = current.get(group)
        # Anchor to the first event; no chaining A→B→C into arbitrarily long batches.
        if batch is None or utc(event["timestamp"]) - utc(batch["start"]) > timedelta(
            minutes=batch_minutes
        ):
            batch = {
                "batch_id": f"batch-{len(batches) + 1:04d}",
                "cycle": group[0],
                "election_type": group[1],
                "start": event["timestamp"],
                "end": event["timestamp"],
                "events": [],
            }
            current[group] = batch
            batches.append(batch)
        batch["events"].append(event)
        batch["end"] = event["timestamp"]
    return {
        "schema_version": 1,
        "races": races,
        "events": events,
        "batches": batches,
        "known_result_times": cutoffs,
        "config": {
            "batch_minutes": batch_minutes,
            "allow_resolution_fallback": allow_resolution_fallback,
        },
        "unsequenced_races": [
            r["race_id"] for r in races if r["race_id"] not in {e["race_id"] for e in selected}
        ],
    }
