"""Mail parser tests."""

from __future__ import annotations

import sys
import unittest
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_mail.mail.parser import parse_email  # noqa: E402


class MailParserTests(unittest.TestCase):
    def test_parses_chinese_headers_and_plain_body(self) -> None:
        message = EmailMessage()
        message["Subject"] = "面试邀请"
        message["From"] = "字节跳动 HR <hr@example.com>"
        message["To"] = "candidate@163.com"
        message["Message-ID"] = "<mail-1@example.com>"
        message["Date"] = "Fri, 11 Sep 2026 09:30:00 +0800"
        message.set_content("您好，请参加面试。")

        parsed = parse_email(message.as_bytes())

        self.assertEqual("面试邀请", parsed.subject)
        self.assertEqual("字节跳动 HR", parsed.from_name)
        self.assertEqual("hr@example.com", parsed.from_email)
        self.assertEqual("message-id:<mail-1@example.com>", parsed.canonical_key)
        self.assertIn("面试", parsed.body_text)

    def test_uses_content_hash_without_message_id(self) -> None:
        message = EmailMessage()
        message["Subject"] = "笔试通知"
        message["From"] = "hr@example.com"
        message["To"] = "candidate@163.com"
        message.set_content("请完成笔试。")

        parsed = parse_email(message.as_bytes(), fallback_uid="42")

        self.assertIsNone(parsed.message_id)
        self.assertEqual(64, len(parsed.canonical_key))


if __name__ == "__main__":
    unittest.main()
