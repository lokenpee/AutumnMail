"""IMAP compatibility tests."""

from __future__ import annotations

import imaplib
import sys
import unittest
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


class ImapClientTests(unittest.TestCase):
    def test_sends_163_id_command(self) -> None:
        connection = FakeConnection()
        NeteaseImapClient._send_client_id(connection)

        self.assertIn("ID", imaplib.Commands)
        self.assertEqual("ID", connection.calls[0][0])
        self.assertIn('"name" "AgentMail"', connection.calls[0][1])


if __name__ == "__main__":
    unittest.main()
