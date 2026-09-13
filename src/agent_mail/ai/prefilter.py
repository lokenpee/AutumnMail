"""Local prefilter used before spending tokens on an LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DEFAULT_PREFILTER_RULES = {
    "marketing_keywords": [
        "优惠", "限时", "折扣", "领取", "免费", "课程", "训练营",
        "简历修改", "简历优化", "求职服务", "付费", "广告", "推广",
        "报名", "unsubscribe", "退订",
    ],
    "job_keywords": {
        "offer": ["offer", "录用", "录用通知", "签约"],
        "interview_invite": ["面试", "interview", "视频面试", "线上面试"],
        "written_test_invite": ["笔试", "written test", "coding test", "编程测试"],
        "assessment_invite": ["测评", "assessment", "问卷", "questionnaire"],
        "rejected": ["未通过", "不匹配", "遗憾", "unfortunately", "not selected", "感谢您的关注"],
        "application_received": ["申请已收到", "感谢投递", "已收到您的申请", "application received"],
    },
}


@dataclass(slots=True)
class PreFilterResult:
    decision: str
    reason: str
    score: int
    category: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "score": self.score,
            "category": self.category,
        }


def _contains_any(text: str, patterns: list[str]) -> list[str]:
    return [pattern for pattern in patterns if pattern and pattern.lower() in text]


def _merged_rules(rules: dict[str, Any] | None) -> dict[str, Any]:
    merged = {
        "marketing_keywords": list(DEFAULT_PREFILTER_RULES["marketing_keywords"]),
        "job_keywords": {
            category: list(values)
            for category, values in DEFAULT_PREFILTER_RULES["job_keywords"].items()
        },
    }
    if not isinstance(rules, dict):
        return merged
    if isinstance(rules.get("marketing_keywords"), list):
        merged["marketing_keywords"] = [str(item) for item in rules["marketing_keywords"] if str(item).strip()]
    custom_job = rules.get("job_keywords")
    if isinstance(custom_job, dict):
        for category, values in custom_job.items():
            if category in merged["job_keywords"] and isinstance(values, list):
                merged["job_keywords"][category] = [str(item) for item in values if str(item).strip()]
    return merged


def prefilter_email(email: dict[str, Any], rules: dict[str, Any] | None = None) -> PreFilterResult:
    """Classify whether an email should be skipped, rule-classified, or sent to AI."""

    effective = _merged_rules(rules)
    text = " ".join(
        [
            str(email.get("subject") or ""),
            str(email.get("from_name") or ""),
            str(email.get("from_email") or ""),
            str(email.get("body_text") or ""),
        ]
    ).lower()

    for category, patterns in effective["job_keywords"].items():
        if _contains_any(text, patterns):
            return PreFilterResult(
                decision="rule_classified",
                reason=f"命中 {category} 本地规则",
                score=0,
                category=category,
            )

    marketing_hits = _contains_any(text, effective["marketing_keywords"])
    if len(marketing_hits) >= 2:
        return PreFilterResult(
            decision="skip_ai",
            reason="命中广告/营销特征：" + "、".join(marketing_hits[:4]),
            score=len(marketing_hits) * 2,
        )

    if re.search(r"no-?reply|do-?not-?reply", str(email.get("from_email") or ""), re.IGNORECASE):
        return PreFilterResult(
            decision="ai_candidate",
            reason="系统代发地址，需要判断是否属于求职流程",
            score=0,
        )

    return PreFilterResult(
        decision="ai_candidate",
        reason="未命中确定性规则，需要 AI 判断",
        score=0,
    )
