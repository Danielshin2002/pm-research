"""Compare saved reference posterior updates to a panel with matching provenance."""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_market.evaluation.comparison import compare, markdown_report  # noqa: E402
from senate_market.io import artifact_ref, read_json, write_json  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--posterior", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/comparison_2024"))
    args = parser.parse_args()
    try:
        result = compare(read_json(args.panel), read_json(args.posterior))
        result["inputs"] = {"panel": artifact_ref(args.panel),
                            "posterior": artifact_ref(args.posterior)}
        write_json(args.output_dir / "comparison.json", result)
        (args.output_dir / "summary.md").write_text(markdown_report(result), encoding="utf-8")
        with (args.output_dir / "responses.csv").open("w", newline="") as handle:
            fields = list(result["rows"][0]) if result["rows"] else [
                "batch_id", "target_race_id", "window_minutes"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(result["rows"])
        print(markdown_report(result))
        print(f"Saved report to {args.output_dir}")
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
