"""Validated local-model configuration. Persisted secrets never enter API output."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def normalize_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("address must use http or https")
    if parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("address must point to this Mac (localhost or loopback IP)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("address cannot contain credentials, a query, or a fragment")
    path = parsed.path.rstrip("/") or "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class LocalLLMParameters(BaseModel):
    """Supported oMLX `/v1/chat/completions` controls."""

    max_tokens: int = Field(default=32768, ge=32, le=131_072)
    temperature: float = Field(default=0.2, ge=0, le=2)
    top_p: float = Field(default=0.95, gt=0, le=1)
    top_k: int = Field(default=0, ge=0, le=100_000)
    min_p: float = Field(default=0, ge=0, le=1)
    repetition_penalty: float = Field(default=1, gt=0, le=2)
    presence_penalty: float = Field(default=0, ge=-2, le=2)
    frequency_penalty: float = Field(default=0, ge=-2, le=2)
    seed: int | None = None
    enable_thinking: bool = True
    thinking_budget: int | None = Field(default=2048, ge=0, le=131_072)
    timeout_seconds: float = Field(default=180, ge=5, le=600)

    def chat_payload(self, *, thinking: bool | None = None) -> dict:
        """Request body. `thinking` overrides `enable_thinking` for one call
        without mutating the saved profile (see `LocalLLMClient.chat`).

        When thinking is off the budget goes with it: sending a
        `thinking_budget` beside a disabled thinking channel is contradictory,
        and some servers honour the budget regardless of the toggle.
        """
        enabled = self.enable_thinking if thinking is None else thinking
        payload = self.model_dump(exclude={"timeout_seconds", "enable_thinking"})
        if not enabled:
            payload.pop("thinking_budget", None)
        payload["chat_template_kwargs"] = {"enable_thinking": enabled}
        return {key: value for key, value in payload.items() if value is not None}


class LocalLLMProfileInput(BaseModel):
    name: str = Field(json_schema_extra={"x-text": "content"}, min_length=1, max_length=80)
    provider: Literal["omlx", "openai_compatible"] = "omlx"
    base_url: str = "http://127.0.0.1:8000/v1"
    model: str = Field(min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=1024)
    parameters: LocalLLMParameters = Field(default_factory=LocalLLMParameters)

    @field_validator("name", "model")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("base_url")
    @classmethod
    def local_address(cls, value: str) -> str:
        return normalize_base_url(value)


class LocalLLMProfile(LocalLLMProfileInput):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "has_api_key": bool(self.api_key),
            "parameters": self.parameters.model_dump(),
        }


class LocalLLMState(BaseModel):
    # Whether the local tier is offered to the routing ladder at all, like
    # Apple FM's toggle and each cloud profile's `enabled`: a saved local
    # profile can leave the ladder without being deleted and losing its
    # configuration. Defaults True so existing installs keep the model they
    # have; a fresh install has no profile and therefore no local tier
    # regardless.
    enabled: bool = True
    active_profile_id: str | None = None
    profiles: list[LocalLLMProfile] = Field(default_factory=list)

    def public(self) -> dict:
        active = self.active_profile_id
        if active not in {profile.id for profile in self.profiles}:
            active = self.profiles[0].id if self.profiles else None
        return {
            "enabled": self.enabled,
            "active_profile_id": active,
            "profiles": [profile.public() for profile in self.profiles],
        }
