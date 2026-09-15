"""Fail if staged or tracked Git files look like secrets/private runtime data."""

from __future__ import annotations

import re
import subprocess
import sys
import argparse
from pathlib import Path

BLOCKED_PATHS = (
    re.compile(r"^data/", re.I),
    re.compile(r"\.(db|sqlite|sqlite3|log|pem|key|p12)$", re.I),
    re.compile(r"(^|/)(\.env($|\.)|credentials\.json$|secrets\.json$)", re.I),
)
SECRET_PATTERNS = (
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{12,}")),
    ("GitHub token", re.compile(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY")),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}", re.I)),
)


def staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all-tracked",
        action="store_true",
        help="scan every Git-tracked file (recommended before building a release)",
    )
    args = parser.parse_args(argv)
    files = tracked_files() if args.all_tracked else staged_files()
    problems: list[str] = []
    for name in files:
        if any(pattern.search(name) for pattern in BLOCKED_PATHS):
            problems.append(f"{name}: blocked private/runtime path")
            continue
        path = Path(name)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "redacted" in line.lower():
                continue
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    problems.append(f"{name}:{line_number}: possible {label}")
                    break
    if problems:
        print("Potential secrets detected:")
        print("\n".join(problems))
        return 1
    scope = "tracked" if args.all_tracked else "staged"
    print(f"No obvious secrets or private runtime files in {len(files)} {scope} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
