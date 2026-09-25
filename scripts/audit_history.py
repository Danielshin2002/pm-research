"""Generate a local HTML/SVG report and machine-readable audit without network access."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_market.audit import audit_race, html_report  # noqa: E402
from senate_market.cli import load_histories  # noqa: E402
from senate_market.io import artifact_ref, read_json, write_json  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--history-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/history_audit_2024"))
    parser.add_argument("--jump", type=float, default=0.10)
    parser.add_argument("--flat-minutes", type=float, default=60)
    parser.add_argument("--gap-seconds", type=float, default=120)
    args = parser.parse_args()
    try:
        events = read_json(args.events)
        histories = load_histories(events, args.history_dir)
        thresholds = {"jump": args.jump, "flat_minutes": args.flat_minutes,
                      "gap_seconds": args.gap_seconds}
        report = {"schema_version": 1, "thresholds": thresholds, "races": [],
                  "inputs": {"events": artifact_ref(args.events), "histories": [
                      artifact_ref(args.history_dir / f"{token}.json")
                      for token in sorted(histories)]}}
        manifest = args.history_dir / "coverage.json"
        if manifest.exists():
            report["inputs"]["coverage"] = artifact_ref(manifest)
        plotted = {}
        for race in events["races"]:
            result, points = audit_race(race, histories.get(race["token_id"]),
                                        events["events"], **thresholds)
            report["races"].append(result)
            plotted[race["race_id"]] = points
        page = html_report(report, plotted)
        write_json(args.output_dir / "audit.json", report)
        (args.output_dir / "index.html").write_text(page, encoding="utf-8")
        print(f"Audited {len(report['races'])} races. Open {args.output_dir / 'index.html'}")
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
