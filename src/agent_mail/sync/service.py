"""Synchronize 163 mailbox messages into the local SQLite database."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from agent_mail.mail import NeteaseImapClient, parse_email
from agent_mail.security import credential_target


@dataclass(slots=True)
class SyncResult:
    account_id: str
    email: str
    folder: str
    uidvalidity: str | None
    fetched: int
    inserted: int
    updated: int
    skipped: int
    last_uid: int


def _account_id(email: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"agent-mail:163:{email.strip().lower()}"))


def _email_id(account_id: str, canonical_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{account_id}:{canonical_key}"))


def _folder_id(account_id: str, folder_name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{account_id}:folder:{folder_name}"))


def _internal_date_to_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def test_connection(email: str, auth_code: str) -> list[str]:
    """Verify 163 IMAP login and return visible folder names."""

    client = NeteaseImapClient(email=email, auth_code=auth_code)
    client.connect()
    try:
        return [folder.name for folder in client.list_folders()]
    finally:
        client.disconnect()


class MailSyncService:
    """Persist recent INBOX messages from a 163 account."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def ensure_account(self, email: str, display_name: str | None = None) -> str:
        account_id = _account_id(email)
        credential_ref = credential_target(email)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO accounts (
                    id, provider, email, display_name, credential_ref, status
                ) VALUES (?, '163', ?, ?, ?, 'active')
                ON CONFLICT(provider, email) DO UPDATE SET
                    display_name = excluded.display_name,
                    credential_ref = excluded.credential_ref,
                    status = 'active',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (account_id, email.strip().lower(), display_name, credential_ref),
            )
        return account_id

    def ensure_folder(self, account_id: str, name: str = "INBOX") -> str:
        folder_id = _folder_id(account_id, name)
        folder_type = "inbox" if name.upper() == "INBOX" else "custom"
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO folders (
                    id, account_id, name, folder_type, enabled, sync_status
                ) VALUES (?, ?, ?, ?, 1, 'pending')
                ON CONFLICT(account_id, name) DO UPDATE SET
                    enabled = 1,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (folder_id, account_id, name, folder_type),
            )
        return folder_id

    def sync_recent(
        self,
        email: str,
        auth_code: str,
        days: int = 30,
        limit: int | None = None,
        folder: str = "INBOX",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> SyncResult:
        if start_date is None and end_date is None:
            start_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        if start_date and end_date and start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期。")

        account_id = self.ensure_account(email)
        folder_id = self.ensure_folder(account_id, folder)
        self._mark_folder_syncing(folder_id)

        client = NeteaseImapClient(email=email, auth_code=auth_code)
        try:
            client.connect()
            client.select_folder(folder, readonly=True)
            uidvalidity = client.get_uidvalidity(folder)
            uids = client.search_range(start_date=start_date, end_date=end_date)
            if limit is not None:
                uids = uids[-limit:]
            fetched_messages = client.fetch_emails(uids)

            inserted = 0
            updated = 0
            skipped = 0
            last_uid = 0
            for fetched in fetched_messages:
                try:
                    canonical_id, was_inserted = self._upsert_email(
                        account_id=account_id,
                        folder_id=folder_id,
                        uid=fetched.uid,
                        flags=fetched.flags,
                        internal_date=fetched.internal_date,
                        raw_bytes=fetched.raw_bytes,
                    )
                    if canonical_id is None:
                        skipped += 1
                    elif was_inserted:
                        inserted += 1
                    else:
                        updated += 1
                    last_uid = max(last_uid, int(fetched.uid))
                except Exception:
                    skipped += 1

            self._mark_folder_ready(folder_id, uidvalidity, last_uid)
            return SyncResult(
                account_id=account_id,
                email=email.strip().lower(),
                folder=folder,
                uidvalidity=uidvalidity,
                fetched=len(fetched_messages),
                inserted=inserted,
                updated=updated,
                skipped=skipped,
                last_uid=last_uid,
            )
        except Exception as exc:
            self._mark_folder_failed(folder_id, str(exc))
            raise
        finally:
            client.disconnect()

    def _upsert_email(
        self,
        account_id: str,
        folder_id: str,
        uid: str,
        flags: tuple[str, ...],
        internal_date: str | None,
        raw_bytes: bytes,
    ) -> tuple[str | None, bool]:
        parsed = parse_email(raw_bytes, fallback_uid=uid)
        received_at = parsed.received_at or _internal_date_to_iso(internal_date) or datetime.now(timezone.utc).isoformat()
        email_id = _email_id(account_id, parsed.canonical_key)
        exists = self.connection.execute(
            "SELECT 1 FROM emails WHERE id = ?",
            (email_id,),
        ).fetchone() is not None

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO emails (
                    id, account_id, canonical_key, message_id, thread_key,
                    subject, from_name, from_email, to_json, cc_json,
                    received_at, body_text, body_html, snippet,
                    has_attachments, attachment_count, size_bytes, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, canonical_key) DO UPDATE SET
                    subject = excluded.subject,
                    from_name = excluded.from_name,
                    from_email = excluded.from_email,
                    to_json = excluded.to_json,
                    cc_json = excluded.cc_json,
                    received_at = excluded.received_at,
                    body_text = excluded.body_text,
                    body_html = excluded.body_html,
                    snippet = excluded.snippet,
                    has_attachments = excluded.has_attachments,
                    attachment_count = excluded.attachment_count,
                    size_bytes = excluded.size_bytes,
                    content_hash = excluded.content_hash,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (
                    email_id,
                    account_id,
                    parsed.canonical_key,
                    parsed.message_id,
                    parsed.message_id,
                    parsed.subject,
                    parsed.from_name,
                    parsed.from_email,
                    json.dumps(parsed.to, ensure_ascii=False),
                    json.dumps(parsed.cc, ensure_ascii=False),
                    received_at,
                    parsed.body_text[:500000],
                    (parsed.body_html or "")[:500000] or None,
                    parsed.snippet,
                    1 if parsed.attachment_count else 0,
                    parsed.attachment_count,
                    parsed.size_bytes,
                    parsed.canonical_key,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO email_locations (
                    id, email_id, folder_id, uid, flags_json, is_read
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(folder_id, uid) DO UPDATE SET
                    email_id = excluded.email_id,
                    flags_json = excluded.flags_json,
                    is_read = excluded.is_read,
                    last_seen_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (
                    str(uuid.uuid5(uuid.NAMESPACE_URL, f"{folder_id}:{uid}")),
                    email_id,
                    folder_id,
                    uid,
                    json.dumps(list(flags), ensure_ascii=False),
                    1 if "\\Seen" in flags else 0,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO processing_jobs (email_id, stage, status)
                VALUES (?, 'imported', 'done')
                ON CONFLICT(email_id) DO UPDATE SET
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (email_id,),
            )
        return email_id, not exists

    def _mark_folder_syncing(self, folder_id: str) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE folders
                SET sync_status = 'syncing',
                    last_error = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (folder_id,),
            )

    def _mark_folder_ready(self, folder_id: str, uidvalidity: str | None, last_uid: int) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE folders
                SET sync_status = 'ready',
                    uidvalidity = ?,
                    last_uid = MAX(last_uid, ?),
                    last_synced_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    last_error = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (uidvalidity, last_uid, folder_id),
            )

    def _mark_folder_failed(self, folder_id: str, error: str) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE folders
                SET sync_status = 'failed',
                    last_error = ?,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (error[:500], folder_id),
            )
