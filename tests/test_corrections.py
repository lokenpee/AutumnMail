"""Manual correction endpoint tests using a temporary database."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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


class CorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "agent_mail.db"
        initialize_database(self.db_path)
        connection = connect(self.db_path)
        with connection:
            connection.execute(
                "INSERT INTO accounts(id, provider, email, credential_ref) VALUES('a','163','a@163.com','ref')"
            )
            connection.execute(
                "INSERT INTO emails(id, account_id, canonical_key, subject, received_at) VALUES('e','a','k','s','2026-09-13T00:00:00+08:00')"
            )
        connection.close()
        self.handler = DummyHandler(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_company_correction_creates_primary_link(self) -> None:
        AgentMailHandler._correct_email(self.handler, {"email_id": "e", "field": "company", "value": "字节跳动"})
        connection = connect(self.db_path)
        try:
            row = connection.execute(
                "SELECT co.canonical_name FROM email_company_links ecl JOIN companies co ON co.id = ecl.company_id WHERE ecl.email_id='e' AND ecl.link_type='primary'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual("字节跳动", row["canonical_name"])

    def test_email_list_exposes_company_id_for_dynamic_filters(self) -> None:
        AgentMailHandler._correct_email(self.handler, {"email_id": "e", "field": "company", "value": "字节跳动"})
        rows = AgentMailHandler._list_emails(self.handler)
        self.assertEqual(1, len(rows))
        self.assertIsNotNone(rows[0]["companyId"])
        self.assertEqual("字节跳动", rows[0]["company"])
        self.assertIn("bodyHtml", rows[0])

    def test_email_list_marks_unprocessed_mail_as_imported(self) -> None:
        rows = AgentMailHandler._list_emails(self.handler)
        self.assertEqual("unclassified", rows[0]["category"])
        self.assertEqual("imported", rows[0]["processingStage"])

    def test_email_review_state_is_exposed_and_can_be_cleared(self) -> None:
        connection = connect(self.db_path)
        with connection:
            connection.execute(
                "INSERT INTO processing_jobs(email_id,stage,status,last_error) VALUES('e','review_required','done','公司名不确定')"
            )
        connection.close()
        rows = AgentMailHandler._list_emails(self.handler)
        self.assertTrue(rows[0]["needsReview"])
        self.assertEqual("公司名不确定", rows[0]["reviewReason"])
        AgentMailHandler._mark_email_reviewed(self.handler, {"email_id": "e"})
        rows = AgentMailHandler._list_emails(self.handler)
        self.assertFalse(rows[0]["needsReview"])
        self.assertIsNone(rows[0]["reviewReason"])

    def test_completion_state_is_persisted_and_exposed(self) -> None:
        AgentMailHandler._set_email_completed(
            self.handler,
            {"email_id": "e", "is_completed": True},
        )
        rows = AgentMailHandler._list_emails(self.handler)
        self.assertTrue(rows[0]["isCompleted"])
        AgentMailHandler._set_email_completed(
            self.handler,
            {"email_id": "e", "is_completed": False},
        )
        rows = AgentMailHandler._list_emails(self.handler)
        self.assertFalse(rows[0]["isCompleted"])

    def test_deadline_correction_works_for_unclassified_email(self) -> None:
        AgentMailHandler._correct_email(self.handler, {"email_id": "e", "field": "deadline", "value": "2026-09-20"})
        connection = connect(self.db_path)
        try:
            row = connection.execute("SELECT due_date_local, source FROM deadlines WHERE email_id='e'").fetchone()
        finally:
            connection.close()
        self.assertEqual("2026-09-20", row["due_date_local"])
        self.assertEqual("manual", row["source"])


if __name__ == "__main__":
    unittest.main()
