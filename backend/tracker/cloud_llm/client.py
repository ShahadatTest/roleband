"""BYOK cloud transport.

`test_connection` stays what it always was: an explicit, user-triggered check
that never runs on its own. `CloudLLMClient.chat` is the generation path used by
the routed cloud tier — it sends job text OFF this Mac, so nothing here may be
reached without the egress opt-in checked in `intelligence.registry`.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

from tracker.cloud_llm.models import CloudLLMProfile
from tracker.platform.http import make_client


class CloudLLMError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, failure_class: str = "api_error"):
        super().__init__(message)
        self.status_code = status_code
        self.failure_class = failure_class


@dataclass(frozen=True)
class CloudChatResult:
    content: str
    model: str
    finish_reason: str | None
    metrics: dict[str, Any]


class CloudLLMClient:
    """One saved cloud profile. Mirrors `LocalLLMClient` so the two adapters on
    the seam differ only in transport, never in outcome vocabulary."""

    def __init__(self, profile: CloudLLMProfile, client: httpx.AsyncClient | None = None):
        self.profile = profile
        self._client = client

    async def chat(self, *, system: str, prompt: str, timeout: float = 60.0) -> CloudChatResult:
        if not self.profile.api_key:
            raise CloudLLMError("API key is not configured", status_code=400, failure_class="no_credentials")
        anthropic = self.profile.provider == "anthropic"
        client = self._client or make_client(timeout=timeout)
        owned = self._client is None
        started = perf_counter()
        try:
            if anthropic:
                response = await client.post(
                    f"{self.profile.base_url}/messages",
                    headers={
                        "x-api-key": self.profile.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self.profile.model,
                        "max_tokens": 2048,
                        "system": system,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
            else:
                response = await client.post(
                    f"{self.profile.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.profile.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.profile.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "stream": False,
                        "response_format": {"type": "json_object"},
                    },
                )
            _raise(response)
            body = response.json()
        except httpx.TimeoutException as exc:
            raise CloudLLMError(
                f"The cloud model timed out after {timeout:g}s.",
                status_code=504,
                failure_class="timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise CloudLLMError(
                f"Could not reach the cloud model: {exc}", failure_class="connection"
            ) from exc
        except ValueError as exc:
            raise CloudLLMError(
                "The cloud model returned a malformed response.", failure_class="validation"
            ) from exc
        finally:
            if owned:
                await client.aclose()

        wall_time_ms = round((perf_counter() - started) * 1000)
        content, finish_reason, usage = (
            _read_anthropic(body) if anthropic else _read_openai(body)
        )
        if not content.strip():
            raise CloudLLMError(
                "The cloud model returned an empty response.", failure_class="validation"
            )
        return CloudChatResult(
            content=content.strip(),
            model=str(body.get("model") or self.profile.model),
            finish_reason=finish_reason,
            metrics={
                "wall_time_ms": wall_time_ms,
                "prompt_tokens": usage[0],
                "completion_tokens": usage[1],
            },
        )


def _read_openai(body: dict) -> tuple[str, str | None, tuple[int | None, int | None]]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise CloudLLMError("The cloud model returned no completion choice.", failure_class="validation")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return (
        content if isinstance(content, str) else "",
        choices[0].get("finish_reason"),
        (usage.get("prompt_tokens"), usage.get("completion_tokens")),
    )


def _read_anthropic(body: dict) -> tuple[str, str | None, tuple[int | None, int | None]]:
    blocks = body.get("content")
    text = ""
    if isinstance(blocks, list):
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    # `max_tokens` is Anthropic's truncation signal; normalize it onto the
    # OpenAI word so one `finish_reason == "length"` check covers both.
    stop = body.get("stop_reason")
    return (
        text,
        "length" if stop == "max_tokens" else stop,
        (usage.get("input_tokens"), usage.get("output_tokens")),
    )


async def test_connection(profile: CloudLLMProfile) -> dict:
    if not profile.api_key:
        raise CloudLLMError("API key is not configured")
    started = perf_counter()
    async with make_client(timeout=30.0) as client:
        if profile.provider in {"openai", "openai_compatible"}:
            response = await client.get(
                f"{profile.base_url}/models",
                headers={"Authorization": f"Bearer {profile.api_key}"},
            )
            _raise(response)
            models = response.json().get("data", [])
            ids = {item.get("id") for item in models if isinstance(item, dict)}
            if ids and profile.model not in ids:
                raise CloudLLMError(f"Connected, but model '{profile.model}' was not listed")
        else:
            response = await client.post(
                f"{profile.base_url}/messages",
                headers={
                    "x-api-key": profile.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": profile.model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "Reply OK"}],
                },
            )
            _raise(response)
    return {
        "ok": True,
        "profile_id": profile.id,
        "provider": profile.provider,
        "model": profile.model,
        "latency_ms": round((perf_counter() - started) * 1000),
    }


def _raise(response: httpx.Response) -> None:
    if response.is_success:
        return
    detail = f"provider returned HTTP {response.status_code}"
    try:
        body = response.json()
        candidate = body.get("error") if isinstance(body, dict) else None
        if isinstance(candidate, dict) and isinstance(candidate.get("message"), str):
            detail = candidate["message"]
    except ValueError:
        pass
    # 429 is the one the router treats as "this tier is busy", not "this tier is
    # broken", so it has to survive as its own class.
    failure_class = "rate_limited" if response.status_code == 429 else "http_error"
    raise CloudLLMError(detail, status_code=response.status_code, failure_class=failure_class)
