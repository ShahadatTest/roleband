"""The two kinds of shape a response model is.

`Built` is a shape this codebase constructs, so it forbids unknown keys: a key
a serializer adds without its model is a 500 a contract test catches, never
output that silently fails to arrive. `Stored` is a shape read back from JSONB:
the keys it names are typed and any other key is kept as stored.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Built(BaseModel):
    """A shape this codebase constructs: every key is known."""

    model_config = ConfigDict(extra="forbid")


class Stored(BaseModel):
    """A shape read back from JSONB: a key the model does not name is kept."""

    model_config = ConfigDict(extra="allow")
