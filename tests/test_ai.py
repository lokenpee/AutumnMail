"""AI prompt, schema, and client tests."""

from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_mail.ai.client import OpenAICompatibleClient  # noqa: E402
from agent_mail.ai.prefilter import prefilter_email  # noqa: E402
from agent_mail.ai.service import _resolve_deadline  # noqa: E402
from agent_mail.ai.prompts import ANALYSIS_SCHEMA_EXAMPLE, SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from agent_mail.ai.schema import AnalysisValidationError, validate_analysis  # noqa: E402


class AiAnalysisTests(unittest.TestCase):
    def test_validates_expected_schema_example(self) -> None:
        result = validate_analysis(ANALYSIS_SCHEMA_EXAMPLE)

        self.assertEqual(
            {
                "schema_version",
                "email_category",
                "email_category_confidence",
                "company",
                "deadline",
                "interview",
                "primary_link",
                "needs_review",
                "review_reason",
            },
            set(result),
        )
        self.assertEqual("interview_invite", result["email_category"])
        self.assertEqual("3.0", result["schema_version"])
        self.assertEqual("body", result["company"]["source"])
        self.assertGreater(result["company"]["confidence"], 0)
        self.assertLessEqual(len(result["company"]["evidence"]), 30)
        self.assertEqual("interview_meeting", result["primary_link"]["link_type"])
        self.assertEqual("2026-09-18", result["interview"]["date"])
        self.assertLessEqual(len(ANALYSIS_SCHEMA_EXAMPLE), 9)

    def test_prompt_contains_category_disambiguation_and_source_rules(self) -> None:
        self.assertIn("通过笔试", SYSTEM_PROMPT)
        self.assertIn("interview_invite", SYSTEM_PROMPT)
        self.assertIn("正文（含签名），其次主题，再其次发件人显示名", SYSTEM_PROMPT)
        self.assertIn("所有 evidence 均不得超过 30 个字符", SYSTEM_PROMPT)
        self.assertIn("confidence 低于 0.75", SYSTEM_PROMPT)
        self.assertIn("不要输出其他字段", SYSTEM_PROMPT)
        self.assertIn("primary_link", SYSTEM_PROMPT)

    def test_primary_link_ignores_unsubscribe_and_truncates_evidence(self) -> None:
        data = dict(ANALYSIS_SCHEMA_EXAMPLE)
        data["primary_link"] = dict(ANALYSIS_SCHEMA_EXAMPLE["primary_link"])
        data["primary_link"]["link_type"] = "unsubscribe"
        data["company"] = dict(ANALYSIS_SCHEMA_EXAMPLE["company"])
        data["company"]["evidence"] = "很长的证据" * 20
        result = validate_analysis(data)
        self.assertIsNone(result["primary_link"])
        self.assertLessEqual(len(result["company"]["evidence"]), 30)

    def test_prompt_explains_deadline_meaning_and_expiry_phrases(self) -> None:
        self.assertIn("deadline", SYSTEM_PROMPT)
        self.assertIn("失效", SYSTEM_PROMPT)
        self.assertIn("有效期", SYSTEM_PROMPT)
        self.assertIn("确认", SYSTEM_PROMPT)
        self.assertIn("2026-09-20", SYSTEM_PROMPT)

    def test_long_email_prompt_keeps_bottom_deadline(self) -> None:
        deadline_text = "本次测试邀请于 2026年09月13日 周日 12:43 ，于 2026年09月20日 周日 12:43 失效"
        prompt = build_user_prompt(
            {
                "subject": "测评邀请",
                "from_name": "HR",
                "from_email": "hr@example.com",
                "received_at": "2026-09-13T12:43:00+08:00",
                "body_text": "开头内容" + ("填充" * 5000) + deadline_text,
            },
            max_chars=1000,
        )
        self.assertIn("中间内容省略", prompt)
        self.assertIn(deadline_text, prompt)

    def test_rejects_invalid_category(self) -> None:
        invalid = dict(ANALYSIS_SCHEMA_EXAMPLE)
        invalid["email_category"] = "unknown_category"

        with self.assertRaises(AnalysisValidationError):
            validate_analysis(invalid)

    def test_builds_prompt_with_email_content_and_json_instruction(self) -> None:
        prompt = build_user_prompt(
            {
                "subject": "字节跳动面试邀请",
                "from_name": "HR",
                "from_email": "hr@example.com",
                "received_at": "2026-09-12T09:00:00+08:00",
                "body_text": "请于 9 月 18 日前确认是否参加面试。",
            }
        )

        self.assertIn("字节跳动面试邀请", prompt)
        self.assertIn("只输出规定的 json 字段", prompt)
        self.assertIn("9 月 18 日", prompt)

    def test_deepseek_endpoint_derivation(self) -> None:
        client = OpenAICompatibleClient(api_key="test", base_url="https://api.deepseek.com")
        self.assertEqual("https://api.deepseek.com/chat/completions", client._endpoint())
        self.assertEqual("https://api.deepseek.com/models", client._models_endpoint())

        client = OpenAICompatibleClient(
            api_key="test",
            base_url="https://api.deepseek.com/chat/completions",
        )
        self.assertEqual("https://api.deepseek.com/chat/completions", client._endpoint())
        self.assertEqual("https://api.deepseek.com/models", client._models_endpoint())

    def test_arbitrary_openai_compatible_endpoint_derivation(self) -> None:
        client = OpenAICompatibleClient(
            api_key="test",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.assertEqual(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            client._endpoint(),
        )
        self.assertEqual(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
            client._models_endpoint(),
        )

    def test_chat_json_retries_without_response_format(self) -> None:
        calls = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]}).encode("utf-8")

        def fake_urlopen(request, timeout):
            calls.append(json.loads(request.data.decode("utf-8")))
            if len(calls) == 1:
                detail = b'{"error":{"message":"response_format is not supported"}}'
                raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(detail))
            return FakeResponse()

        client = OpenAICompatibleClient(api_key="test", base_url="https://api.example.com/v1")
        with patch("agent_mail.ai.client.urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.chat_json("system", "user")

        self.assertEqual({"ok": True}, result)
        self.assertEqual(2, len(calls))
        self.assertIn("response_format", calls[0])
        self.assertNotIn("response_format", calls[1])

    def test_model_list_accepts_common_compatible_shapes(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"models": [{"name": "qwen-plus"}]}).encode("utf-8")

        client = OpenAICompatibleClient(api_key="test", base_url="https://api.example.com/v1")
        with patch("agent_mail.ai.client.urllib.request.urlopen", return_value=FakeResponse()):
            self.assertEqual(["qwen-plus"], client.list_models())


    def test_prefilter_skips_marketing_email(self) -> None:
        result = prefilter_email(
            {
                "subject": "限时优惠：简历修改训练营",
                "from_email": "promo@example.com",
                "body_text": "免费领取课程，限时折扣，立即报名。",
            }
        )
        self.assertEqual("skip_ai", result.decision)

    def test_prefilter_marks_rule_classified_email(self) -> None:
        result = prefilter_email(
            {
                "subject": "面试邀请",
                "from_email": "hr@example.com",
                "body_text": "诚邀您参加面试。",
            }
        )
        self.assertEqual("rule_classified", result.decision)
        self.assertEqual("interview_invite", result.category)


    def test_prefilter_uses_custom_marketing_rules(self) -> None:
        result = prefilter_email(
            {
                "subject": "内部推荐课程",
                "from_email": "promo@example.com",
                "body_text": "仅限今天，私信领取。",
            },
            {"marketing_keywords": ["内部推荐", "仅限今天", "私信领取"], "job_keywords": {}},
        )
        self.assertEqual("skip_ai", result.decision)


    def test_absolute_deadline_with_time_builds_utc_value(self) -> None:
        due_at, due_date, due_time, precision = _resolve_deadline(
            {"deadline_type": "absolute", "date": "2026-09-14", "time": "21:32"},
            "2026-09-13T19:45:00+08:00",
        )
        self.assertIsNotNone(due_at)
        self.assertEqual("2026-09-14", due_date)
        self.assertEqual("21:32", due_time)
        self.assertEqual("datetime", precision)

    def test_relative_deadline_is_resolved_from_received_at(self) -> None:
        due_at, due_date, due_time, precision = _resolve_deadline(
            {"deadline_type": "relative", "relative_amount": 48, "relative_unit": "hour"},
            "2026-09-13T00:00:00+08:00",
        )
        self.assertIsNotNone(due_at)
        self.assertEqual("2026-09-15", due_date)
        self.assertEqual("00:00", due_time)
        self.assertEqual("datetime", precision)


if __name__ == "__main__":
    unittest.main()
