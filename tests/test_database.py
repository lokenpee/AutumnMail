"""Database schema tests."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_mail.db import backup_database, connect, get_schema_version, initialize_database  # noqa: E402


EXPECTED_TABLES = {
    "accounts",
    "folders",
    "emails",
    "email_locations",
    "companies",
    "company_aliases",
    "positions",
    "email_company_links",
    "classifications",
    "email_user_states",
    "deadlines",
    "calendar_events",
    "attachments",
    "action_links",
    "classification_rules",
    "processing_jobs",
    "reminders",
    "settings",
    "audit_logs",
    "schema_migrations",
}


class DatabaseSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "agent_mail.db"
        initialize_database(self.db_path)
        self.connection = connect(self.db_path)
        self._insert_base_data()

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def _insert_base_data(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO accounts (
                    id, provider, email, credential_ref
                ) VALUES (?, ?, ?, ?)
                """,
                ("account-1", "163", "candidate@163.com", "credential/account-1"),
            )
            self.connection.execute(
                """
                INSERT INTO folders (
                    id, account_id, name, folder_type, enabled, uidvalidity
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("folder-1", "account-1", "INBOX", "inbox", 1, "100"),
            )
            self.connection.execute(
                """
                INSERT INTO emails (
                    id, account_id, canonical_key, message_id, subject,
                    from_email, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "email-1",
                    "account-1",
                    "message-id:one@example.com",
                    "<one@example.com>",
                    "面试邀请",
                    "hr@example.com",
                    "2026-09-11T02:00:00.000Z",
                ),
            )
            self.connection.execute(
                """
                INSERT INTO email_locations (
                    id, email_id, folder_id, uid, is_read
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("location-1", "email-1", "folder-1", "42", 0),
            )
            self.connection.execute(
                """
                INSERT INTO companies (
                    id, canonical_name, normalized_name
                ) VALUES (?, ?, ?)
                """,
                ("company-1", "示例公司", "示例公司"),
            )
            self.connection.execute(
                """
                INSERT INTO positions (
                    id, company_id, title, normalized_title, location
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("position-1", "company-1", "后端开发", "后端开发", "上海"),
            )
            self.connection.execute(
                """
                INSERT INTO classifications (
                    id, email_id, primary_type, confidence, source
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("classification-1", "email-1", "interview_invite", 0.98, "rule"),
            )
            self.connection.execute(
                """
                INSERT INTO email_user_states (email_id)
                VALUES (?)
                """,
                ("email-1",),
            )

    def test_schema_contains_expected_tables(self) -> None:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        table_names = {row["name"] for row in rows if not row["name"].startswith("sqlite_")}
        self.assertTrue(EXPECTED_TABLES.issubset(table_names))
        self.assertEqual(3, get_schema_version(self.connection))

    def test_repairs_processing_stage_when_sync_reset_old_rows(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO processing_jobs(email_id, stage, status)
                VALUES('email-1', 'imported', 'done')
                ON CONFLICT(email_id) DO UPDATE SET stage='imported', status='done'
                """
            )
        initialize_database(self.db_path)
        connection = connect(self.db_path)
        try:
            row = connection.execute(
                "SELECT stage, status FROM processing_jobs WHERE email_id='email-1'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual('classified', row['stage'])
        self.assertEqual('done', row['status'])

    def test_duplicate_canonical_key_is_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO emails (
                        id, account_id, canonical_key, subject, received_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "email-duplicate",
                        "account-1",
                        "message-id:one@example.com",
                        "重复邮件",
                        "2026-09-11T03:00:00.000Z",
                    ),
                )

    def test_same_email_can_exist_in_multiple_folders(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO folders (id, account_id, name, folder_type, uidvalidity)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("folder-2", "account-1", "Archive", "custom", "100"),
            )
            self.connection.execute(
                """
                INSERT INTO email_locations (id, email_id, folder_id, uid)
                VALUES (?, ?, ?, ?)
                """,
                ("location-2", "email-1", "folder-2", "77"),
            )
        count = self.connection.execute(
            "SELECT COUNT(*) AS count FROM email_locations WHERE email_id = ?",
            ("email-1",),
        ).fetchone()["count"]
        self.assertEqual(2, count)

    def test_only_one_primary_company_link_is_allowed(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO email_company_links (
                    id, email_id, company_id, position_id, link_type,
                    source, confidence, is_confirmed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "link-primary",
                    "email-1",
                    "company-1",
                    "position-1",
                    "primary",
                    "user",
                    1.0,
                    1,
                ),
            )

        with self.assertRaises(sqlite3.IntegrityError):
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO companies (
                        id, canonical_name, normalized_name
                    ) VALUES (?, ?, ?)
                    """,
                    ("company-2", "另一家公司", "另一家公司"),
                )
                self.connection.execute(
                    """
                    INSERT INTO email_company_links (
                        id, email_id, company_id, link_type, source,
                        confidence, is_confirmed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "link-primary-2",
                        "email-1",
                        "company-2",
                        "primary",
                        "model",
                        0.8,
                        0,
                    ),
                )

    def test_date_only_deadline_requires_local_date(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO deadlines (
                        id, email_id, precision, source, confidence
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    ("deadline-invalid", "email-1", "date", "manual", 1.0),
                )

    def test_manual_deadline_override_is_persisted(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO deadlines (
                    id, email_id, label, due_date_local, precision,
                    source, confidence, is_manual_override
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "deadline-1",
                    "email-1",
                    "测评截止",
                    "2026-09-20",
                    "date",
                    "manual",
                    1.0,
                    1,
                ),
            )
        row = self.connection.execute(
            "SELECT source, is_manual_override FROM deadlines WHERE id = ?",
            ("deadline-1",),
        ).fetchone()
        self.assertEqual("manual", row["source"])
        self.assertEqual(1, row["is_manual_override"])

    def test_received_at_range_is_inclusive(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO emails (
                    id, account_id, canonical_key, subject, received_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "email-2",
                    "account-1",
                    "message-id:two@example.com",
                    "笔试邀请",
                    "2026-09-11T16:00:00.000Z",
                ),
            )
        rows = self.connection.execute(
            """
            SELECT id FROM emails
            WHERE received_at >= ? AND received_at <= ?
            ORDER BY received_at
            """,
            ("2026-09-11T00:00:00.000Z", "2026-09-11T23:59:59.999Z"),
        ).fetchall()
        self.assertEqual(["email-1", "email-2"], [row["id"] for row in rows])

    def test_foreign_keys_are_enforced(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO email_locations (id, email_id, folder_id, uid)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("location-invalid", "missing-email", "folder-1", "99"),
                )


    def test_backup_database_creates_snapshot(self) -> None:
        backup_dir = Path(self.temp_dir.name) / "backups"
        backup_path = backup_database(self.db_path, backup_dir)

        self.assertTrue(backup_path.exists())
        backup_connection = connect(backup_path)
        try:
            count = backup_connection.execute("SELECT COUNT(*) AS count FROM emails").fetchone()["count"]
        finally:
            backup_connection.close()
        self.assertEqual(1, count)


    def test_other_primary_classification_is_allowed(self) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE classifications SET primary_type = 'other' WHERE id = ?",
                ("classification-1",),
            )
        row = self.connection.execute(
            "SELECT primary_type FROM classifications WHERE id = ?",
            ("classification-1",),
        ).fetchone()
        self.assertEqual("other", row["primary_type"])


if __name__ == "__main__":
    unittest.main()
