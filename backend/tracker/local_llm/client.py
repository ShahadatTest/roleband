"""Async OpenAI-compatible client with oMLX metrics and strict failure states."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from tracker.local_llm.models import LocalLLMProfile
from tracker.platform.http import make_client


class LocalLLMError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, failure_class: str = "api_error"):
        super().__init__(message)
        self.status_code = status_code
        self.failure_class = failure_class


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    finish_reason: str | None
    metrics: dict[str, Any]


def _seconds_to_ms(value: Any) -> int | None:
    return round(float(value) * 1000) if isinstance(value, (int, float)) else None


def _metrics(response: dict, *, wall_time_ms: int, context_window: int | None) -> dict:
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    details = usage.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    choice = response.get("choices", [{}])[0] if response.get("choices") else {}
    return {
        "wall_time_ms": wall_time_ms,
        "total_time_ms": _seconds_to_ms(usage.get("total_time")),
        "time_to_first_token_ms": _seconds_to_ms(usage.get("time_to_first_token")),
        "prompt_eval_ms": _seconds_to_ms(usage.get("prompt_eval_duration")),
        "generation_ms": _seconds_to_ms(usage.get("generation_duration")),
        "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
        "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
        "total_tokens": usage.get("total_tokens"),
        "cached_prompt_tokens": details.get("cached_tokens"),
        "prompt_tokens_per_second": usage.get("prompt_tokens_per_second"),
        "generation_tokens_per_second": usage.get("generation_tokens_per_second"),
        "finish_reason": choice.get("finish_reason"),
        "context_window": context_window,
    }


class LocalLLMClient:
    def __init__(self, profile: LocalLLMProfile, client: httpx.AsyncClient | None = None):
        self.profile = profile
        self._client = client

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.profile.api_key:
            headers["Authorization"] = f"Bearer {self.profile.api_key}"
        return headers

    async def _get_client(self):
        if self._client is not None:
            return self._client, False
        return (
            make_client(timeout=self.profile.parameters.timeout_seconds),
            True,
        )

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        client, owned = await self._get_client()
        try:
            response = await client.request(
                method, f"{self.profile.base_url}{path}", headers=self.headers, **kwargs
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("response was not a JSON object")
            return data
        except httpx.TimeoutException as exc:
            raise LocalLLMError(
                f"Local model timed out after {self.profile.parameters.timeout_seconds:g}s.",
                status_code=504,
                failure_class="timeout",
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                detail = str(exc.response.json().get("error", {}).get("message", ""))
            except (ValueError, AttributeError):
                pass
            message = f"Local model returned HTTP {exc.response.status_code}"
            if detail:
                message += f": {detail}"
            raise LocalLLMError(message, failure_class="http_error") from exc
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise LocalLLMError(
                f"Could not reach the local model: {exc}", failure_class="connection"
            ) from exc
        finally:
            if owned:
                await client.aclose()

    async def list_models(self) -> list[dict]:
        data = await self._request("GET", "/models")
        models = data.get("data")
        if not isinstance(models, list):
            raise LocalLLMError("The local server returned an invalid model list.")
        return [item for item in models if isinstance(item, dict)]

    async def chat(
        self,
        *,
        system: str,
        prompt: str,
        json_mode: bool = False,
        thinking: bool | None = None,
    ) -> ChatResult:
        """One non-streaming completion.

        `thinking` overrides the profile's `enable_thinking` for THIS call only;
        the saved profile is never mutated. Structured-output callers pass False:
        thinking on costs many times the latency and completion tokens for no
        accuracy gain on structured output, and the reasoning arrives in the
        visible channel, ahead of the JSON. The profile setting still governs
        free-form use.
        """
        models = await self.list_models()
        info = next((item for item in models if item.get("id") == self.profile.model), None)
        if info is None:
            available = ", ".join(str(item.get("id")) for item in models[:5]) or "none"
            raise LocalLLMError(
                f'Model "{self.profile.model}" is not available. Server models: {available}.',
                status_code=400,
                failure_class="model_not_found",
            )
        payload = {
            "model": self.profile.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            **self.profile.parameters.chat_payload(thinking=thinking),
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        response = await self._request("POST", "/chat/completions", json=payload)
        wall_time_ms = round((time.monotonic() - started) * 1000)
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LocalLLMError("The local model returned no completion choice.")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LocalLLMError("The local model returned an empty final response.")
        finish_reason = choices[0].get("finish_reason")
        metrics = _metrics(
            response,
            wall_time_ms=wall_time_ms,
            context_window=info.get("max_model_len") if isinstance(info.get("max_model_len"), int) else None,
        )
        return ChatResult(
            content=content.strip(),
            model=str(response.get("model") or self.profile.model),
            finish_reason=str(finish_reason) if finish_reason is not None else None,
            metrics=metrics,
        )

    async def test_connection(self, prompt: str | None = None) -> dict:
        expected = "RoleBand local model connection is ready."
        result = await self.chat(
            system="Follow the user's output instruction exactly. Return only the final answer.",
            prompt=prompt.strip() if prompt and prompt.strip() else f"Reply exactly: {expected}",
        )
        truncated = result.finish_reason == "length"
        return {
            "ok": not truncated,
            "profile_id": self.profile.id,
            "provider": self.profile.provider,
            "model": result.model,
            "response": result.content,
            "finish_reason": result.finish_reason,
            "truncated": truncated,
            "metrics": result.metrics,
        }
