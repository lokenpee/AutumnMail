"""Parse RFC email messages into the project's normalized representation."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from email.policy import default
from email.utils import parsedate_to_datetime


@dataclass(slots=True)
class ParsedEmail:
    canonical_key: str
    message_id: str | None
    subject: str
    from_name: str | None
    from_email: str | None
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    received_at: str | None = None
    body_text: str = ""
    body_html: str | None = None
    snippet: str = ""
    attachment_count: int = 0
    size_bytes: int = 0


def _decode_header_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    pieces: list[str] = []
    for content, charset in decode_header(str(value)):
        if isinstance(content, bytes):
            pieces.append(content.decode(charset or "utf-8", errors="replace"))
        else:
            pieces.append(content)
    return "".join(pieces).strip()


def _decode_part(part: Message) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        payload = None
    if payload is None:
        raw = part.get_payload()
        if isinstance(raw, str):
            return raw
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _extract_bodies(message: Message) -> tuple[str, str | None, int]:
    if not message.is_multipart():
        content_type = message.get_content_type().lower()
        if content_type == "text/html":
            html_body = _decode_part(message)
            return _strip_html(html_body), html_body, 0
        return _decode_part(message), None, 0

    text_parts: list[str] = []
    html_parts: list[str] = []
    attachment_count = 0
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        if "attachment" in disposition or filename:
            attachment_count += 1
            continue
        content_type = part.get_content_type().lower()
        if content_type == "text/plain":
            text_parts.append(_decode_part(part))
        elif content_type == "text/html":
            html_parts.append(_decode_part(part))

    html_body = "\n".join(part for part in html_parts if part) or None
    if text_parts:
        text_body = "\n".join(part for part in text_parts if part)
    elif html_body:
        text_body = _strip_html(html_body)
    else:
        text_body = ""
    return text_body.strip(), html_body, attachment_count


def _address_values(message: Message, header: str) -> list[str]:
    values = message.get_all(header, [])
    result: list[str] = []
    for value in values:
        for piece in str(value).split(","):
            decoded = _decode_header_value(piece)
            if decoded:
                result.append(decoded)
    return result


def parse_email(raw_bytes: bytes, fallback_uid: str = "") -> ParsedEmail:
    """Parse an RFC822 message and normalize common headers and bodies."""

    message = message_from_bytes(raw_bytes, policy=default)
    message_id = _decode_header_value(message.get("Message-ID")) or None
    subject = _decode_header_value(message.get("Subject"))
    from_header = _decode_header_value(message.get("From"))
    to_values = _address_values(message, "To")
    cc_values = _address_values(message, "Cc")

    from_name: str | None = None
    from_email: str | None = None
    match = re.match(r"^(?P<name>.*?)\s*<(?P<email>[^>]+)>$", from_header)
    if match:
        from_name = match.group("name").strip().strip('"') or None
        from_email = match.group("email").strip().lower()
    elif "@" in from_header:
        from_email = from_header.strip().lower()

    date_header = message.get("Date")
    received_at: str | None = None
    if date_header:
        try:
            parsed = parsedate_to_datetime(str(date_header))
            if parsed:
                received_at = parsed.isoformat()
        except Exception:
            received_at = None

    body_text, body_html, attachment_count = _extract_bodies(message)
    snippet = re.sub(r"\s+", " ", body_text).strip()[:120]
    if not message_id:
        seed = "|".join(
            [
                from_header,
                subject,
                str(date_header or ""),
                str(len(raw_bytes)),
                fallback_uid,
            ]
        )
        canonical_key = hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()
    else:
        canonical_key = f"message-id:{message_id}"

    return ParsedEmail(
        canonical_key=canonical_key,
        message_id=message_id,
        subject=subject or "(无主题)",
        from_name=from_name,
        from_email=from_email,
        to=to_values,
        cc=cc_values,
        received_at=received_at,
        body_text=body_text,
        body_html=body_html,
        snippet=snippet,
        attachment_count=attachment_count,
        size_bytes=len(raw_bytes),
    )
