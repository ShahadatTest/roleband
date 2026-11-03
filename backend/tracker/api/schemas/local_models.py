"""What the API reports about a call to a local model, shared by every route that makes one.

`LocalLLMClient.chat` builds `metrics` from the server's own `usage` block. The
timings it converts itself are integers. The token counts and rates pass through
as the server sent them, so they are typed `int | float`: Pydantic re-emits an
integer through a `float` field as `1525.0` and a float through an `int` field as
`12`, and either would change what the client receives from what the server said.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tracker.api.schemas.text_class import text

#: `LocalLLMProfileInput.provider`: the profile is validated against it before it is saved.
LocalModelProvider = Literal["omlx", "openai_compatible"]


class LocalModelMetrics(BaseModel):
    """`tracker.local_llm.client._metrics`: one completion's timings and token use."""

    model_config = ConfigDict(extra="forbid")

    wall_time_ms: int
    total_time_ms: int | None
    time_to_first_token_ms: int | None
    prompt_eval_ms: int | None
    generation_ms: int | None
    prompt_tokens: int | float | None
    completion_tokens: int | float | None
    total_tokens: int | float | None
    cached_prompt_tokens: int | float | None
    prompt_tokens_per_second: int | float | None
    generation_tokens_per_second: int | float | None
    finish_reason: str | None = Field(json_schema_extra=text("code"))
    context_window: int | None
