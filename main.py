"""Run the research CLI directly or through the installed senate-market command."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from senate_market.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
