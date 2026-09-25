"""Inspect a saved Gamma catalog without making network requests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_market.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["inspect", *sys.argv[1:]]))
