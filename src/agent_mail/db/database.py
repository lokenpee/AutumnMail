"""SQLite connection and initialization utilities."""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

def _schema_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "agent_mail" / "db" / "schema.sql"
    return Path(__file__).with_name("schema.sql")


SCHEMA_PATH = _schema_path()


def default_db_path() -> Path:
    """Return the default user-scoped database path.

    The path can be overridden with AGENT_MAIL_DB_PATH, which is also useful
    for tests and local development.
    """

    override = os.environ.get("AGENT_MAIL_DB_PATH")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "AgentMail" / "agent_mail.db"


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with the project's required pragmas."""

    path = Path(db_path).expanduser().resolve() if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a transaction and roll back on failure."""

    try:
        connection.execute("BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def initialize_database(db_path: str | Path | None = None) -> Path:
    """Create the database schema if it does not exist and return its path."""

    path = Path(db_path).expanduser().resolve() if db_path else default_db_path()
    connection = connect(path)
    try:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        connection.executescript(schema)
        _migrate_classification_other(connection)
        _repair_processing_stages(connection)
        connection.commit()
    finally:
        connection.close()
    return path


def _migrate_classification_other(connection: sqlite3.Connection) -> None:
    """Allow the 'other' primary classification on existing databases."""

    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'classifications'"
    ).fetchone()
    if not row or not row["sql"] or "'other'" in row["sql"]:
        return

    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        with connection:
            connection.execute("DROP TABLE IF EXISTS classifications_v1")
            connection.execute("ALTER TABLE classifications RENAME TO classifications_v1")
            connection.execute(
                """
                CREATE TABLE classifications (
                    id TEXT PRIMARY KEY,
                    email_id TEXT NOT NULL UNIQUE REFERENCES emails(id) ON DELETE CASCADE,
                    primary_type TEXT NOT NULL CHECK (primary_type IN (
                        'application_received', 'rejected', 'assessment_invite',
                        'written_test_invite', 'interview_invite', 'offer',
                        'other', 'unclassified'
                    )),
                    confidence REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
                    source TEXT NOT NULL DEFAULT 'rule' CHECK (source IN ('rule', 'model', 'user')),
                    rule_id TEXT,
                    model_version TEXT,
                    reason TEXT,
                    is_manual_override INTEGER NOT NULL DEFAULT 0 CHECK (is_manual_override IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            connection.execute(
                """
                INSERT INTO classifications (
                    id, email_id, primary_type, confidence, source, rule_id,
                    model_version, reason, is_manual_override, created_at, updated_at
                )
                SELECT
                    id, email_id, primary_type, confidence, source, rule_id,
                    model_version, reason, is_manual_override, created_at, updated_at
                FROM classifications_v1
                """
            )
            connection.execute("DROP TABLE classifications_v1")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_classifications_type ON classifications(primary_type)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_classifications_confidence ON classifications(confidence)")
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version, description) VALUES (2, 'allow other classification')")
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _repair_processing_stages(connection: sqlite3.Connection) -> None:
    """Repair stages that were reset by older sync behavior."""

    with connection:
        connection.execute(
            """
            UPDATE processing_jobs
            SET stage = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM classifications c
                        WHERE c.email_id = processing_jobs.email_id
                          AND c.reason = 'llm: structured extraction'
                    ) THEN 'ready'
                    WHEN EXISTS (
                        SELECT 1 FROM classifications c
                        WHERE c.email_id = processing_jobs.email_id
                    ) THEN 'classified'
                    ELSE stage
                END,
                status = 'done',
                last_error = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE stage = 'imported'
              AND EXISTS (
                  SELECT 1 FROM classifications c
                  WHERE c.email_id = processing_jobs.email_id
              )
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, description) VALUES (3, 'repair processing stages')"
        )


def get_schema_version(connection: sqlite3.Connection) -> int:
    """Return the current schema version, or zero if the database is empty."""

    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
    ).fetchone()
    return int(row["version"])

def backup_database(db_path: str | Path | None = None, backup_dir: str | Path | None = None) -> Path:
    """Create a consistent SQLite backup and return the backup path."""

    source_path = Path(db_path).expanduser().resolve() if db_path else default_db_path()
    target_dir = Path(backup_dir).expanduser().resolve() if backup_dir else source_path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target_path = target_dir / f"{source_path.stem}-{timestamp}.db"

    source = sqlite3.connect(source_path, timeout=30)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return target_path
