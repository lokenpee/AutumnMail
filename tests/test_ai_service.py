"""AI service candidate selection tests without model calls."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from unittest.mock import Mock, patch  # noqa: E402

from agent_mail.ai.prompts import ANALYSIS_SCHEMA_EXAMPLE  # noqa: E402
from agent_mail.ai.service import AIService  # noqa: E402
from agent_mail.db import connect, initialize_database  # noqa: E402


class AIServiceCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "agent_mail.db"
        initialize_database(self.db_path)
        connection = connect(self.db_path)
        with connection:
            connection.execute(
                "INSERT INTO accounts(id, provider, email, credential_ref) VALUES('a','163','a@163.com','ref')"
            )
            for index in range(3):
                connection.execute(
                    "INSERT INTO emails(id, account_id, canonical_key, subject, received_at) VALUES(?,?,?,?,?)",
                    (f"e{index}", "a", f"k{index}", f"subject {index}", f"2026-09-{13-index:02d}T00:00:00+08:00"),
                )
        connection.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_screening_candidates_without_limit_returns_all(self) -> None:
        service = AIService(self.db_path)
        self.assertEqual(3, len(service._load_screening_candidates(None)))
        self.assertEqual(1, len(service._load_screening_candidates(1)))

    def test_analysis_candidates_exclude_other_and_unclassified(self) -> None:
        connection = connect(self.db_path)
        with connection:
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source) VALUES('c0','e0','assessment_invite',0.9,'model')"
            )
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source) VALUES('c1','e1','other',0.9,'model')"
            )
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source) VALUES('c2','e2','unclassified',0.0,'model')"
            )
        connection.close()
        service = AIService(self.db_path)
        self.assertEqual(1, len(service._load_analysis_candidates(None)))


    def test_screening_pending_skips_finished_and_manual_results(self) -> None:
        connection = connect(self.db_path)
        with connection:
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source) VALUES('c0','e0','unclassified',0.0,'model')"
            )
            connection.execute(
                "INSERT INTO processing_jobs(email_id,stage,status) VALUES('e0','classified','done')"
            )
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source,is_manual_override) VALUES('c1','e1','other',1.0,'user',1)"
            )
        connection.close()
        service = AIService(self.db_path)
        pending = service._load_screening_candidates(None, mode="pending")
        all_candidates = service._load_screening_candidates(None, mode="all")
        self.assertEqual(["e2"], [row["id"] for row in pending])
        self.assertEqual({"e0", "e2"}, {row["id"] for row in all_candidates})

    def test_analysis_modes_use_processing_stage_and_company_link(self) -> None:
        connection = connect(self.db_path)
        with connection:
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source,reason) VALUES('c0','e0','assessment_invite',0.9,'model','screening: relevant')"
            )
            connection.execute(
                "INSERT INTO processing_jobs(email_id,stage,status) VALUES('e0','ready','done')"
            )
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source) VALUES('c1','e1','other',0.9,'model')"
            )
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source,reason) VALUES('c2','e2','unclassified',0.8,'model','screening: relevant')"
            )
            connection.execute(
                "INSERT INTO companies(id,canonical_name,normalized_name) VALUES('co0','测试公司','测试公司')"
            )
            connection.execute(
                "INSERT INTO email_company_links(id,email_id,company_id,link_type,source,confidence,is_confirmed) VALUES('l0','e0','co0','primary','model',0.9,0)"
            )
        connection.close()
        service = AIService(self.db_path)
        pending = service._load_analysis_candidates(None, mode="pending")
        unresolved = service._load_analysis_candidates(None, mode="company_unresolved")
        all_relevant = service._load_analysis_candidates(None, mode="all_relevant")
        self.assertEqual(["e2"], [row["id"] for row in pending])
        self.assertEqual(["e2"], [row["id"] for row in unresolved])
        self.assertEqual({"e0", "e2"}, {row["id"] for row in all_relevant})

    def test_screen_batch_real_pipeline_with_mocked_network(self) -> None:
        service = AIService(self.db_path)
        service._load_config = lambda key, defaults: {
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "fake",
            "concurrency": 2,
            "max_chars": 1000,
            "max_tokens": 100,
            "timeout": 5,
        }
        response = {
            "is_relevant": True,
            "confidence": 0.9,
            "category_hint": "assessment_invite",
            "reason": "test",
        }
        with patch("agent_mail.ai.service.load_secret", return_value="fake-key"), patch(
            "agent_mail.ai.service.OpenAICompatibleClient.chat_json",
            return_value=response,
        ):
            result = service.screen_batch(limit=None, mode="pending")
        self.assertEqual(3, result["screened"])
        self.assertEqual(3, result["relevant"])
        connection = connect(self.db_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM classifications WHERE primary_type='assessment_invite'"
            ).fetchone()["count"]
            jobs = connection.execute(
                "SELECT COUNT(*) AS count FROM processing_jobs WHERE stage='classified' AND status='done'"
            ).fetchone()["count"]
        finally:
            connection.close()
        self.assertEqual(3, count)
        self.assertEqual(3, jobs)

    def test_analyze_batch_real_pipeline_with_mocked_network(self) -> None:
        connection = connect(self.db_path)
        with connection:
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source,reason) VALUES('c0','e0','assessment_invite',0.9,'model','screening: relevant')"
            )
        connection.close()
        service = AIService(self.db_path)
        service._load_config = lambda key, defaults: {
            "base_url": "https://api.deepseek.com",
            "model": "fake",
            "concurrency": 1,
            "max_chars": 1000,
            "max_tokens": 100,
            "timeout": 5,
        }
        with patch("agent_mail.ai.service.load_secret", return_value="fake-key"), patch(
            "agent_mail.ai.service.OpenAICompatibleClient.chat_json",
            return_value=ANALYSIS_SCHEMA_EXAMPLE,
        ):
            result = service.analyze_batch(limit=None, mode="pending")
        self.assertEqual(1, result["analyzed"])
        self.assertEqual(0, result["failed"])
        connection = connect(self.db_path)
        try:
            company_count = connection.execute("SELECT COUNT(*) AS count FROM companies").fetchone()["count"]
            ready_count = connection.execute(
                "SELECT COUNT(*) AS count FROM processing_jobs WHERE stage='ready' AND status='done'"
            ).fetchone()["count"]
            deadline_count = connection.execute(
                "SELECT COUNT(*) AS count FROM deadlines WHERE email_id='e0' AND source='auto'"
            ).fetchone()["count"]
            event_count = connection.execute(
                "SELECT COUNT(*) AS count FROM calendar_events WHERE email_id='e0' AND source='auto'"
            ).fetchone()["count"]
            link_count = connection.execute(
                "SELECT COUNT(*) AS count FROM action_links WHERE email_id='e0'"
            ).fetchone()["count"]
        finally:
            connection.close()
        self.assertEqual(1, company_count)
        self.assertEqual(1, ready_count)
        self.assertEqual(1, deadline_count)
        self.assertEqual(1, event_count)
        self.assertEqual(1, link_count)

    def test_screening_three_email_button_with_mocked_network(self) -> None:
        service = AIService(self.db_path)
        service._load_config = lambda key, defaults: {
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "fake",
            "max_chars": 1000,
            "max_tokens": 100,
            "timeout": 5,
        }
        response = {
            "is_relevant": False,
            "confidence": 0.8,
            "category_hint": "other",
            "reason": "test",
        }
        with patch("agent_mail.ai.service.load_secret", return_value="fake-key"), patch(
            "agent_mail.ai.service.OpenAICompatibleClient.chat_json",
            return_value=response,
        ):
            result = service.test_screening_emails(limit=3)
        self.assertEqual(3, len(result["results"]))
        self.assertTrue(all(item["ok"] for item in result["results"]))
        self.assertFalse(result["persisted"])

    def test_analysis_three_email_button_with_mocked_network(self) -> None:
        connection = connect(self.db_path)
        with connection:
            connection.execute(
                "INSERT INTO classifications(id,email_id,primary_type,confidence,source,reason) VALUES('c0','e0','assessment_invite',0.9,'model','screening: relevant')"
            )
        connection.close()
        service = AIService(self.db_path)
        service._load_config = lambda key, defaults: {
            "base_url": "https://api.deepseek.com",
            "model": "fake",
            "max_chars": 1000,
            "max_tokens": 1000,
            "timeout": 5,
        }
        with patch("agent_mail.ai.service.load_secret", return_value="fake-key"), patch(
            "agent_mail.ai.service.OpenAICompatibleClient.chat_json",
            return_value=ANALYSIS_SCHEMA_EXAMPLE,
        ):
            result = service.test_analysis_emails(limit=3)
        self.assertEqual(1, len(result["results"]))
        self.assertTrue(result["results"][0]["ok"])
        self.assertFalse(result["persisted"])
        output = result["results"][0]["analysis"]
        self.assertIn("primary_link", output)
        self.assertNotIn("events", output)
        self.assertNotIn("action_links", output)

    def test_analysis_persists_review_required_state(self) -> None:
        service = AIService(self.db_path)
        connection = connect(self.db_path)
        try:
            with connection:
                service._persist_analysis(
                    connection,
                    "e0",
                    {
                        "email_category": "assessment_invite",
                        "company": None,
                        "deadlines": [],
                        "events": [],
                        "needs_review": True,
                        "review_reason": "公司名不确定",
                        "field_confidence": {},
                    },
                )
            row = connection.execute(
                "SELECT stage, status, last_error FROM processing_jobs WHERE email_id='e0'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual("review_required", row["stage"])
        self.assertEqual("done", row["status"])
        self.assertEqual("公司名不确定", row["last_error"])

    def test_recheck_fills_missing_company_and_deadline(self) -> None:
        service = AIService(self.db_path)
        client = Mock()
        client.chat_json.return_value = {
            "company": {"name": "腾讯", "source": "body", "confidence": 0.95, "evidence": "腾讯校招"},
            "deadline": {"raw_date": "2026年09月20日 12:43 失效", "date": "2026-09-20", "time": "12:43", "deadline_type": "absolute", "confidence": 0.9},
            "review_reason": None,
        }
        analysis = {
            "schema_version": "3.0",
            "email_category": "assessment_invite",
            "email_category_confidence": 0.9,
            "company": None,
            "deadline": None,
            "interview": None,
            "primary_link": None,
            "needs_review": False,
            "review_reason": None,
        }
        merged = service._recheck_missing_fields(
            client,
            {"subject": "测评邀请", "body_text": "腾讯测评将于 2026年09月20日 12:43 失效", "received_at": "2026-09-13T12:43:00+08:00"},
            analysis,
            2000,
        )
        self.assertEqual("腾讯", merged["company"]["name"])
        self.assertEqual("2026-09-20", merged["deadline"]["date"])
        self.assertFalse(merged["needs_review"])

    def test_recheck_marks_review_when_fields_remain_missing(self) -> None:
        service = AIService(self.db_path)
        client = Mock()
        client.chat_json.return_value = {"company": None, "deadline": None, "review_reason": "仍未找到公司名"}
        analysis = {
            "email_category": "interview_invite",
            "company": None,
            "deadline": None,
            "needs_review": False,
            "review_reason": None,
        }
        merged = service._recheck_missing_fields(
            client,
            {"subject": "面试邀请", "body_text": "欢迎参加面试", "received_at": "2026-09-13T12:43:00+08:00"},
            analysis,
            2000,
        )
        self.assertTrue(merged["needs_review"])
        self.assertIn("仍未找到公司名", merged["review_reason"])

    def test_screen_batch_pause_persists_completed_items(self) -> None:
        service = AIService(self.db_path)
        service._load_config = lambda key, defaults: {
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "fake",
            "concurrency": 1,
            "max_chars": 1000,
            "max_tokens": 100,
            "timeout": 5,
        }
        service._screen_one = lambda client, email, max_chars: {
            "ok": True,
            "screening": {"is_relevant": False, "confidence": 0.9, "category_hint": "other", "reason": "test"},
        }
        completed = []
        with patch("agent_mail.ai.service.load_secret", return_value="fake-key"):
            result = service.screen_batch(
                limit=None,
                progress_callback=lambda count, total, update=None: completed.append(count),
                should_pause=lambda: bool(completed),
            )
        self.assertTrue(result["paused"])
        self.assertEqual(1, result["screened"])
        connection = connect(self.db_path)
        try:
            count = connection.execute("SELECT COUNT(*) AS count FROM classifications WHERE primary_type='other'").fetchone()["count"]
        finally:
            connection.close()
        self.assertEqual(1, count)


if __name__ == "__main__":
    unittest.main()
