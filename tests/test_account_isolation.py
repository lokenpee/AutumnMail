"""Account-scoping tests for mailbox data and background AI candidates."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_mail.ai.service import AIService  # noqa: E402
from agent_mail.db import connect, initialize_database  # noqa: E402
from agent_mail.web.server import AgentMailHandler  # noqa: E402


class DummyHandler:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.response = None

    @contextmanager
    def _open_db(self):
        connection = connect(self.db_path)
        try:
            yield connection
        finally:
            connection.close()

    def _send_json(self, payload, status=None) -> None:
        self.response = payload

    def _json_error(self, message, status=None) -> None:
        raise AssertionError(message)

    def _first_account(self):
        return AgentMailHandler._first_account(self)


class AccountIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "agent_mail.db"
        initialize_database(self.db_path)
        connection = connect(self.db_path)
        with connection:
            connection.execute(
                "INSERT INTO accounts(id,provider,email,credential_ref,status) VALUES('a','163','a@163.com','ref-a','active')"
            )
            connection.execute(
                "INSERT INTO accounts(id,provider,email,credential_ref,status) VALUES('b','163','b@163.com','ref-b','disabled')"
            )
            connection.execute(
                "INSERT INTO emails(id,account_id,canonical_key,subject,received_at) VALUES('ea','a','ka','mail-a','2026-09-15T10:00:00Z')"
            )
            connection.execute(
                "INSERT INTO emails(id,account_id,canonical_key,subject,received_at) VALUES('eb','b','kb','mail-b','2026-09-15T11:00:00Z')"
            )
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source) VALUES('ca','ea','assessment_invite',0.9,'model')"
            )
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source) VALUES('cb','eb','assessment_invite',0.9,'model')"
            )
        connection.close()
        self.handler = DummyHandler(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_mail_list_only_returns_active_account_data(self) -> None:
        rows = AgentMailHandler._list_emails(self.handler)
        self.assertEqual(["ea"], [row["id"] for row in rows])

        connection = connect(self.db_path)
        with connection:
            connection.execute("UPDATE accounts SET status='disabled' WHERE id='a'")
            connection.execute("UPDATE accounts SET status='active' WHERE id='b'")
        connection.close()

        rows = AgentMailHandler._list_emails(self.handler)
        self.assertEqual(["eb"], [row["id"] for row in rows])

    def test_ai_candidates_and_single_email_are_account_scoped(self) -> None:
        service = AIService(self.db_path, account_id="a")
        self.assertEqual(["ea"], [row["id"] for row in service._load_screening_candidates(None)])
        self.assertEqual(["ea"], [row["id"] for row in service._load_analysis_candidates(None)])
        self.assertIsNone(service._load_email("eb"))

    def test_current_account_cannot_modify_another_accounts_email(self) -> None:
        with self.assertRaisesRegex(AssertionError, "当前邮箱"):
            AgentMailHandler._set_email_completed(
                self.handler,
                {"email_id": "eb", "is_completed": True},
            )

    @patch("agent_mail.web.server.save_secret")
    @patch("agent_mail.web.server.test_connection", return_value=["INBOX"])
    def test_connecting_another_mailbox_switches_active_scope(self, _test_connection, _save_secret) -> None:
        AgentMailHandler._connect_account(
            self.handler,
            {"email": "b@163.com", "auth_code": "not-a-real-secret"},
        )
        connection = connect(self.db_path)
        try:
            statuses = {
                row["id"]: row["status"]
                for row in connection.execute("SELECT id, status FROM accounts").fetchall()
            }
        finally:
            connection.close()
        self.assertEqual({"a": "disabled", "b": "active"}, statuses)
        self.assertEqual(["eb"], [row["id"] for row in AgentMailHandler._list_emails(self.handler)])


if __name__ == "__main__":
    unittest.main()
