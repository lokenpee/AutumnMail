"""Shared domain enumerations.

Enum values intentionally match the SQLite CHECK constraints in
``agent_mail.db.schema.sql``.
"""

from __future__ import annotations

from enum import Enum


class _StringEnum(str, Enum):
    """String enum compatible with Python 3.10."""

    def __str__(self) -> str:
        return self.value


class EmailCategory(_StringEnum):
    APPLICATION_RECEIVED = "application_received"
    REJECTED = "rejected"
    ASSESSMENT_INVITE = "assessment_invite"
    WRITTEN_TEST_INVITE = "written_test_invite"
    INTERVIEW_INVITE = "interview_invite"
    OFFER = "offer"
    UNCLASSIFIED = "unclassified"


class PipelineStatus(_StringEnum):
    SUBMITTED = "submitted"
    APPLICATION_RECEIVED = "application_received"
    ASSESSMENT = "assessment"
    WRITTEN_TEST = "written_test"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    NO_RESPONSE = "no_response"
    UNKNOWN = "unknown"


class CompanyLinkType(_StringEnum):
    PRIMARY = "primary"
    MENTIONED = "mentioned"
    CANDIDATE = "candidate"


class ClassificationSource(_StringEnum):
    RULE = "rule"
    MODEL = "model"
    USER = "user"


class DeadlinePrecision(_StringEnum):
    DATE = "date"
    DATETIME = "datetime"


class DeadlineSource(_StringEnum):
    AUTO = "auto"
    MANUAL = "manual"


class DeadlineStatus(_StringEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProcessingStage(_StringEnum):
    IMPORTED = "imported"
    NORMALIZED = "normalized"
    LINKED = "linked"
    CLASSIFIED = "classified"
    DEADLINE_EXTRACTED = "deadline_extracted"
    REVIEW_REQUIRED = "review_required"
    READY = "ready"
    FAILED = "failed"


class SyncStatus(_StringEnum):
    PENDING = "pending"
    SYNCING = "syncing"
    READY = "ready"
    FAILED = "failed"
