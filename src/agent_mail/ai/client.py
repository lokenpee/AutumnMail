"""Minimal OpenAI-compatible chat client used for DeepSeek and compatible APIs."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMClientError(RuntimeError):
    """Raised when an AI API request fails."""


@dataclass(slots=True)
class OpenAICompatibleClient:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout: int = 60
    max_tokens: int = 1500
    temperature: float = 0.0

    def _endpoint(self) -> str:
        base = self.base_url.strip().rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _models_endpoint(self) -> str:
        base = self.base_url.strip().rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        return f"{base}/models"

    def list_models(self) -> list[str]:
        request = urllib.request.Request(
            self._models_endpoint(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            detail = detail.replace(self.api_key, "[redacted]")[:500]
            raise LLMClientError(f"获取模型失败 HTTP {exc.code}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise LLMClientError(f"获取模型网络错误：{exc.reason}") from exc

        try:
            data = json.loads(body)
            models = data.get("data")
            if not isinstance(models, list):
                raise ValueError("missing data")
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMClientError("模型列表响应不是有效的 OpenAI 兼容格式。") from exc

        model_ids = []
        for item in models:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                model_ids.append(item["id"])
        return sorted(set(model_ids))

    def chat_json(self, system_prompt: str, user_prompt: str, json_mode: bool = True) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            detail = detail.replace(self.api_key, "[redacted]")[:500]
            raise LLMClientError(f"AI API HTTP {exc.code}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise LLMClientError(f"AI API 网络错误：{exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMClientError("AI API 请求超时。") from exc

        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise LLMClientError("AI API 返回的不是有效 JSON。") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("AI API 响应缺少 choices/message/content。") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("AI API 返回了空内容。")

        cleaned = _strip_code_fence(content.strip())
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"模型输出不是合法 JSON：{cleaned[:300]}") from exc
        if not isinstance(result, dict):
            raise LLMClientError("模型输出必须是 JSON 对象。")
        return result


def _strip_code_fence(value: str) -> str:
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return value
