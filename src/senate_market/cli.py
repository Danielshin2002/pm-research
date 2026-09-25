"""Command line workflow with explicit inputs and auditable JSON outputs."""

import argparse
import json
import sys
import tomllib
from pathlib import Path

import requests

from senate_market.bayesian.sequential import run_baseline
from senate_market.event_study.panel import build_panel
from senate_market.events.build import build_events, validate_races
from senate_market.ingestion.catalog import discover
from senate_market.ingestion.client import PublicClient
from senate_market.ingestion.history import fetch_history
from senate_market.io import artifact_ref, read_csv, read_json, write_json


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="U.S. Senate market research using public Polymarket data"
    )
    commands = root.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser(
        "discover", help="Inventory Gamma Senate candidates, including closed markets"
    )
    catalog.add_argument(
        "--end-year", type=int, help="Gamma end-date year filter, NOT election cycle"
    )
    catalog.add_argument("--closed", choices=["all", "true", "false"], default="all")
    catalog.add_argument("--tag-id")
    catalog.add_argument(
        "--slug", action="append", help="Exact market slug; bypass Senate text filter"
    )
    catalog.add_argument("--page-size", type=int, default=100, help="Markets per page (1..100)")
    catalog.add_argument("--max-pages", type=int, default=50, help="Per closed/open partition")
    catalog.add_argument("--output", type=Path, default=Path("data/interim/catalog.json"))
    history = commands.add_parser(
        "history", help="Download token price samples and coverage reports"
    )
    selection = history.add_mutually_exclusive_group(required=True)
    selection.add_argument("--token-id", action="append")
    selection.add_argument(
        "--catalog", type=Path, help="Probe every outcome in a candidate catalog"
    )
    history.add_argument("--start", required=True, help="ISO timestamp including timezone")
    history.add_argument("--end", required=True, help="Exclusive ISO timestamp including timezone")
    history.add_argument("--fidelity", type=int)
    history.add_argument("--chunk-days", type=int)
    history.add_argument("--output-dir", type=Path, default=Path("data/interim/history"))
    history.add_argument("--config", type=Path)
    for command in (catalog, history):
        command.add_argument("--cache-dir", type=Path, default=Path("data/raw/http"))
        command.add_argument("--refresh", action="store_true")
        command.add_argument("--offline", action="store_true")
    inspect = commands.add_parser("inspect", help="Print a saved candidate catalog")
    inspect.add_argument("catalog", type=Path)
    events = commands.add_parser(
        "events", help="Validate reviewed mappings and batch timestamped results"
    )
    events.add_argument("--catalog", type=Path, required=True)
    events.add_argument("--races", type=Path, required=True)
    events.add_argument("--events", type=Path, required=True)
    events.add_argument("--config", type=Path)
    events.add_argument("--output", type=Path, default=Path("data/processed/events.json"))
    panel = commands.add_parser(
        "panel", help="Build descriptive event response and exclusion tables"
    )
    bayes = commands.add_parser(
        "bayes", help="Run the fixed-loading Bayesian reference calculation"
    )
    for command in (panel, bayes):
        command.add_argument("--events", type=Path, required=True)
        command.add_argument("--history-dir", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    panel.add_argument("--config", type=Path)
    bayes.add_argument("--baseline-time", required=True)
    bayes.add_argument("--max-age-seconds", type=int, default=120)
    bayes.add_argument("--loading", type=float, default=1.0)
    demo = commands.add_parser("demo", help="Run a fully synthetic offline example")
    demo.add_argument("--output-dir", type=Path, default=Path("outputs/demo"))
    return root


def config(path: Path | None) -> dict:
    defaults = {
        "history": {"fidelity_minutes": 60, "chunk_days": 7},
        "events": {"batch_minutes": 5, "allow_resolution_fallback": False},
        "event_study": {
            "windows_minutes": [5, 30, 60, 360, 1440],
            "max_age_seconds": 120,
            "contamination_minutes": 5,
            "exclude_contaminated": True,
        },
    }
    if path:
        supplied = tomllib.loads(path.read_text())
        for section, values in supplied.items():
            if section not in defaults or not isinstance(values, dict):
                raise ValueError(f"Unknown config section {section}")
            for key, value in values.items():
                if key not in defaults[section] or type(value) is not type(defaults[section][key]):
                    raise ValueError(f"Unknown or incorrectly typed config: {section}.{key}")
                defaults[section][key] = value
    return defaults


def load_histories(events: dict, directory: Path) -> dict:
    histories = {}
    coverage_path = directory / "coverage.json"
    coverage = read_json(coverage_path) if coverage_path.exists() else None
    valid = (
        {r["token_id"]: r for r in coverage["tokens"] if r["status"] in {"observed", "empty"}}
        if coverage
        else None
    )
    for race in events["races"]:
        token = race["token_id"]
        if not token.isdecimal():
            raise ValueError("Token ID must be decimal")
        path = directory / f"{token}.json"
        if path.exists() and (valid is None or token in valid):
            if valid is not None and valid[token].get("artifact"):
                if artifact_ref(path)["sha256"] != valid[token]["artifact"]["sha256"]:
                    raise ValueError(f"History file differs from coverage manifest: {path}")
            histories[token] = read_json(path)
    return histories


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = config(getattr(args, "config", None))
        if args.command == "discover":
            client = PublicClient(args.cache_dir, refresh=args.refresh, offline=args.offline)
            result = discover(
                client,
                end_year=args.end_year,
                page_size=args.page_size,
                max_pages=args.max_pages,
                closed=args.closed,
                tag_id=args.tag_id,
                slugs=args.slug,
                progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
            write_json(args.output, result)
            print(f"Saved {len(result['markets'])} candidates to {args.output}")
            print(json.dumps(result["scans"], indent=2))
            if not result["pagination_complete"]:
                print("Partial scan: raise --max-pages or narrow the query.", file=sys.stderr)
                return 2
        elif args.command == "inspect":
            catalog = read_json(args.catalog)
            print(f"Pagination complete: {catalog['pagination_complete']}")
            for market in catalog["markets"]:
                print(f"{market['market_id']}: {market['question']}")
                for outcome in market["outcomes"]:
                    print(f"  {outcome['label']}: {outcome['token_id'] or '(no CLOB token)'}")
        elif args.command == "history":
            tokens = args.token_id
            missing = []
            if args.catalog:
                catalog = read_json(args.catalog)
                tokens = [
                    o["token_id"]
                    for m in catalog["markets"]
                    for o in m["outcomes"]
                    if o["token_id"]
                ]
                missing = [m["market_id"] for m in catalog["markets"] if not m["has_clob_tokens"]]
            tokens = sorted(set(tokens))
            if not tokens:
                raise ValueError("No CLOB token IDs available in the selected input")
            reports, failed = [], False
            for index, token in enumerate(tokens, 1):
                try:
                    client = PublicClient(
                        args.cache_dir, refresh=args.refresh, offline=args.offline
                    )
                    result = fetch_history(
                        client,
                        token,
                        args.start,
                        args.end,
                        fidelity=args.fidelity
                        if args.fidelity is not None
                        else settings["history"]["fidelity_minutes"],
                        chunk_days=args.chunk_days
                        if args.chunk_days is not None
                        else settings["history"]["chunk_days"],
                    )
                    destination = args.output_dir / f"{token}.json"
                    write_json(destination, result)
                    reports.append(
                        {
                            "token_id": token,
                            **result["coverage"],
                            "artifact": artifact_ref(destination),
                        }
                    )
                    print(
                        f"[{index}/{len(tokens)}] {token}: {result['coverage']['count']} samples",
                        flush=True,
                    )
                except (requests.RequestException, ValueError, KeyError) as exc:
                    failed = True
                    reports.append({"token_id": token, "status": "error", "error": str(exc)})
                    print(f"History failed for {token}: {exc}", file=sys.stderr)
            write_json(
                args.output_dir / "coverage.json",
                {
                    "requested_start": args.start,
                    "requested_end": args.end,
                    "tokens": reports,
                    "markets_without_tokens": missing,
                },
            )
            return 1 if failed else 0
        elif args.command == "events":
            races = validate_races(read_csv(args.races), read_json(args.catalog))
            result = build_events(races, read_csv(args.events), **settings["events"])
            result["inputs"] = {
                "catalog": artifact_ref(args.catalog),
                "races": artifact_ref(args.races),
                "events": artifact_ref(args.events),
            }
            write_json(args.output, result)
            print(f"Saved {len(result['batches'])} result batches to {args.output}")
        elif args.command in {"panel", "bayes"}:
            events = read_json(args.events)
            histories = load_histories(events, args.history_dir)
            if args.command == "panel":
                options = settings["event_study"].copy()
                options["windows"] = options.pop("windows_minutes")
                result = build_panel(events, histories, **options)
                print(
                    f"{len(result['responses'])} response rows; "
                    f"{len(result['excluded'])} exclusions"
                )
            else:
                result = run_baseline(
                    events,
                    histories,
                    args.baseline_time,
                    max_age_seconds=args.max_age_seconds,
                    loading=args.loading,
                )
            result["inputs"] = {
                "events": artifact_ref(args.events),
                "histories": [
                    artifact_ref(args.history_dir / f"{token}.json") for token in sorted(histories)
                ],
            }
            write_json(args.output, result)
        elif args.command == "demo":
            from senate_market.demo import run_demo

            run_demo(args.output_dir)
            print(f"Synthetic example saved to {args.output_dir}; these are not election findings.")
        return 0
    except (requests.RequestException, ValueError, OSError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
