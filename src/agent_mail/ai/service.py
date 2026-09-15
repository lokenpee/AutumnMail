"""Batch AI operations for screening and structured extraction."""

from __future__ import annotations

import sqlite3
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

from agent_mail.ai.client import OpenAICompatibleClient
from agent_mail.ai.prompts import (
    RECHECK_SYSTEM_PROMPT,
    SCREENING_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_recheck_prompt,
    build_screening_prompt,
    build_user_prompt,
)
from agent_mail.ai.schema import (
    ALLOWED_CATEGORIES,
    validate_analysis,
    validate_recheck,
    validate_screening,
)
from agent_mail.db import connect
from agent_mail.security import load_secret
from urllib.parse import urlparse

AI_CREDENTIAL_KEY = "ai:deepseek"
SCREENING_CREDENTIAL_KEY = "ai:screening"


class AIServiceError(RuntimeError):
    pass


class AIService:
    def __init__(self, db_path: str | Path, account_id: str | None = None) -> None:
        self.db_path = Path(db_path)
        self.account_id = account_id

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def test_connection(self, kind: str, overrides: dict[str, Any]) -> dict[str, Any]:
        if kind == "screening":
            config = self._load_config("ai.screening.config", {
                "provider": "siliconflow",
                "base_url": "https://api.siliconflow.cn/v1",
                "model": "",
                "timeout": 30,
            })
            credential_key = SCREENING_CREDENTIAL_KEY
        else:
            config = self._load_config("ai.config", {
                "provider": "deepseek",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-flash",
                "timeout": 60,
            })
            credential_key = AI_CREDENTIAL_KEY
        api_key = str(overrides.get("api_key") or "").strip() or (load_secret(credential_key) or "")
        model = str(overrides.get("model") or config.get("model") or "").strip()
        base_url = str(overrides.get("base_url") or config.get("base_url") or "").strip()
        if not api_key:
            raise AIServiceError("请先填写或保存 API Key。")
        if not model:
            raise AIServiceError("请先选择模型。")
        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=int(overrides.get("timeout") or config.get("timeout", 30)),
            max_tokens=64,
            temperature=0.0,
        )
        started = time.perf_counter()
        client.chat_json(
            "你是一个模型连通性测试器。只输出合法 json。",
            '请返回这个 json：{"ok": true}',
            json_mode=False,
        )
        return {"model": model, "latency_ms": int((time.perf_counter() - started) * 1000)}

    def screen_batch(self, limit: int | None = None, progress_callback=None, should_pause=None, mode: str = "pending") -> dict[str, Any]:
        config = self._load_config("ai.screening.config", {})
        api_key = load_secret(SCREENING_CREDENTIAL_KEY) or ""
        model = str(config.get("model") or "").strip()
        if not api_key or not model:
            raise AIServiceError("请先配置并保存筛选 API Key 和模型。")
        emails = self._load_screening_candidates(limit, mode=mode)
        if not emails:
            return {"screened": 0, "relevant": 0, "irrelevant": 0, "failed": 0, "paused": False}
        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=str(config.get("base_url") or "https://api.siliconflow.cn/v1"),
            model=model,
            timeout=int(config.get("timeout", 30)),
            max_tokens=int(config.get("max_tokens", 300)),
            temperature=0.0,
        )
        max_chars = int(config.get("max_chars", 2000))
        concurrency = max(1, min(int(config.get("concurrency", 4)), 16))
        total = len(emails)
        iterator = iter(emails)
        futures = {}
        completed = relevant = irrelevant = failed = 0
        paused = False
        if progress_callback:
            progress_callback(0, total, None)
        executor = ThreadPoolExecutor(max_workers=concurrency)
        try:
            for _ in range(concurrency):
                try:
                    email = next(iterator)
                except StopIteration:
                    break
                futures[executor.submit(self._screen_one, client, email, max_chars)] = email
            with self._connect() as connection:
                while futures:
                    done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                    for future in done:
                        email = futures.pop(future)
                        completed += 1
                        try:
                            result = future.result()
                        except Exception as exc:
                            result = {"ok": False, "error": str(exc)}
                        patch = {"email_id": email["id"]}
                        if not result.get("ok"):
                            failed += 1
                        else:
                            screening = result["screening"]
                            if screening["is_relevant"]:
                                relevant += 1
                                category = screening.get("category_hint") or "unclassified"
                                if category not in ALLOWED_CATEGORIES:
                                    category = "unclassified"
                            else:
                                irrelevant += 1
                                category = "other"
                            self._persist_screening(connection, email["id"], screening, category)
                            connection.commit()
                            patch["patch"] = {"category": category}
                        if progress_callback:
                            progress_callback(completed, total, patch)
                    if should_pause and should_pause():
                        paused = True
                    if not paused:
                        while len(futures) < concurrency:
                            try:
                                email = next(iterator)
                            except StopIteration:
                                break
                            futures[executor.submit(self._screen_one, client, email, max_chars)] = email
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return {"screened": completed - failed, "relevant": relevant, "irrelevant": irrelevant, "failed": failed, "paused": paused}

    def analyze_email(self, email_id: str) -> dict[str, int]:
        email = self._load_email(email_id)
        if not email:
            raise AIServiceError("邮件不存在。")
        return self._analyze_emails([email])

    def analyze_batch(
        self,
        limit: int | None = None,
        progress_callback=None,
        should_pause=None,
        mode: str = "pending",
    ) -> dict[str, Any]:
        emails = self._load_analysis_candidates(limit, mode=mode)
        return self._analyze_emails(
            emails,
            progress_callback=progress_callback,
            should_pause=should_pause,
        )

    def _analyze_emails(self, emails: list[dict[str, Any]], progress_callback=None, should_pause=None) -> dict[str, Any]:
        config = self._load_config("ai.config", {})
        api_key = load_secret(AI_CREDENTIAL_KEY) or ""
        model = str(config.get("model") or "").strip()
        if not api_key or not model:
            raise AIServiceError("请先配置并保存主 AI API Key 和模型。")
        if not emails:
            return {"analyzed": 0, "failed": 0, "paused": False}
        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=str(config.get("base_url") or "https://api.deepseek.com"),
            model=model,
            timeout=int(config.get("timeout", 60)),
            max_tokens=int(config.get("max_tokens", 1500)),
            temperature=0.0,
        )
        max_chars = int(config.get("max_chars", 8000))
        concurrency = max(1, min(int(config.get("concurrency", 2)), 8))
        total = len(emails)
        iterator = iter(emails)
        futures = {}
        completed = analyzed = failed = 0
        errors: list[dict[str, str]] = []
        paused = False
        if progress_callback:
            progress_callback(0, total, None)
        executor = ThreadPoolExecutor(max_workers=concurrency)
        try:
            for _ in range(concurrency):
                try:
                    email = next(iterator)
                except StopIteration:
                    break
                futures[executor.submit(self._analyze_one, client, email, max_chars)] = email
            with self._connect() as connection:
                while futures:
                    done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                    for future in done:
                        email = futures.pop(future)
                        completed += 1
                        try:
                            result = future.result()
                        except Exception as exc:
                            result = {"ok": False, "error": str(exc)}
                        patch = {"email_id": email["id"]}
                        if result.get("ok"):
                            try:
                                analysis = result["analysis"]
                                analysis = self._recheck_missing_fields(client, email, analysis, max_chars)
                                self._persist_analysis(connection, email["id"], analysis)
                                connection.commit()
                                analyzed += 1
                                deadline = analysis.get("deadline") or {}
                                _, resolved_due_date, _, _ = _resolve_deadline(deadline, email.get("received_at"))
                                interview = analysis.get("interview") or {}
                                patch["patch"] = {
                                    "category": analysis.get("email_category") or "unclassified",
                                    "company": (analysis.get("company") or {}).get("name") or "公司未识别",
                                    "deadline": resolved_due_date,
                                    "eventDate": interview.get("date"),
                                }
                            except Exception as exc:
                                failed += 1
                                errors.append({"email_id": email["id"], "error": str(exc)})
                        else:
                            failed += 1
                        if progress_callback:
                            progress_callback(completed, total, patch)
                    if should_pause and should_pause():
                        paused = True
                    if not paused:
                        while len(futures) < concurrency:
                            try:
                                email = next(iterator)
                            except StopIteration:
                                break
                            futures[executor.submit(self._analyze_one, client, email, max_chars)] = email
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return {"analyzed": analyzed, "failed": failed, "errors": errors[:20], "paused": paused}

    def _recheck_missing_fields(
        self,
        client: OpenAICompatibleClient,
        email: dict[str, Any],
        analysis: dict[str, Any],
        max_chars: int,
    ) -> dict[str, Any]:
        category = str(analysis.get("email_category") or "")
        if category in {"other", "unclassified"}:
            return analysis
        deadline_categories = {"assessment_invite", "written_test_invite", "interview_invite", "offer"}
        missing = []
        if not analysis.get("company"):
            missing.append("company")
        if category in deadline_categories and not analysis.get("deadline"):
            missing.append("deadline")
        if not missing:
            return analysis

        merged = dict(analysis)
        for _ in range(2):
            try:
                raw = client.chat_json(
                    RECHECK_SYSTEM_PROMPT,
                    build_recheck_prompt(email, merged, missing, max_chars=max_chars),
                )
                recheck = validate_recheck(raw)
            except Exception:
                break
            if "company" in missing and not merged.get("company") and recheck.get("company"):
                merged["company"] = recheck["company"]
            if "deadline" in missing and not merged.get("deadline") and recheck.get("deadline"):
                merged["deadline"] = recheck["deadline"]
            missing = [
                field
                for field in missing
                if not merged.get(field)
            ]
            if not missing:
                return merged
            if recheck.get("review_reason"):
                merged["review_reason"] = recheck["review_reason"]

        if missing:
            merged["needs_review"] = True
            merged["review_reason"] = merged.get("review_reason") or f"复查后仍缺少：{', '.join(missing)}"
        return merged

    def _screen_one(
        self,
        client: OpenAICompatibleClient,
        email: dict[str, Any],
        max_chars: int,
    ) -> dict[str, Any]:
        try:
            raw = client.chat_json(
                SCREENING_SYSTEM_PROMPT,
                build_screening_prompt(email, max_chars=max_chars),
            )
            return {"ok": True, "screening": validate_screening(raw)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _analyze_one(
        self,
        client: OpenAICompatibleClient,
        email: dict[str, Any],
        max_chars: int,
    ) -> dict[str, Any]:
        try:
            raw = client.chat_json(SYSTEM_PROMPT, build_user_prompt(email, max_chars=max_chars))
            return {"ok": True, "analysis": validate_analysis(raw), "model_output": raw}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _persist_screening(self, connection, email_id: str, screening: dict[str, Any], category: str) -> None:
        current = connection.execute(
            "SELECT is_manual_override FROM classifications WHERE email_id = ?",
            (email_id,),
        ).fetchone()
        if current and current["is_manual_override"]:
            return
        reason = "screening: relevant" if screening["is_relevant"] else "screening: irrelevant"
        connection.execute(
            """
            INSERT INTO classifications (id, email_id, primary_type, confidence, source, reason, is_manual_override)
            VALUES (?, ?, ?, ?, 'model', ?, 0)
            ON CONFLICT(email_id) DO UPDATE SET
                primary_type = excluded.primary_type,
                confidence = excluded.confidence,
                source = 'model',
                reason = excluded.reason,
                is_manual_override = 0,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            (str(uuid.uuid4()), email_id, category, screening["confidence"], reason),
        )
        connection.execute(
            """
            INSERT INTO processing_jobs (email_id, stage, status)
            VALUES (?, 'classified', 'done')
            ON CONFLICT(email_id) DO UPDATE SET
                stage = 'classified', status = 'done', last_error = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            (email_id,),
        )

    def _persist_analysis(self, connection, email_id: str, analysis: dict[str, Any]) -> None:
        email_row = connection.execute("SELECT received_at FROM emails WHERE id = ?", (email_id,)).fetchone()
        received_at = email_row["received_at"] if email_row else None
        current = connection.execute(
            "SELECT is_manual_override FROM classifications WHERE email_id = ?",
            (email_id,),
        ).fetchone()
        if not (current and current["is_manual_override"]):
            connection.execute(
                """
                INSERT INTO classifications (id, email_id, primary_type, confidence, source, reason, is_manual_override)
                VALUES (?, ?, ?, ?, 'model', 'llm: structured extraction', 0)
                ON CONFLICT(email_id) DO UPDATE SET
                    primary_type = excluded.primary_type,
                    confidence = excluded.confidence,
                    source = 'model',
                    reason = excluded.reason,
                    is_manual_override = 0,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (
                    str(uuid.uuid4()),
                    email_id,
                    analysis.get("email_category") or "unclassified",
                    float(analysis.get("email_category_confidence") or 0.9),
                ),
            )

        company = analysis.get("company") or {}
        company_name = str(company.get("name") or "").strip()
        if company_name:
            existing = connection.execute(
                "SELECT is_confirmed FROM email_company_links WHERE email_id = ? AND link_type = 'primary'",
                (email_id,),
            ).fetchone()
            if not (existing and existing["is_confirmed"]):
                connection.execute(
                    "DELETE FROM email_company_links WHERE email_id = ? AND link_type = 'primary'",
                    (email_id,),
                )
                normalized = _normalize_name(company_name)
                row = connection.execute(
                    "SELECT id FROM companies WHERE normalized_name = ?",
                    (normalized,),
                ).fetchone()
                company_id = row["id"] if row else str(uuid.uuid4())
                if not row:
                    connection.execute(
                        "INSERT INTO companies (id, canonical_name, normalized_name) VALUES (?, ?, ?)",
                        (company_id, company_name, normalized),
                    )
                connection.execute(
                    """
                    INSERT INTO email_company_links (
                        id, email_id, company_id, link_type, source, confidence, is_confirmed, evidence
                    ) VALUES (?, ?, ?, 'primary', 'model', ?, 0, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        email_id,
                        company_id,
                        company.get("confidence", 0.0),
                        company.get("evidence"),
                    ),
                )

        connection.execute("DELETE FROM deadlines WHERE email_id = ? AND source = 'auto'", (email_id,))
        deadline = analysis.get("deadline") or {}
        due_at_utc, due_date, due_time, precision = _resolve_deadline(deadline, received_at)
        if due_date or due_at_utc:
            connection.execute(
                """
                INSERT INTO deadlines (
                    id, email_id, label, due_at_utc, due_date_local, due_time_local,
                    precision, source, confidence, status, extraction_evidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'auto', ?, 'pending', ?)
                """,
                (
                    str(uuid.uuid4()),
                    email_id,
                    deadline.get("label"),
                    due_at_utc,
                    due_date,
                    due_time,
                    precision,
                    deadline.get("confidence", 0.0),
                    deadline.get("raw_date") or deadline.get("label"),
                ),
            )

        primary_link = analysis.get("primary_link") or {}
        connection.execute("DELETE FROM action_links WHERE email_id = ?", (email_id,))
        link_url = str(primary_link.get("url") or "").strip()
        if link_url:
            normalized_url = urlparse(link_url)._replace(fragment="").geturl() or link_url
            db_link_type = {
                "interview_meeting": "interview",
                "assessment_test": "assessment",
                "written_test": "written_test",
                "offer_accept": "offer",
            }.get(primary_link.get("link_type"), "other")
            connection.execute(
                """
                INSERT INTO action_links (
                    id, email_id, url, normalized_url, link_type, label, domain
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    email_id,
                    link_url,
                    normalized_url,
                    db_link_type,
                    primary_link.get("label"),
                    urlparse(normalized_url).netloc.lower() or None,
                ),
            )

        connection.execute("DELETE FROM calendar_events WHERE email_id = ? AND source = 'auto'", (email_id,))
        interview = analysis.get("interview") or {}
        event_date = str(interview.get("date") or "").strip()
        if event_date:
            start_time = str(interview.get("time") or "00:00")
            connection.execute(
                """
                INSERT INTO calendar_events (
                    id, email_id, event_type, title, start_at_utc,
                    timezone, location, meeting_url, source, confidence, status
                ) VALUES (?, ?, 'interview', ?, ?, ?, ?, ?, 'auto', ?, 'scheduled')
                """,
                (
                    str(uuid.uuid4()),
                    email_id,
                    f"{(analysis.get('company') or {}).get('name') or '求职'} - {interview.get('round') or '面试'}",
                    f"{event_date}T{start_time}:00+08:00",
                    interview.get("timezone") or "Asia/Shanghai",
                    interview.get("location"),
                    interview.get("meeting_url"),
                    interview.get("confidence", 0.0),
                ),
            )

        needs_review = bool(analysis.get("needs_review"))
        review_reason = str(analysis.get("review_reason") or "").strip() or None
        job_stage = "review_required" if needs_review else "ready"
        connection.execute(
            """
            INSERT INTO processing_jobs (email_id, stage, status, last_error)
            VALUES (?, ?, 'done', ?)
            ON CONFLICT(email_id) DO UPDATE SET
                stage = excluded.stage, status = 'done', last_error = excluded.last_error,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            (email_id, job_stage, review_reason),
        )

    def test_screening_emails(self, limit: int = 3) -> dict[str, Any]:
        config = self._load_config("ai.screening.config", {})
        api_key = load_secret(SCREENING_CREDENTIAL_KEY) or ""
        model = str(config.get("model") or "").strip()
        if not api_key or not model:
            raise AIServiceError("请先配置并保存筛选 API Key 和模型。")
        emails = self._load_recent_emails(limit)
        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=str(config.get("base_url") or "https://api.siliconflow.cn/v1"),
            model=model,
            timeout=int(config.get("timeout", 30)),
            max_tokens=int(config.get("max_tokens", 300)),
            temperature=0.0,
        )
        results = []
        for email in emails:
            item = self._screen_one(client, email, int(config.get("max_chars", 2000)))
            item["email"] = {"id": email["id"], "subject": email["subject"], "from_email": email["from_email"]}
            results.append(item)
        return {"model": model, "results": results, "persisted": False}

    def test_analysis_emails(self, limit: int = 3) -> dict[str, Any]:
        config = self._load_config("ai.config", {})
        api_key = load_secret(AI_CREDENTIAL_KEY) or ""
        model = str(config.get("model") or "").strip()
        if not api_key or not model:
            raise AIServiceError("请先配置并保存主 AI API Key 和模型。")
        emails = self._load_llm_test_emails(limit)
        if not emails:
            raise AIServiceError("没有可识别的邮件：未分类和广告/垃圾邮件已被排除。")
        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=str(config.get("base_url") or "https://api.deepseek.com"),
            model=model,
            timeout=int(config.get("timeout", 60)),
            max_tokens=int(config.get("max_tokens", 1500)),
            temperature=0.0,
        )
        results = []
        for email in emails:
            max_chars = int(config.get("max_chars", 8000))
            item = self._analyze_one(client, email, max_chars)
            if item.get("ok"):
                item["analysis"] = self._recheck_missing_fields(client, email, item["analysis"], max_chars)
                item.pop("model_output", None)
            item["email"] = {"id": email["id"], "subject": email["subject"], "from_email": email["from_email"], "category": email.get("current_category")}
            results.append(item)
        return {"model": model, "results": results, "persisted": False}

    def _load_config(self, key: str, defaults: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = ?",
                (key,),
            ).fetchone()
        result = dict(defaults)
        if row:
            try:
                import json
                stored = json.loads(row["value_json"])
                if isinstance(stored, dict):
                    result.update(stored)
            except Exception:
                pass
        return result

    def _load_screening_candidates(self, limit: int | None, mode: str = "pending") -> list[dict[str, Any]]:
        if mode == "all":
            where = """
                NOT EXISTS (
                    SELECT 1 FROM classifications mc
                    WHERE mc.email_id = e.id AND mc.is_manual_override = 1
                )
            """
        else:
            where = """
                NOT EXISTS (
                    SELECT 1 FROM classifications mc
                    WHERE mc.email_id = e.id AND mc.is_manual_override = 1
                )
                AND NOT EXISTS (
                    SELECT 1 FROM processing_jobs pj
                    WHERE pj.email_id = e.id
                      AND pj.status = 'done'
                      AND pj.stage IN ('classified', 'deadline_extracted', 'review_required', 'ready')
                )
            """
        account_filter = "e.account_id = ? AND" if self.account_id else ""
        sql = f"""
            SELECT e.id, e.subject, e.from_name, e.from_email, e.received_at,
                   COALESCE(NULLIF(e.body_text, ''), e.snippet, '') AS body_text
            FROM emails e
            WHERE {account_filter} {where}
            ORDER BY e.received_at DESC
        """
        params: tuple[Any, ...] = (self.account_id,) if self.account_id else ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def _load_analysis_candidates(self, limit: int | None, mode: str = "pending") -> list[dict[str, Any]]:
        allowed = tuple(sorted(ALLOWED_CATEGORIES - {"other", "unclassified"}))
        placeholders = ",".join("?" for _ in allowed)
        relevant_condition = f"""
            (
                c.primary_type IN ({placeholders})
                OR (c.primary_type = 'unclassified' AND c.reason = 'screening: relevant')
            )
        """
        if mode == "company_unresolved":
            condition = f"""
                {relevant_condition}
                AND NOT EXISTS (
                    SELECT 1 FROM email_company_links ecl
                    WHERE ecl.email_id = e.id
                      AND ecl.link_type = 'primary'
                )
            """
        elif mode == "all_relevant":
            condition = relevant_condition
        else:
            condition = f"""
                {relevant_condition}
                AND NOT EXISTS (
                    SELECT 1 FROM processing_jobs pj
                    WHERE pj.email_id = e.id
                      AND pj.status = 'done'
                      AND pj.stage IN ('ready', 'review_required')
                )
            """
        account_filter = "e.account_id = ? AND" if self.account_id else ""
        sql = f"""
            SELECT e.id, e.subject, e.from_name, e.from_email, e.received_at,
                   COALESCE(NULLIF(e.body_text, ''), e.snippet, '') AS body_text,
                   c.primary_type AS current_category
            FROM emails e
            JOIN classifications c ON c.email_id = e.id
            WHERE {account_filter} {condition}
            ORDER BY e.received_at DESC
        """
        params: tuple[Any, ...] = ((self.account_id,) if self.account_id else ()) + allowed
        if limit is not None:
            sql += " LIMIT ?"
            params = (*params, limit)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def _load_email(self, email_id: str) -> dict[str, Any] | None:
        account_filter = "AND account_id = ?" if self.account_id else ""
        params: tuple[Any, ...] = (email_id, self.account_id) if self.account_id else (email_id,)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT id, subject, from_name, from_email, received_at,
                       COALESCE(NULLIF(body_text, ''), snippet, '') AS body_text
                FROM emails
                WHERE id = ? {account_filter}
                """,
                params,
            ).fetchone()
        return dict(row) if row else None

    def _load_recent_emails(self, limit: int = 3) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 20))
        account_filter = "WHERE account_id = ?" if self.account_id else ""
        params: tuple[Any, ...] = (self.account_id, safe_limit) if self.account_id else (safe_limit,)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, subject, from_name, from_email, received_at,
                       COALESCE(NULLIF(body_text, ''), snippet, '') AS body_text
                FROM emails
                {account_filter}
                ORDER BY received_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def _load_llm_test_emails(self, limit: int = 3) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 20))
        return self._load_analysis_candidates(safe_limit, mode="all_relevant")


def _normalize_name(value: str) -> str:
    import re
    return re.sub(r"[\s\W_]+", "", value.strip().lower())


def _shanghai_timezone():
    try:
        return ZoneInfo("Asia/Shanghai")
    except Exception:
        return timezone(timedelta(hours=8))


def _resolve_deadline(deadline: dict[str, Any], received_at: str | None) -> tuple[str | None, str | None, str | None, str]:
    local_timezone = _shanghai_timezone()
    if deadline.get("deadline_type") == "relative" and received_at:
        amount = deadline.get("relative_amount")
        unit = str(deadline.get("relative_unit") or "").lower()
        try:
            amount_value = float(amount)
        except (TypeError, ValueError):
            return None, None, None, "datetime"
        unit_map = {
            "minute": "minutes", "minutes": "minutes",
            "hour": "hours", "hours": "hours",
            "day": "days", "days": "days",
        }
        keyword = unit_map.get(unit)
        if not keyword:
            return None, None, None, "datetime"
        try:
            base = datetime.fromisoformat(received_at)
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            due = base + timedelta(**{keyword: amount_value})
            local = due.astimezone(local_timezone)
            return due.astimezone(timezone.utc).isoformat(), local.date().isoformat(), local.strftime("%H:%M"), "datetime"
        except Exception:
            return None, None, None, "datetime"
    due_date = str(deadline.get("normalized_date") or deadline.get("date") or "").strip() or None
    due_time = str(deadline.get("time") or "").strip() or None
    if due_date and due_time:
        try:
            local_due = datetime.strptime(f"{due_date} {due_time}", "%Y-%m-%d %H:%M").replace(
                tzinfo=local_timezone
            )
            return local_due.astimezone(timezone.utc).isoformat(), due_date, due_time, "datetime"
        except Exception:
            return None, due_date, None, "date"
    if due_date:
        return None, due_date, None, "date"
    return None, None, None, "date"
