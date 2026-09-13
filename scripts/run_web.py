"""Run the local Agent Mail web UI and API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_mail.web import create_server  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Agent Mail web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()

    server = create_server(host=args.host, port=args.port, db_path=args.db)
    print(f"Agent Mail UI: http://{args.host}:{args.port}")
    print(f"Database: {server.db_path}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
