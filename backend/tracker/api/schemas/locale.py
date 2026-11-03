"""Request and response contract for Settings > Language and region.

Language picks the copy catalog the dashboard shows; region picks how numbers
and dates are written, and null follows the reader's operating system
(docs/copy.md). Backend schema/store validate the same language-tag
grammar; catalog availability belongs to the dashboard manifest. OS banners
remain English; AI output language is separately scoped.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tracker.platform.language_tags import LOCALE_TAG, is_locale_tag


class LocaleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(pattern=LOCALE_TAG, max_length=35)
    region: str | None = Field(default=None, pattern=LOCALE_TAG, max_length=35)

    @field_validator("language", "region")
    @classmethod
    def valid_tag(cls, value: str | None) -> str | None:
        if value is not None and not is_locale_tag(value):
            raise ValueError("invalid language tag")
        return value
