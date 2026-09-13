"""Initialize the Agent Mail SQLite database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_mail.db import initialize_database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the Agent Mail database.")
    parser.add_argument("--db", type=Path, default=None, help="Override database path.")
    args = parser.parse_args()

    path = initialize_database(args.db)
    print(f"initialized: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
