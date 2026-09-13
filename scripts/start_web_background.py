"""Start the Agent Mail web server as a detached background process."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=str, default="data/agent_mail.db")
    parser.add_argument("--log", type=str, default="data/web.log")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    launcher = root / "scripts" / "run_web.py"
    db_path = (root / args.db).resolve()
    log_path = (root / args.log).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    command = [sys.executable, str(launcher), "--port", str(args.port), "--db", str(db_path)]
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200 | 0x08000000
    with log_path.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            command,
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            close_fds=True,
            creationflags=flags,
        )
    time.sleep(1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
