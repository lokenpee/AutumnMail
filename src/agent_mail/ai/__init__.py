"""AI analysis adapters and prompts."""

from .client import OpenAICompatibleClient, LLMClientError
from .prefilter import PreFilterResult, prefilter_email
from .prompts import (
    SCREENING_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_screening_prompt,
    build_user_prompt,
)
from .schema import (
    ANALYSIS_SCHEMA_EXAMPLE,
    AnalysisValidationError,
    validate_analysis,
    validate_screening,
)

__all__ = [
    "OpenAICompatibleClient",
    "LLMClientError",
    "SYSTEM_PROMPT",
    "build_user_prompt",
    "SCREENING_SYSTEM_PROMPT",
    "build_screening_prompt",
    "validate_screening",
    "PreFilterResult",
    "prefilter_email",
    "ANALYSIS_SCHEMA_EXAMPLE",
    "AnalysisValidationError",
    "validate_analysis",
]
