"""How the contract tests read an error body (tracker/api/errors.py).

An error the API answers on purpose carries a code, its parameters and English
for logs. `said()` checks that shape, the code a real `ErrorCode`, then returns
the body as `{"detail": message}`, so a test that pinned the English reason it
always pinned keeps doing so, and every refusal it exercises is held to the
coded shape too."""

from __future__ import annotations

from tracker.api.errors import ErrorCode


def said(body: dict) -> dict:
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert set(detail) == {"code", "params", "message"}, detail
        ErrorCode(detail["code"])
        assert isinstance(detail["params"], dict)
        return {**body, "detail": detail["message"]}
    return body


def code_of(body: dict) -> str:
    return body["detail"]["code"]
