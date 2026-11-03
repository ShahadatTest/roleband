"""Validated cloud connection profiles; secrets are write-only at the API."""

from __future__ import annotations

import ipaddress
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator


def normalize_cloud_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme != "https":
        raise ValueError("cloud address must use https")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("cloud address must be a host URL without credentials, query, or fragment")
    if parsed.hostname.lower() == "localhost":
        raise ValueError("cloud address cannot use localhost")
    try:
        if ipaddress.ip_address(parsed.hostname).is_private:
            raise ValueError("cloud address cannot use a private IP")
    except ValueError as exc:
        if "private IP" in str(exc):
            raise
    path = parsed.path.rstrip("/") or "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), "", ""))


class CloudLLMProfileInput(BaseModel):
    name: str = Field(json_schema_extra={"x-text": "content"}, min_length=1, max_length=80)
    provider: Literal["openai", "anthropic", "openai_compatible"]
    base_url: str
    model: str = Field(min_length=1, max_length=256)
    enabled: bool = False
    api_key: str | None = Field(default=None, max_length=2048)

    @field_validator("name", "model")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("base_url")
    @classmethod
    def secure_address(cls, value: str) -> str:
        return normalize_cloud_url(value)


class CloudLLMProfile(CloudLLMProfileInput):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "enabled": self.enabled,
            "has_api_key": bool(self.api_key),
        }


class CloudLLMState(BaseModel):
    profiles: list[CloudLLMProfile] = Field(default_factory=list)

    def public(self) -> dict:
        return {"profiles": [profile.public() for profile in self.profiles]}
