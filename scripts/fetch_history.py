"""Download public Polymarket token price histories and report coverage."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_market.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["history", *sys.argv[1:]]))
