"""HTTP server that exposes the local UI and mailbox onboarding API."""

from __future__ import annotations

import imaplib
import json
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import ssl
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent_mail.ai.schema import ALLOWED_CATEGORIES
from agent_mail.ai.prefilter import DEFAULT_PREFILTER_RULES
from agent_mail.ai import (
    LLMClientError,
    OpenAICompatibleClient,
    SCREENING_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_screening_prompt,
    build_user_prompt,
    prefilter_email,
    validate_analysis,
    validate_screening,
)
from agent_mail.db import backup_database, connect, default_db_path, initialize_database
from agent_mail.ai.service import AIService, AIServiceError
from agent_mail.security import CredentialStoreError, delete_secret, load_secret, save_secret
from agent_mail.sync import MailSyncService, test_connection

def _resource_path(relative: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / relative
    return Path(__file__).resolve().parents[3] / relative


WEB_DIR = _resource_path("web")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AI_CREDENTIAL_KEY = "ai:deepseek"
SCREENING_CREDENTIAL_KEY = "ai:screening"
AI_JOBS: dict[str, dict[str, Any]] = {}
AI_JOBS_LOCK = threading.Lock()
LOG_EVENTS: list[dict[str, Any]] = []
LOG_LOCK = threading.Lock()


def _append_log(level: str, message: str, job_id: str | None = None) -> None:
    with LOG_LOCK:
        LOG_EVENTS.append({
            "index": len(LOG_EVENTS) + 1,
            "level": level,
            "message": message,
            "job_id": job_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        if len(LOG_EVENTS) > 500:
            del LOG_EVENTS[:100]

DEFAULT_SCREENING_CONFIG = {
    "enabled": True,
    "provider": "siliconflow",
    "base_url": "https://api.siliconflow.cn/v1",
    "model": "",
    "max_chars": 2000,
    "max_tokens": 300,
    "timeout": 30,
    "temperature": 0.0,
    "concurrency": 4,
}
DEFAULT_AI_CONFIG = {
    "enabled": True,
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "max_chars": 8000,
    "max_tokens": 1500,
    "timeout": 60,
    "temperature": 0.0,
    "concurrency": 2,
}

def _safe_connect_error(exc: Exception, auth_code: str = "") -> str:
    text = str(exc)
    if auth_code:
        text = text.replace(auth_code, "[redacted]")
    text = text.strip()[:300]
    lowered = text.lower()

    if isinstance(exc, imaplib.IMAP4.error):
        if "unsafe login" in lowered:
            return "网易拒绝了 IMAP 登录，请确认 IMAP 服务已开启并重新生成授权码。"
        if "login" in lowered or "password" in lowered or "auth" in lowered:
            return "账号或客户端授权码不正确。请确认邮箱地址正确，并使用的是新生成的客户端授权码，不是登录密码。"
        return f"IMAP 服务器返回：{text}"
    if isinstance(exc, ssl.SSLError):
        return f"TLS/SSL 握手失败：{text}"
    if isinstance(exc, TimeoutError):
        return "连接 163 IMAP 超时，请检查网络、代理或防火墙。"
    if isinstance(exc, OSError):
        return f"网络连接失败：{text}"
    return f"{type(exc).__name__}: {text}"



def _safe_ai_error(exc: Exception, api_key: str = "") -> str:
    text = str(exc)
    if api_key:
        text = text.replace(api_key, "[redacted]")
    return text.strip()[:500] or type(exc).__name__



def _normalize_name(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value.strip().lower())


def _parse_sync_bounds(payload: dict[str, Any]) -> tuple[date | None, date | None]:
    try:
        start_date = date.fromisoformat(str(payload.get("start_date") or "").strip()) if payload.get("start_date") else None
        end_date = date.fromisoformat(str(payload.get("end_date") or "").strip()) if payload.get("end_date") else None
    except ValueError as exc:
        raise RuntimeError("同步日期必须使用 YYYY-MM-DD 格式。") from exc
    if start_date and end_date and start_date > end_date:
        raise RuntimeError("开始日期不能晚于结束日期。")
    if not start_date and not end_date:
        days = max(1, int(payload.get("days", 30)))
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
    return start_date, end_date


def _parse_sync_limit(payload: dict[str, Any]) -> int | None:
    raw_limit = payload.get("limit")
    if raw_limit in (None, ""):
        return None
    return max(1, int(raw_limit))


class AgentMailServer(ThreadingHTTPServer):
    """Threaded local server with an explicit database path."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], db_path: Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        handler = partial(AgentMailHandler, db_path=self.db_path)
        super().__init__(address, handler)


class AgentMailHandler(SimpleHTTPRequestHandler):
    """Serve static assets and a small authenticated-by-locality JSON API."""

    def __init__(self, *args: Any, db_path: Path, **kwargs: Any) -> None:
        self.db_path = db_path
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            try:
                self._handle_get(path)
            except Exception as exc:
                self._json_error(str(exc))
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            self._handle_post(path)
        except Exception as exc:
            self._json_error(str(exc))

    def _handle_get(self, path: str) -> None:
        if path == "/api/health":
            self._send_json({"status": "ok"})
            return
        if path == "/api/account":
            self._send_json(self._account_state())
            return
        if path == "/api/sync/status":
            self._send_json(self._sync_state())
            return
        if path == "/api/emails":
            self._send_json({"emails": self._list_emails(limit=200)})
            return
        if path == "/api/ai/settings":
            self._send_json(self._ai_settings_state())
            return
        if path == "/api/ai/screening/settings":
            self._send_json(self._screening_settings_state())
            return
        if path == "/api/prefilter/settings":
            self._send_json(self._prefilter_settings_state())
            return
        if path == "/api/logs":
            query = urlparse(self.path).query
            after = 0
            if query.startswith("after="):
                try:
                    after = int(query.split("=", 1)[1])
                except ValueError:
                    after = 0
            with LOG_LOCK:
                events = [event for event in LOG_EVENTS if event["index"] > after]
                cursor = LOG_EVENTS[-1]["index"] if LOG_EVENTS else after
            self._send_json({"ok": True, "events": events, "cursor": cursor})
            return
        if path.startswith("/api/ai/jobs/"):
            self._send_json(self._get_ai_job(path.rsplit("/", 1)[-1]))
            return
        self._json_error("API endpoint not found.", HTTPStatus.NOT_FOUND)

    def _handle_post(self, path: str) -> None:
        payload = self._read_json()
        if path == "/api/account/connect":
            self._connect_account(payload)
            return
        if path == "/api/sync/run":
            self._run_sync(payload)
            return
        if path == "/api/pipeline/run":
            self._run_sync_pipeline(payload)
            return
        if path == "/api/ai/settings":
            self._save_ai_settings(payload)
            return
        if path == "/api/ai/screening/settings":
            self._save_screening_settings(payload)
            return
        if path == "/api/prefilter/settings":
            self._save_prefilter_settings(payload)
            return
        if path == "/api/ai/models":
            self._list_ai_models(payload)
            return
        if path == "/api/ai/screening/models":
            self._list_screening_models(payload)
            return
        if path == "/api/emails/correct":
            self._correct_email(payload)
            return
        if path == "/api/emails/review":
            self._mark_email_reviewed(payload)
            return
        if path == "/api/emails/complete":
            self._set_email_completed(payload)
            return
        if path == "/api/ai/test":
            self._test_ai(payload)
            return
        if path == "/api/ai/test-connection":
            self._test_model_connection(payload, "ai")
            return
        if path == "/api/ai/screening/test-connection":
            self._test_model_connection(payload, "screening")
            return
        if path == "/api/ai/screening/test-emails":
            self._test_screening_emails(payload)
            return
        if path == "/api/ai/test-emails":
            self._test_analysis_emails(payload)
            return
        if path == "/api/ai/screen/run":
            self._run_screening_batch(payload)
            return
        if path == "/api/ai/analyze/run":
            self._run_analysis_batch(payload)
            return
        if path == "/api/ai/analyze/email":
            self._run_single_analysis(payload)
            return
        if path.startswith("/api/ai/jobs/") and path.endswith("/pause"):
            job_id = path.split("/")[-2]
            self._pause_ai_job(job_id)
            return
        if path == "/api/account/disconnect":
            self._disconnect_account()
            return
        if path == "/api/database/backup":
            self._backup_database()
            return
        self._json_error("API endpoint not found.", HTTPStatus.NOT_FOUND)

    def _backup_database(self) -> None:
        try:
            backup_path = backup_database(self.db_path)
        except Exception as exc:
            self._json_error(f"数据库备份失败：{exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json({"ok": True, "backup_path": str(backup_path)})

    def _connect_account(self, payload: dict[str, Any]) -> None:
        email = str(payload.get("email", "")).strip().lower()
        auth_code = str(payload.get("auth_code", "")).strip()
        display_name = str(payload.get("display_name", "")).strip() or None

        if not EMAIL_RE.match(email):
            self._json_error("请输入有效的邮箱地址。", HTTPStatus.BAD_REQUEST)
            return
        if not auth_code:
            self._json_error("请输入 163 客户端授权码。", HTTPStatus.BAD_REQUEST)
            return

        try:
            folders = test_connection(email, auth_code)
        except Exception as exc:
            safe_error = _safe_connect_error(exc, auth_code)
            _append_log("error", f"163 连接失败：{safe_error}")
            print(f"[163 connect] {safe_error}", flush=True)
            self._json_error(f"163 连接失败：{safe_error}", HTTPStatus.BAD_REQUEST)
            return

        save_secret(email, email, auth_code)
        with self._open_db() as connection:
            service = MailSyncService(connection)
            account_id = service.ensure_account(email, display_name=display_name)
            service.ensure_folder(account_id, "INBOX")

        _append_log("success", f"163 邮箱连接成功：{email}")
        self._send_json({"connected": True, "email": email, "folders": folders})

    def _perform_sync(self, start_date: date | None, end_date: date | None, limit: int | None) -> dict[str, Any]:
        account = self._first_account()
        if not account:
            raise RuntimeError("请先连接 163 邮箱。")
        try:
            auth_code = load_secret(account["email"])
        except CredentialStoreError as exc:
            raise RuntimeError(str(exc)) from exc
        if not auth_code:
            raise RuntimeError("本机没有找到授权码，请重新连接邮箱。")
        range_text = f"{start_date or '最早'} 至 {end_date or '今天'}"
        _append_log("info", f"开始同步 163 邮箱邮件：{range_text}")
        with self._open_db() as connection:
            service = MailSyncService(connection)
            result = service.sync_recent(
                email=account["email"],
                auth_code=auth_code,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
            )
        _append_log("success", f"邮件同步完成：获取 {result.fetched} 封，新增 {result.inserted} 封")
        return asdict(result)

    def _run_sync(self, payload: dict[str, Any]) -> None:
        try:
            start_date, end_date = _parse_sync_bounds(payload)
            limit = _parse_sync_limit(payload)
            result = self._perform_sync(start_date, end_date, limit)
        except Exception as exc:
            self._json_error(str(exc), HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, "result": result})

    def _run_sync_pipeline(self, payload: dict[str, Any]) -> None:
        job_id = str(uuid.uuid4())
        try:
            start_date, end_date = _parse_sync_bounds(payload)
            limit = _parse_sync_limit(payload)
        except Exception as exc:
            self._json_error(str(exc), HTTPStatus.BAD_REQUEST)
            return
        chunk_size = max(1, min(int(payload.get("chunk_size", 20)), 100))
        self._create_ai_job(job_id, "pipeline")
        _append_log("info", "开始同步并自动处理邮件流水线", job_id)

        def worker() -> None:
            try:
                self._update_ai_job(job_id, stage="syncing", completed=0, total=0)
                sync_result = self._perform_sync(start_date, end_date, limit)
                screening_totals = {"screened": 0, "relevant": 0, "irrelevant": 0, "failed": 0}
                analysis_totals = {"analyzed": 0, "failed": 0}

                while True:
                    screening = AIService(self.db_path).screen_batch(
                        limit=chunk_size,
                        mode="pending",
                        progress_callback=lambda completed, total, update=None: self._update_ai_job(
                            job_id, stage="screening", completed=completed, total=total, update=update
                        ),
                    )
                    for key in screening_totals:
                        screening_totals[key] += int(screening.get(key, 0))

                    analysis = AIService(self.db_path).analyze_batch(
                        limit=None,
                        mode="pending",
                        progress_callback=lambda completed, total, update=None: self._update_ai_job(
                            job_id, stage="analysis", completed=completed, total=total, update=update
                        ),
                    )
                    analysis_totals["analyzed"] += int(analysis.get("analyzed", 0))
                    analysis_totals["failed"] += int(analysis.get("failed", 0))

                    if int(screening.get("screened", 0)) == 0 and int(analysis.get("analyzed", 0)) == 0:
                        break

                result = {
                    "sync": sync_result,
                    "screening": screening_totals,
                    "analysis": analysis_totals,
                    "paused": False,
                }
                self._finish_ai_job(job_id, result)
                _append_log("success", f"同步处理流水线完成：{result}", job_id)
            except Exception as exc:
                safe_error = _safe_ai_error(exc)
                self._fail_ai_job(job_id, safe_error)
                _append_log("error", f"同步处理流水线失败：{safe_error}", job_id)

        threading.Thread(target=worker, daemon=True).start()
        self._send_json({"ok": True, "job_id": job_id, "status": "running"})

    def _disconnect_account(self) -> None:
        account = self._first_account()
        if not account:
            self._send_json({"ok": True})
            return
        delete_secret(account["email"])
        with self._open_db() as connection:
            connection.execute(
                """
                UPDATE accounts
                SET status = 'disabled',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (account["id"],),
            )
            connection.commit()
        self._send_json({"ok": True})

    def _prefilter_settings_state(self) -> dict[str, Any]:
        return {"ok": True, "rules": self._load_prefilter_config()}

    def _save_prefilter_settings(self, payload: dict[str, Any]) -> None:
        rules = payload.get("rules")
        if not isinstance(rules, dict):
            self._json_error("预筛规则格式错误。", HTTPStatus.BAD_REQUEST)
            return
        merged = {
            "marketing_keywords": list(DEFAULT_PREFILTER_RULES["marketing_keywords"]),
            "job_keywords": {
                category: list(values)
                for category, values in DEFAULT_PREFILTER_RULES["job_keywords"].items()
            },
        }
        marketing = rules.get("marketing_keywords")
        if isinstance(marketing, list):
            merged["marketing_keywords"] = [str(item).strip() for item in marketing if str(item).strip()]
        job_keywords = rules.get("job_keywords")
        if isinstance(job_keywords, dict):
            for category, values in job_keywords.items():
                if category in merged["job_keywords"] and isinstance(values, list):
                    merged["job_keywords"][category] = [str(item).strip() for item in values if str(item).strip()]
        self._store_prefilter_config(merged)
        self._send_json({"ok": True, "rules": merged})

    def _load_prefilter_config(self) -> dict[str, Any]:
        with self._open_db() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = 'prefilter.rules'"
            ).fetchone()
        if not row:
            return {
                "marketing_keywords": list(DEFAULT_PREFILTER_RULES["marketing_keywords"]),
                "job_keywords": {
                    category: list(values)
                    for category, values in DEFAULT_PREFILTER_RULES["job_keywords"].items()
                },
            }
        try:
            stored = json.loads(row["value_json"])
        except json.JSONDecodeError:
            stored = {}
        merged = {
            "marketing_keywords": list(DEFAULT_PREFILTER_RULES["marketing_keywords"]),
            "job_keywords": {
                category: list(values)
                for category, values in DEFAULT_PREFILTER_RULES["job_keywords"].items()
            },
        }
        if isinstance(stored, dict):
            if isinstance(stored.get("marketing_keywords"), list):
                merged["marketing_keywords"] = [str(item) for item in stored["marketing_keywords"] if str(item).strip()]
            if isinstance(stored.get("job_keywords"), dict):
                for category, values in stored["job_keywords"].items():
                    if category in merged["job_keywords"] and isinstance(values, list):
                        merged["job_keywords"][category] = [str(item) for item in values if str(item).strip()]
        return merged

    def _store_prefilter_config(self, rules: dict[str, Any]) -> None:
        with self._open_db() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value_json, updated_at)
                VALUES ('prefilter.rules', ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (json.dumps(rules, ensure_ascii=False),),
            )
            connection.commit()

    def _screening_settings_state(self) -> dict[str, Any]:
        config = self._load_screening_config()
        try:
            api_key_configured = bool(load_secret(SCREENING_CREDENTIAL_KEY))
        except CredentialStoreError:
            api_key_configured = False
        return {
            "provider": config.get("provider", "deepseek"),
            "config": config,
            "api_key_configured": api_key_configured,
        }

    def _save_screening_settings(self, payload: dict[str, Any]) -> None:
        config = self._load_screening_config()
        previous_provider = str(config.get("provider") or "")
        for key in ("enabled", "provider", "base_url", "model", "max_chars", "max_tokens", "timeout", "concurrency"):
            if key in payload:
                config[key] = payload[key]
        config["provider"] = str(config.get("provider") or "siliconflow")
        config["base_url"] = str(config.get("base_url") or "").strip().rstrip("/")
        if not config["base_url"]:
            self._json_error("请填写筛选 API Base URL。", HTTPStatus.BAD_REQUEST)
            return
        config["model"] = str(config.get("model") or "")
        config["max_chars"] = max(100, min(int(config.get("max_chars", 2000)), 20000))
        config["max_tokens"] = max(64, min(int(config.get("max_tokens", 300)), 2048))
        config["timeout"] = max(5, min(int(config.get("timeout", 30)), 300))
        config["concurrency"] = max(1, min(int(config.get("concurrency", 4)), 16))

        api_key = str(payload.get("api_key", "")).strip()
        if api_key:
            save_secret(SCREENING_CREDENTIAL_KEY, config["provider"], api_key)
        elif previous_provider and previous_provider != config["provider"]:
            delete_secret(SCREENING_CREDENTIAL_KEY)
        if payload.get("clear_api_key"):
            delete_secret(SCREENING_CREDENTIAL_KEY)

        self._store_screening_config(config)
        self._send_json(self._screening_settings_state())

    def _list_screening_models(self, payload: dict[str, Any]) -> None:
        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            self._json_error("请填写筛选 API Base URL。", HTTPStatus.BAD_REQUEST)
            return
        api_key = str(payload.get("api_key", "")).strip()
        if not api_key:
            try:
                api_key = load_secret(SCREENING_CREDENTIAL_KEY) or ""
            except CredentialStoreError:
                api_key = ""
        if not api_key:
            self._json_error("请先输入筛选 API Key，或保存已配置的筛选 Key。", HTTPStatus.BAD_REQUEST)
            return
        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=base_url,
            model="deepseek-flash",
            timeout=30,
        )
        try:
            models = client.list_models()
        except LLMClientError as exc:
            self._json_error(_safe_ai_error(exc, api_key), HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, "models": models, "base_url": base_url})

    def _load_screening_config(self) -> dict[str, Any]:
        config = dict(DEFAULT_SCREENING_CONFIG)
        with self._open_db() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = 'ai.screening.config'"
            ).fetchone()
        if row:
            try:
                stored = json.loads(row["value_json"])
            except json.JSONDecodeError:
                stored = {}
            if isinstance(stored, dict):
                config.update(stored)
        return config

    def _store_screening_config(self, config: dict[str, Any]) -> None:
        with self._open_db() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value_json, updated_at)
                VALUES ('ai.screening.config', ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (json.dumps(config, ensure_ascii=False),),
            )
            connection.commit()

    def _screen_email(self, client: OpenAICompatibleClient, email: dict[str, Any], max_chars: int) -> dict[str, Any]:
        raw = client.chat_json(
            SCREENING_SYSTEM_PROMPT,
            build_screening_prompt(email, max_chars=max_chars),
        )
        return validate_screening(raw)

    def _correct_email(self, payload: dict[str, Any]) -> None:
        email_id = str(payload.get("email_id", "")).strip()
        field = str(payload.get("field", "")).strip()
        value = payload.get("value")
        if not email_id or field not in {"category", "deadline", "company", "position", "eventDate"}:
            self._json_error("无效的人工纠错请求。", HTTPStatus.BAD_REQUEST)
            return

        with self._open_db() as connection:
            email = connection.execute(
                "SELECT id FROM emails WHERE id = ?",
                (email_id,),
            ).fetchone()
            if not email:
                self._json_error("邮件不存在。", HTTPStatus.NOT_FOUND)
                return

            if field == "category":
                category = str(value or "unclassified")
                if category not in ALLOWED_CATEGORIES:
                    self._json_error("无效的邮件类别。", HTTPStatus.BAD_REQUEST)
                    return
                connection.execute(
                    """
                    INSERT INTO classifications (
                        id, email_id, primary_type, confidence, source, is_manual_override
                    ) VALUES (?, ?, ?, 1.0, 'user', 1)
                    ON CONFLICT(email_id) DO UPDATE SET
                        primary_type = excluded.primary_type,
                        confidence = 1.0,
                        source = 'user',
                        is_manual_override = 1,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (str(uuid.uuid4()), email_id, category),
                )
            elif field == "company":
                company_name = str(value or "").strip()
                connection.execute(
                    "DELETE FROM email_company_links WHERE email_id = ? AND link_type = 'primary'",
                    (email_id,),
                )
                if company_name:
                    normalized = _normalize_name(company_name)
                    company = connection.execute(
                        "SELECT id FROM companies WHERE normalized_name = ?",
                        (normalized,),
                    ).fetchone()
                    if company:
                        company_id = company["id"]
                    else:
                        company_id = str(uuid.uuid4())
                        connection.execute(
                            """
                            INSERT INTO companies (id, canonical_name, normalized_name)
                            VALUES (?, ?, ?)
                            """,
                            (company_id, company_name, normalized),
                        )
                    connection.execute(
                        """
                        INSERT INTO email_company_links (
                            id, email_id, company_id, link_type, source,
                            confidence, is_confirmed, evidence
                        ) VALUES (?, ?, ?, 'primary', 'user', 1.0, 1, '人工修正')
                        """,
                        (str(uuid.uuid4()), email_id, company_id),
                    )
            elif field == "position":
                position_name = str(value or "").strip()
                primary = connection.execute(
                    """
                    SELECT company_id, position_id FROM email_company_links
                    WHERE email_id = ? AND link_type = 'primary'
                    LIMIT 1
                    """,
                    (email_id,),
                ).fetchone()
                if not primary:
                    self._json_error("请先设置公司，再修改岗位。", HTTPStatus.BAD_REQUEST)
                    return
                position_id = None
                if position_name:
                    normalized = _normalize_name(position_name)
                    position = connection.execute(
                        """
                        SELECT id FROM positions
                        WHERE company_id = ? AND normalized_title = ?
                        LIMIT 1
                        """,
                        (primary["company_id"], normalized),
                    ).fetchone()
                    if position:
                        position_id = position["id"]
                    else:
                        position_id = str(uuid.uuid4())
                        connection.execute(
                            """
                            INSERT INTO positions (
                                id, company_id, title, normalized_title, status
                            ) VALUES (?, ?, ?, ?, 'unknown')
                            """,
                            (position_id, primary["company_id"], position_name, normalized),
                        )
                connection.execute(
                    "UPDATE email_company_links SET position_id = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE email_id = ? AND link_type = 'primary'",
                    (position_id, email_id),
                )
            elif field == "eventDate":
                event_value = str(value or "").strip()
                if event_value:
                    try:
                        datetime.strptime(event_value, "%Y-%m-%d")
                    except ValueError:
                        self._json_error("面试日期必须使用 YYYY-MM-DD 格式。", HTTPStatus.BAD_REQUEST)
                        return
                connection.execute(
                    "DELETE FROM calendar_events WHERE email_id = ? AND event_type = 'interview'",
                    (email_id,),
                )
                if event_value:
                    connection.execute(
                        """
                        INSERT INTO calendar_events (
                            id, email_id, event_type, title, start_at_utc,
                            timezone, source, confidence, status
                        ) VALUES (?, ?, 'interview', '人工修正面试时间', ?, 'Asia/Shanghai', 'manual', 1.0, 'scheduled')
                        """,
                        (str(uuid.uuid4()), email_id, f"{event_value}T00:00:00+08:00"),
                    )
            else:
                deadline_value = str(value or "").strip()
                if deadline_value:
                    try:
                        datetime.strptime(deadline_value, "%Y-%m-%d")
                    except ValueError:
                        self._json_error("截止日期必须使用 YYYY-MM-DD 格式。", HTTPStatus.BAD_REQUEST)
                        return
                    existing = connection.execute(
                        """
                        SELECT id FROM deadlines
                        WHERE email_id = ? AND source = 'manual'
                        ORDER BY created_at ASC
                        LIMIT 1
                        """,
                        (email_id,),
                    ).fetchone()
                    if existing:
                        connection.execute(
                            """
                            UPDATE deadlines
                            SET due_date_local = ?, due_at_utc = NULL, due_time_local = NULL,
                                precision = 'date', status = 'pending', is_manual_override = 1,
                                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                            WHERE id = ?
                            """,
                            (deadline_value, existing["id"]),
                        )
                    else:
                        connection.execute(
                            """
                            INSERT INTO deadlines (
                                id, email_id, label, due_date_local, precision, source,
                                confidence, status, is_manual_override
                            ) VALUES (?, ?, '人工修正截止日期', ?, 'date', 'manual', 1.0, 'pending', 1)
                            """,
                            (str(uuid.uuid4()), email_id, deadline_value),
                        )
                else:
                    connection.execute(
                        "DELETE FROM deadlines WHERE email_id = ? AND source = 'manual'",
                        (email_id,),
                    )
            connection.commit()
        self._send_json({"ok": True, "email_id": email_id, "field": field})

    def _ai_settings_state(self) -> dict[str, Any]:
        config = self._load_ai_config()
        try:
            api_key_configured = bool(load_secret(AI_CREDENTIAL_KEY))
        except CredentialStoreError:
            api_key_configured = False
        return {
            "provider": config.get("provider", "deepseek"),
            "config": config,
            "api_key_configured": api_key_configured,
        }

    def _save_ai_settings(self, payload: dict[str, Any]) -> None:
        config = self._load_ai_config()
        previous_provider = str(config.get("provider") or "")
        for key in ("enabled", "provider", "base_url", "model", "max_chars", "max_tokens", "timeout", "temperature", "concurrency"):
            if key in payload:
                config[key] = payload[key]
        config["provider"] = str(config.get("provider") or "deepseek")
        config["base_url"] = str(config.get("base_url") or "").strip().rstrip("/")
        if not config["base_url"]:
            self._json_error("请填写主模型 API Base URL。", HTTPStatus.BAD_REQUEST)
            return
        config["model"] = str(config.get("model") or "")
        config["max_chars"] = max(100, min(int(config.get("max_chars", 8000)), 50000))
        config["max_tokens"] = max(128, min(int(config.get("max_tokens", 1500)), 8192))
        config["timeout"] = max(5, min(int(config.get("timeout", 60)), 300))
        config["temperature"] = 0.0
        config["concurrency"] = max(1, min(int(config.get("concurrency", 2)), 8))

        api_key = str(payload.get("api_key", "")).strip()
        if api_key:
            save_secret(AI_CREDENTIAL_KEY, config["provider"], api_key)
        elif previous_provider and previous_provider != config["provider"]:
            delete_secret(AI_CREDENTIAL_KEY)
        if payload.get("clear_api_key"):
            delete_secret(AI_CREDENTIAL_KEY)

        self._store_ai_config(config)
        self._send_json(self._ai_settings_state())

    def _set_email_completed(self, payload: dict[str, Any]) -> None:
        raw_ids = payload.get("email_ids")
        if isinstance(raw_ids, list):
            email_ids = [str(item).strip() for item in raw_ids if str(item).strip()]
        else:
            email_id = str(payload.get("email_id") or "").strip()
            email_ids = [email_id] if email_id else []
        if not email_ids:
            self._json_error("缺少邮件 ID。", HTTPStatus.BAD_REQUEST)
            return
        completed = 1 if payload.get("is_completed") else 0
        with self._open_db() as connection:
            for email_id in email_ids:
                connection.execute(
                    """
                    INSERT INTO email_user_states (email_id, is_completed, completed_at)
                    VALUES (?, ?, CASE WHEN ? = 1 THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') ELSE NULL END)
                    ON CONFLICT(email_id) DO UPDATE SET
                        is_completed = excluded.is_completed,
                        completed_at = excluded.completed_at,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (email_id, completed, completed),
                )
            connection.commit()
        self._send_json({"ok": True, "email_ids": email_ids, "is_completed": bool(completed)})

    def _mark_email_reviewed(self, payload: dict[str, Any]) -> None:
        email_id = str(payload.get("email_id") or "").strip()
        if not email_id:
            self._json_error("缺少邮件 ID。", HTTPStatus.BAD_REQUEST)
            return
        with self._open_db() as connection:
            result = connection.execute(
                """
                UPDATE processing_jobs
                SET stage = 'ready', status = 'done', last_error = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE email_id = ?
                """,
                (email_id,),
            )
            connection.commit()
        if not result.rowcount:
            self._json_error("没有找到该邮件的识别任务。", HTTPStatus.NOT_FOUND)
            return
        self._send_json({"ok": True, "email_id": email_id, "needs_review": False})

    def _test_model_connection(self, payload: dict[str, Any], kind: str) -> None:
        try:
            result = AIService(self.db_path).test_connection(kind, payload)
        except (AIServiceError, Exception) as exc:
            safe_error = _safe_ai_error(exc, str(payload.get("api_key") or ""))
            _append_log("error", f"模型测试失败：{safe_error}")
            self._json_error(safe_error, HTTPStatus.BAD_REQUEST)
            return
        _append_log("success", f"模型测试成功：{result.get('model')} ({result.get('latency_ms')} ms)")
        self._send_json({"ok": True, **result})

    def _test_screening_emails(self, payload: dict[str, Any]) -> None:
        try:
            result = AIService(self.db_path).test_screening_emails(limit=int(payload.get("limit", 3)))
        except Exception as exc:
            safe_error = _safe_ai_error(exc)
            _append_log("error", f"筛选测试失败：{safe_error}")
            self._json_error(safe_error, HTTPStatus.BAD_REQUEST)
            return
        _append_log("success", f"筛选测试完成：{len(result.get('results', []))} 封邮件")
        self._send_json({"ok": True, **result})

    def _test_analysis_emails(self, payload: dict[str, Any]) -> None:
        try:
            result = AIService(self.db_path).test_analysis_emails(limit=int(payload.get("limit", 3)))
        except Exception as exc:
            safe_error = _safe_ai_error(exc)
            _append_log("error", f"LLM 识别测试失败：{safe_error}")
            self._json_error(safe_error, HTTPStatus.BAD_REQUEST)
            return
        _append_log("success", f"LLM 识别测试完成：{len(result.get('results', []))} 封邮件")
        self._send_json({"ok": True, **result})

    def _run_screening_batch(self, payload: dict[str, Any]) -> None:
        job_id = str(uuid.uuid4())
        raw_limit = payload.get("limit")
        limit = None if raw_limit in (None, "", 0, "all") else max(1, int(raw_limit))
        mode = str(payload.get("mode") or "pending")
        self._create_ai_job(job_id, "screening")
        _append_log("info", f"开始筛选任务：{'全部重新筛选' if mode == 'all' else '仅未筛选邮件'}", job_id)

        def worker() -> None:
            try:
                result = AIService(self.db_path).screen_batch(
                    limit=limit,
                    mode=mode,
                    progress_callback=lambda completed, total, update=None: self._update_ai_job(
                        job_id, completed=completed, total=total, update=update
                    ),
                    should_pause=lambda: self._is_ai_job_pause_requested(job_id),
                )
                self._finish_ai_job(job_id, result)
                _append_log("success", f"任务完成：{result}", job_id)
            except Exception as exc:
                safe_error = _safe_ai_error(exc)
                self._fail_ai_job(job_id, safe_error)
                _append_log("error", f"任务失败：{safe_error}", job_id)

        threading.Thread(target=worker, daemon=True).start()
        self._send_json({"ok": True, "job_id": job_id, "status": "running", "total": 0})

    def _run_analysis_batch(self, payload: dict[str, Any]) -> None:
        job_id = str(uuid.uuid4())
        raw_limit = payload.get("limit")
        limit = None if raw_limit in (None, "", 0, "all") else max(1, int(raw_limit))
        mode = str(payload.get("mode") or "pending")
        mode_label = {
            "company_unresolved": "公司未识别的相关邮件",
            "all_relevant": "全部相关邮件重新识别",
        }.get(mode, "仅待识别邮件")
        self._create_ai_job(job_id, "analysis")
        _append_log("info", f"开始识别任务：{mode_label}", job_id)

        def worker() -> None:
            try:
                result = AIService(self.db_path).analyze_batch(
                    limit=limit,
                    mode=mode,
                    progress_callback=lambda completed, total, update=None: self._update_ai_job(
                        job_id, completed=completed, total=total, update=update
                    ),
                    should_pause=lambda: self._is_ai_job_pause_requested(job_id),
                )
                self._finish_ai_job(job_id, result)
                _append_log("success", f"任务完成：{result}", job_id)
            except Exception as exc:
                safe_error = _safe_ai_error(exc)
                self._fail_ai_job(job_id, safe_error)
                _append_log("error", f"任务失败：{safe_error}", job_id)

        threading.Thread(target=worker, daemon=True).start()
        self._send_json({"ok": True, "job_id": job_id, "status": "running", "total": 0})

    def _create_ai_job(self, job_id: str, job_type: str) -> None:
        with AI_JOBS_LOCK:
            AI_JOBS[job_id] = {
                "job_id": job_id,
                "type": job_type,
                "status": "running",
                "completed": 0,
                "total": 0,
                "result": None,
                "error": None,
                "pause_requested": False,
                "updates": [],
                "update_cursor": 0,
            }

    def _update_ai_job(self, job_id: str, update: dict[str, Any] | None = None, **fields: Any) -> None:
        with AI_JOBS_LOCK:
            if job_id in AI_JOBS:
                AI_JOBS[job_id].update(fields)
                if update:
                    AI_JOBS[job_id].setdefault("updates", []).append(update)
                    if len(AI_JOBS[job_id]["updates"]) > 500:
                        AI_JOBS[job_id]["updates"] = AI_JOBS[job_id]["updates"][-500:]
        completed = int(fields.get("completed") or 0)
        total = int(fields.get("total") or 0)
        if total and (completed == total or completed == 0 or completed % 10 == 0):
            _append_log("info", f"处理进度：{completed}/{total}", job_id)

    def _pause_ai_job(self, job_id: str) -> None:
        with AI_JOBS_LOCK:
            if job_id not in AI_JOBS:
                self._json_error("任务不存在。", HTTPStatus.NOT_FOUND)
                return
            AI_JOBS[job_id]["pause_requested"] = True
            AI_JOBS[job_id]["status"] = "pausing"
        _append_log("info", "收到暂停请求，等待当前邮件完成后停止", job_id)
        self._send_json({"ok": True, "job_id": job_id, "status": "pausing"})

    def _is_ai_job_pause_requested(self, job_id: str) -> bool:
        with AI_JOBS_LOCK:
            job = AI_JOBS.get(job_id)
            return bool(job and job.get("pause_requested"))

    def _finish_ai_job(self, job_id: str, result: dict[str, Any]) -> None:
        with AI_JOBS_LOCK:
            if job_id in AI_JOBS:
                total = AI_JOBS[job_id].get("total") or 0
                status = "paused" if result.get("paused") else "completed"
                AI_JOBS[job_id].update({
                    "status": status,
                    "result": result,
                    "completed": total or AI_JOBS[job_id].get("completed", 0),
                    "total": total or AI_JOBS[job_id].get("completed", 0),
                })

    def _fail_ai_job(self, job_id: str, error: str) -> None:
        with AI_JOBS_LOCK:
            if job_id in AI_JOBS:
                AI_JOBS[job_id].update({"status": "failed", "error": error})

    def _get_ai_job(self, job_id: str) -> dict[str, Any]:
        with AI_JOBS_LOCK:
            job = AI_JOBS.get(job_id)
            if not job:
                return {"ok": False, "error": "任务不存在。"}
            return {"ok": True, **job}

    def _run_single_analysis(self, payload: dict[str, Any]) -> None:
        _append_log("info", f"开始重新识别邮件：{payload.get('email_id')}")
        try:
            result = AIService(self.db_path).analyze_email(str(payload.get("email_id") or ""))
        except Exception as exc:
            self._json_error(_safe_ai_error(exc), HTTPStatus.BAD_REQUEST)
            return
        if result.get("failed"):
            errors = result.get("errors") or []
            error = errors[0].get("error") if errors else "邮件识别失败。"
            _append_log("error", f"邮件重新识别失败：{error}")
            self._json_error(_safe_ai_error(RuntimeError(error)), HTTPStatus.BAD_REQUEST)
            return
        _append_log("success", f"邮件重新识别完成：{result}")
        self._send_json({"ok": True, **result})

    def _test_ai(self, payload: dict[str, Any]) -> None:
        config = self._load_ai_config()
        if not config.get("enabled", True):
            self._json_error("AI 分析当前处于关闭状态。", HTTPStatus.BAD_REQUEST)
            return
        try:
            api_key = load_secret(AI_CREDENTIAL_KEY)
        except CredentialStoreError as exc:
            self._json_error(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if not api_key:
            self._json_error("请先保存主模型 API Key。", HTTPStatus.BAD_REQUEST)
            return

        limit = max(1, min(int(payload.get("limit", 3)), 10))
        recent_emails = self._load_ai_test_emails(50)
        if not recent_emails:
            self._json_error("本地没有可测试的邮件，请先同步邮件。", HTTPStatus.BAD_REQUEST)
            return

        test_emails = recent_emails[:limit]

        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=str(config.get("base_url") or "https://api.deepseek.com"),
            model=str(config.get("model") or "deepseek-flash"),
            timeout=int(config.get("timeout", 60)),
            max_tokens=int(config.get("max_tokens", 1500)),
            temperature=0.0,
        )
        max_chars = int(config.get("max_chars", 8000))
        concurrency = max(1, min(int(config.get("concurrency", 2)), 8))
        screening_config = self._load_screening_config()
        screening_client: OpenAICompatibleClient | None = None
        if screening_config.get("enabled", True):
            try:
                screening_key = load_secret(SCREENING_CREDENTIAL_KEY)
            except CredentialStoreError:
                screening_key = None
            screening_model = str(screening_config.get("model") or "").strip()
            if not screening_key:
                self._json_error("请先保存筛选 API Key。", HTTPStatus.BAD_REQUEST)
                return
            if not screening_model:
                self._json_error("请先获取并选择筛选模型。", HTTPStatus.BAD_REQUEST)
                return
            screening_client = OpenAICompatibleClient(
                api_key=screening_key,
                base_url=str(screening_config.get("base_url") or "https://api.siliconflow.cn/v1"),
                model=screening_model,
                timeout=int(screening_config.get("timeout", 30)),
                max_tokens=int(screening_config.get("max_tokens", 300)),
                temperature=0.0,
            )
        screening_max_chars = int(screening_config.get("max_chars", 2000))
        results: list[dict[str, Any] | None] = [None] * len(test_emails)
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_map = {
                executor.submit(
                    self._analyze_test_email,
                    client,
                    email,
                    max_chars,
                    api_key,
                    screening_client,
                    screening_max_chars,
                ): index
                for index, email in enumerate(test_emails)
            }
            for future in as_completed(future_map):
                index = future_map[future]
                results[index] = future.result()
        ordered_results = [item for item in results if item is not None]

        self._send_json(
            {
                "ok": True,
                "provider": config.get("provider"),
                "model": config.get("model"),
                "tested": len(ordered_results),
                "concurrency": concurrency,
                "screening_enabled": screening_client is not None,
                "screening_model": screening_config.get("model") if screening_client else None,
                "results": ordered_results,
            }
        )

    def _list_ai_models(self, payload: dict[str, Any]) -> None:
        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        if not base_url:
            self._json_error("请填写主模型 API Base URL。", HTTPStatus.BAD_REQUEST)
            return
        api_key = str(payload.get("api_key", "")).strip()
        if not api_key:
            try:
                api_key = load_secret(AI_CREDENTIAL_KEY) or ""
            except CredentialStoreError:
                api_key = ""
        if not api_key:
            self._json_error("请先输入 API Key，或保存已配置的 API Key。", HTTPStatus.BAD_REQUEST)
            return
        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=base_url,
            model="deepseek-flash",
            timeout=30,
        )
        try:
            models = client.list_models()
        except LLMClientError as exc:
            self._json_error(_safe_ai_error(exc, api_key), HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, "models": models, "base_url": base_url})

    def _analyze_test_email(
        self,
        client: OpenAICompatibleClient,
        email: dict[str, Any],
        max_chars: int,
        api_key: str,
        screening_client: OpenAICompatibleClient | None = None,
        screening_max_chars: int = 2000,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        item = {
            "email_id": email["id"],
            "subject": email["subject"],
            "from_name": email["from_name"],
            "from_email": email["from_email"],
            "received_at": email["received_at"],
        }
        try:
            if screening_client is not None:
                screening = self._screen_email(screening_client, email, screening_max_chars)
                item["screening"] = screening
                if not screening["is_relevant"]:
                    item["status"] = "skipped_screening"
                    item["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
                    return item

            raw = client.chat_json(
                SYSTEM_PROMPT,
                build_user_prompt(email, max_chars=max_chars),
            )
            item["analysis"] = validate_analysis(raw)
            item["status"] = "ok"
        except Exception as exc:
            item["status"] = "error"
            item["error"] = _safe_ai_error(exc, api_key)
        item["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return item

    def _load_ai_config(self) -> dict[str, Any]:
        config = dict(DEFAULT_AI_CONFIG)
        with self._open_db() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = 'ai.config'"
            ).fetchone()
        if row:
            try:
                stored = json.loads(row["value_json"])
            except json.JSONDecodeError:
                stored = {}
            if isinstance(stored, dict):
                config.update(stored)
        return config

    def _store_ai_config(self, config: dict[str, Any]) -> None:
        with self._open_db() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value_json, updated_at)
                VALUES ('ai.config', ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (json.dumps(config, ensure_ascii=False),),
            )
            connection.commit()

    def _load_ai_test_emails(self, limit: int) -> list[dict[str, Any]]:
        with self._open_db() as connection:
            rows = connection.execute(
                """
                SELECT id, subject, from_name, from_email, received_at,
                       COALESCE(NULLIF(body_text, ''), snippet, '') AS body_text
                FROM emails
                ORDER BY received_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _account_state(self) -> dict[str, Any]:
        account = self._first_account()
        if not account:
            return {"connected": False, "account": None, "folders": []}
        return {
            "connected": account["status"] == "active",
            "account": {
                "id": account["id"],
                "email": account["email"],
                "display_name": account["display_name"],
                "status": account["status"],
                "imap_host": account["imap_host"],
                "imap_port": account["imap_port"],
            },
            "folders": self._folder_state(account["id"]),
        }

    def _sync_state(self) -> dict[str, Any]:
        account = self._first_account()
        if not account:
            return {"connected": False, "account": None, "folders": []}
        with self._open_db() as connection:
            total = connection.execute(
                "SELECT COUNT(*) AS count FROM emails WHERE account_id = ?",
                (account["id"],),
            ).fetchone()["count"]
        return {
            "connected": account["status"] == "active",
            "account": {"id": account["id"], "email": account["email"]},
            "folders": self._folder_state(account["id"]),
            "email_count": total,
        }

    def _folder_state(self, account_id: str) -> list[dict[str, Any]]:
        with self._open_db() as connection:
            rows = connection.execute(
                """
                SELECT name, folder_type, enabled, sync_status, uidvalidity,
                       last_uid, last_synced_at, last_error
                FROM folders
                WHERE account_id = ?
                ORDER BY CASE WHEN name = 'INBOX' THEN 0 ELSE 1 END, name
                """,
                (account_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_emails(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._open_db() as connection:
            rows = connection.execute(
                """
                SELECT
                    e.id,
                    e.subject,
                    e.snippet,
                    e.body_text,
                    e.body_html,
                    e.from_name,
                    e.from_email,
                    e.received_at,
                    COALESCE(us.is_completed, 0) AS is_completed,
                    COALESCE(c.primary_type, 'unclassified') AS category,
                    co.id AS company_id,
                    co.canonical_name AS company,
                    p.title AS position,
                    d.due_date_local AS ddl,
                    ev.event_date AS event_date,
                    pj.stage AS processing_stage,
                    pj.last_error AS review_reason
                FROM emails e
                LEFT JOIN email_user_states us ON us.email_id = e.id
                LEFT JOIN classifications c ON c.email_id = e.id
                LEFT JOIN email_company_links ecl
                    ON ecl.email_id = e.id AND ecl.link_type = 'primary'
                LEFT JOIN companies co ON co.id = ecl.company_id
                LEFT JOIN positions p ON p.id = ecl.position_id
                LEFT JOIN processing_jobs pj ON pj.email_id = e.id
                LEFT JOIN (
                    SELECT email_id, MIN(due_date_local) AS due_date_local
                    FROM deadlines
                    WHERE status = 'pending'
                    GROUP BY email_id
                ) d ON d.email_id = e.id
                LEFT JOIN (
                    SELECT email_id, MIN(substr(start_at_utc, 1, 10)) AS event_date
                    FROM calendar_events
                    WHERE event_type = 'interview' AND status = 'scheduled'
                    GROUP BY email_id
                ) ev ON ev.email_id = e.id
                ORDER BY e.received_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "companyId": row["company_id"],
                "company": row["company"] or "公司未识别",
                "companyIsOther": row["category"] == "other",
                "isOther": row["category"] == "other",
                "position": row["position"],
                "fromName": row["from_name"] or "未知发件人",
                "fromEmail": row["from_email"] or "",
                "category": row["category"],
                "subject": row["subject"],
                "snippet": row["snippet"] or (row["body_text"] or "")[:120],
                "body": row["body_text"] or "",
                "bodyHtml": row["body_html"] or "",
                "receivedAt": row["received_at"],
                "deadline": row["ddl"],
                "eventDate": row["event_date"],
                "needsReview": row["processing_stage"] == "review_required",
                "reviewReason": row["review_reason"] if row["processing_stage"] == "review_required" else None,
                "isCompleted": bool(row["is_completed"]),
                "canComplete": row["category"] in {"assessment_invite", "written_test_invite", "interview_invite"},
            }
            for row in rows
        ]

    def _first_account(self) -> dict[str, Any] | None:
        with self._open_db() as connection:
            row = connection.execute(
                """
                SELECT id, provider, email, display_name, credential_ref,
                       imap_host, imap_port, smtp_host, smtp_port, status
                FROM accounts
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    @contextmanager
    def _open_db(self):
        connection = connect(self.db_path)
        try:
            yield connection
        finally:
            connection.close()

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("请求 JSON 格式错误。") from exc
        if not isinstance(payload, dict):
            raise ValueError("请求必须是 JSON 对象。")
        return payload

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, message: str, status: HTTPStatus = HTTPStatus.INTERNAL_SERVER_ERROR) -> None:
        self._send_json({"ok": False, "error": message}, status)

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the console quiet; the UI exposes sync state separately.
        return


def create_server(host: str = "127.0.0.1", port: int = 8765, db_path: Path | None = None) -> AgentMailServer:
    path = Path(db_path) if db_path else default_db_path()
    initialize_database(path)
    return AgentMailServer((host, port), path)
