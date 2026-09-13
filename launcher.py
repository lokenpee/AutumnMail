"""Portable Windows entry point for Agent Mail."""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import traceback
import webbrowser
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Start Agent Mail")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    root = app_root()
    db_path = args.db or (root / "data" / "agent_mail.db")
    url = f"http://{args.host}:{args.port}/?v=20260913s#/home"

    if port_open(args.host, args.port):
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    source = root / "src"
    if source.exists() and str(source) not in sys.path:
        sys.path.insert(0, str(source))

    from agent_mail.web import create_server

    server = create_server(host=args.host, port=args.port, db_path=db_path)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        root = app_root()
        log_dir = root / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "launch-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
