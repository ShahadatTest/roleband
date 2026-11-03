"""A search query reaches a cloud model only with the user's AI egress switch on.

The query is text the user typed. Search may send it to Anthropic for parsing
(`tracker/search/llm.py`), and the switch in Settings, stored through
`set_ai_egress_enabled`, decides whether it can: enabling the search model and
setting a key is not enough. The model endpoint is replaced at the HTTP client,
so a query that would leave the machine is recorded instead.
"""

from __future__ import annotations

import httpx
import pytest

from tracker.company_discovery import company_names
from tracker.config import get_settings
from tracker.search import best_match, llm
from tracker.search.best_match import relevance_search
from tracker.settings_store import set_ai_egress_enabled

QUERY = "staff pm at google"
BROWSE = {"status": "open", "hidden": []}


def _search_model_on():
    return get_settings().model_copy(
        update={"search_llm_enabled": True, "anthropic_api_key": "sk-ant-test-not-a-key"}
    )


class _ModelEndpoint:
    """The Anthropic endpoint at the HTTP boundary: records every request."""

    def __init__(self) -> None:
        self.posted: list[dict] = []

    def client(self, **_kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, *, json, headers):
        self.posted.append({"url": url, "text": json["messages"][0]["content"]})
        answer = {"content": [{"type": "tool_use", "name": "structured_query", "input": {
            "company": ["google"], "level_band": [], "family": [], "workplace_type": [],
            "location_group": [], "comp_min": None, "comp_max": None, "remainder": "staff pm",
        }}]}
        return httpx.Response(200, json=answer, request=httpx.Request("POST", url))


@pytest.fixture
def endpoint(monkeypatch) -> _ModelEndpoint:
    model = _ModelEndpoint()
    monkeypatch.setattr(llm, "make_client", model.client)
    monkeypatch.setattr(llm, "get_settings", _search_model_on)
    return model


async def _no_vector(_text):
    return None


@pytest.mark.asyncio
async def test_a_query_stays_on_the_machine_while_ai_egress_is_off(endpoint):
    assert await llm.llm_parse(QUERY, egress_allowed=False, companies=company_names()) is None
    assert endpoint.posted == []


@pytest.mark.asyncio
async def test_a_query_reaches_the_model_only_with_ai_egress_on(endpoint):
    parsed = await llm.llm_parse(QUERY, egress_allowed=True, companies=company_names())
    assert endpoint.posted == [{"url": llm._ANTHROPIC_URL, "text": QUERY}]
    assert parsed is not None and parsed.company == ["google"]


@pytest.mark.asyncio
async def test_search_follows_the_switch_stored_from_settings(db_session, endpoint, monkeypatch):
    monkeypatch.setattr(best_match, "get_settings", _search_model_on)

    await relevance_search(db_session, BROWSE, QUERY, 25, 0, embed=_no_vector)
    assert endpoint.posted == [], "egress is off until the user turns it on"

    await set_ai_egress_enabled(db_session, True)
    await db_session.commit()
    await relevance_search(db_session, BROWSE, QUERY, 25, 0, embed=_no_vector)
    assert [p["text"] for p in endpoint.posted] == [QUERY]

    await set_ai_egress_enabled(db_session, False)
    await db_session.commit()
    await relevance_search(db_session, BROWSE, QUERY, 25, 0, embed=_no_vector)
    assert len(endpoint.posted) == 1, "turning the switch off stops the next query"
