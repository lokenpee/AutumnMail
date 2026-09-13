"""IMAP compatibility tests."""

from __future__ import annotations

import imaplib
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_mail.mail.imap_client import NeteaseImapClient  # noqa: E402


class FakeConnection:
    def __init__(self) -> None:
        self.calls = []

    def _simple_command(self, command: str, value: str):
        self.calls.append((command, value))
        return "OK", []

    def uid(self, command: str, *args):
        self.calls.append((command, args))
        return "OK", [b"3 5 8"]


class ImapClientTests(unittest.TestCase):
    def test_sends_163_id_command(self) -> None:
        connection = FakeConnection()
        NeteaseImapClient._send_client_id(connection)

        self.assertIn("ID", imaplib.Commands)
        self.assertEqual("ID", connection.calls[0][0])
        self.assertIn('"name" "AgentMail"', connection.calls[0][1])

    def test_search_range_uses_inclusive_imap_start_and_exclusive_end(self) -> None:
        connection = FakeConnection()
        client = NeteaseImapClient(email="a@163.com", auth_code="test")
        client._connection = connection

        uids = client.search_range(date(2026, 9, 1), date(2026, 9, 30))

        self.assertEqual(["3", "5", "8"], uids)
        self.assertEqual(("SEARCH", (None, "SINCE", "01-Sep-2026", "BEFORE", "01-Oct-2026")), connection.calls[0])


if __name__ == "__main__":
    unittest.main()
