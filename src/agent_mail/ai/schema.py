"""Validate the small model result and normalize only meaningful fields."""

from __future__ import annotations

import json
from typing import Any

from .prompts import ANALYSIS_SCHEMA_EXAMPLE

ALLOWED_CATEGORIES = {
    "application_received",
    "rejected",
    "assessment_invite",
    "written_test_invite",
    "interview_invite",
    "offer",
    "other",
    "unclassified",
}
ALLOWED_COMPANY_SOURCES = {"body", "subject", "sender", "email_domain", "unknown"}
ALLOWED_LINK_TYPES = {
    "interview_meeting",
    "assessment_test",
    "written_test",
    "offer_accept",
    "application_portal",
    "resume_upload",
    "login",
    "deadline_action",
    "other",
}
IGNORED_LINK_TYPES = {"unsubscribe", "tracking", "contact"}


class AnalysisValidationError(ValueError):
    """Raised when model output does not match the expected structure."""


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _text(value: Any, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def _first_dict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list):
        return None
    return next((item for item in value if isinstance(item, dict)), None)


def _primary_dict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list):
        return None
    primary = next(
        (item for item in value if isinstance(item, dict) and item.get("is_primary")),
        None,
    )
    return primary or _first_dict(value)


def _company(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    name = _text(value.get("name"), 120) or None
    if not name:
        return None
    source = _text(value.get("source"), 20).lower()
    return {
        "name": name,
        "source": source if source in ALLOWED_COMPANY_SOURCES else "unknown",
        "confidence": _confidence(value.get("confidence")),
        "evidence": _text(value.get("evidence"), 30),
    }


def _deadline(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    date = _text(value.get("date") or value.get("normalized_date"), 10) or None
    raw_date = _text(value.get("raw_date") or value.get("raw_text"), 120)
    deadline_type = _text(value.get("deadline_type"), 20).lower()
    if deadline_type not in {"absolute", "relative", "unknown"}:
        deadline_type = "absolute" if date else "unknown"
    time = _text(value.get("time"), 20) or None
    if not date and not raw_date and not value.get("relative_amount"):
        return None
    return {
        "label": _text(value.get("label"), 80),
        "raw_date": raw_date,
        "date": date,
        "time": time,
        "deadline_type": deadline_type,
        "relative_amount": value.get("relative_amount"),
        "relative_unit": _text(value.get("relative_unit"), 20).lower(),
        "confidence": _confidence(value.get("confidence")),
    }


def _interview(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    date = _text(value.get("date") or value.get("normalized_date"), 10) or None
    raw_date = _text(value.get("raw_date"), 120)
    if not date and not raw_date:
        return None
    time = _text(value.get("time") or value.get("start_time"), 20) or None
    return {
        "round": _text(value.get("round"), 80),
        "raw_date": raw_date,
        "date": date,
        "time": time,
        "timezone": _text(value.get("timezone"), 60) or "Asia/Shanghai",
        "location": _text(value.get("location"), 160) or None,
        "meeting_url": _text(value.get("meeting_url"), 500) or None,
        "confidence": _confidence(value.get("confidence")),
    }


def _primary_link(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    link_type = _text(value.get("link_type"), 40).lower()
    if link_type in IGNORED_LINK_TYPES:
        return None
    if link_type not in ALLOWED_LINK_TYPES:
        link_type = "other"
    url = _text(value.get("url"), 1000)
    if not url:
        return None
    return {
        "link_type": link_type,
        "url": url,
        "label": _text(value.get("label"), 120),
        "confidence": _confidence(value.get("confidence")),
        "evidence": _text(value.get("evidence"), 30),
    }


def validate_analysis(data: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical result used by tests, UI, and persistence."""

    if not isinstance(data, dict):
        raise AnalysisValidationError("分析结果必须是 JSON 对象。")

    category = data.get("email_category")
    if category not in ALLOWED_CATEGORIES:
        raise AnalysisValidationError(f"非法 email_category: {category}")

    deadline_value = data.get("deadline")
    if not isinstance(deadline_value, dict):
        deadline_value = _first_dict(data.get("deadlines"))
    interview_value = data.get("interview")
    if not isinstance(interview_value, dict):
        interview_value = _first_dict(data.get("interviews")) or _first_dict(data.get("events"))
    link_value = data.get("primary_link")
    if not isinstance(link_value, dict):
        link_value = _primary_dict(data.get("links")) or _primary_dict(data.get("action_links"))

    return {
        "schema_version": "3.0",
        "email_category": category,
        "email_category_confidence": _confidence(data.get("email_category_confidence", 0.9)),
        "company": _company(data.get("company")),
        "deadline": _deadline(deadline_value),
        "interview": _interview(interview_value),
        "primary_link": _primary_link(link_value),
        "needs_review": bool(data.get("needs_review")),
        "review_reason": _text(data.get("review_reason"), 80) or None,
    }


def schema_example_json() -> str:
    return json.dumps(ANALYSIS_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)


def validate_recheck(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AnalysisValidationError("复查结果必须是 JSON 对象。")
    return {
        "company": _company(data.get("company")),
        "deadline": _deadline(data.get("deadline")),
        "review_reason": _text(data.get("review_reason"), 80) or None,
    }


def validate_screening(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AnalysisValidationError("筛选结果必须是 JSON 对象。")
    category = data.get("category_hint", "unclassified")
    if category not in ALLOWED_CATEGORIES:
        category = "unclassified"
    return {
        "is_relevant": bool(data.get("is_relevant")),
        "confidence": _confidence(data.get("confidence", 0.0)),
        "category_hint": category,
        "reason": _text(data.get("reason"), 500),
    }
