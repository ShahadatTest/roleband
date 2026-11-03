"""A route that waits on the outside holds no database transaction meanwhile.

Each route here reads what it needs, then waits on a careers site, a model
server or a cloud provider. While it waits, a transaction left open would hold
its locks for as long as the outside takes to answer, and a migration's ALTER
would queue behind it with every later query on that table. So the outside
call is wrapped to look, from a connection of its own, for any other session
on this database inside a transaction at that moment.
"""

from __future__ import annotations

import copy

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import tracker.api.routers.companies as companies_router
import tracker.api.routers.intelligence as intelligence_router
import tracker.api.routers.lineage as lineage_router
import tracker.api.routers.recipes as recipes_router
from tests.factories import make_company
from tests.intelligence_contract_seed import (
    PinnedMachine,
    pin_integration_machine,
    seed_cloud_connection,
    seed_local_connection,
)
from tests.lineage_contract_seed import pin_lineage_environment, seed_lineage_contract
from tests.test_recipe_adapter import PAGE, RECIPE
from tracker.api.deps import end_read
from tracker.connectors.listing import base
from tracker.db.models import TrackedCompany
from tracker.intelligence.providers.local import LocalLLMProvider
from tracker.local_llm.client import LocalLLMClient
from tracker.workflows import recipe_preview

pytestmark = pytest.mark.usefixtures("no_escape")

OPEN_ELSEWHERE = text(
    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
    " AND pid <> pg_backend_pid() AND backend_type = 'client backend' AND xact_start IS NOT NULL"
)


@pytest.fixture
def machine(monkeypatch, tmp_path, no_escape) -> PinnedMachine:
    return pin_integration_machine(monkeypatch, tmp_path)


class Watch:
    """Counts the transactions open elsewhere each time the outside is called."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._engine = db_session.bind
        self.seen: list[int] = []

    def around(self, real):
        async def call(*args, **kwargs):
            async with self._engine.connect() as conn:
                self.seen.append(await conn.scalar(OPEN_ELSEWHERE))
            return await real(*args, **kwargs)

        return call


@pytest_asyncio.fixture
async def watch(db_session) -> Watch:
    # The fixture's own session ends its transaction, so only the route's count.
    await db_session.commit()
    return Watch(db_session)


@pytest.mark.asyncio
async def test_finding_a_moved_board_reads_the_site_outside_a_transaction(api_client, db_session, watch, monkeypatch):
    db_session.add(make_company("hex", "Hex"))
    await db_session.commit()

    async def nothing_found(**_kwargs):
        return None

    monkeypatch.setattr(companies_router, "find_moved_board", watch.around(nothing_found))
    response = await api_client.post("/api/companies/hex/board/find", json={})
    assert response.status_code == 200, response.text
    assert response.json() == {"candidate": None}
    assert watch.seen == [0]


@pytest.mark.asyncio
async def test_validating_a_recipe_reads_the_listing_outside_a_transaction(api_client, db_session, watch, monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://careers.demo.com/jobs":
            return httpx.Response(200, text=PAGE)
        if str(request.url) == "https://careers.demo.com/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(404)

    def client(*_a, **_kw):
        return httpx.AsyncClient(transport=httpx.MockTransport(handle))

    monkeypatch.setattr(base, "make_tier_client", client)
    monkeypatch.setattr(recipe_preview, "public_client", client)
    saved = await api_client.post("/api/connector-recipes", json={"document": copy.deepcopy(RECIPE)})
    assert saved.status_code == 201, saved.text
    revision_id = saved.json()["revision_id"]

    monkeypatch.setattr(recipes_router, "validate_document", watch.around(recipes_router.validate_document))
    validated = await api_client.post(f"/api/connector-recipes/demo-careers/revisions/{revision_id}/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["passed"] is True
    assert watch.seen == [0]
    listing = (await api_client.get("/api/connector-recipes")).json()
    assert listing[0]["slug"] == "demo-careers", "the validation after the read was still saved"


@pytest.mark.asyncio
async def test_a_local_model_test_waits_on_the_model_outside_a_transaction(api_client, db_session, machine, watch, monkeypatch):
    saved = await seed_local_connection(db_session)
    await db_session.commit()
    monkeypatch.setattr(LocalLLMClient, "test_connection", watch.around(LocalLLMClient.test_connection))
    response = await api_client.post(f"/api/intelligence/local-models/{saved.id}/test", json={})
    assert response.status_code == 200, response.text
    assert watch.seen == [0]


@pytest.mark.asyncio
async def test_the_local_server_status_probes_outside_a_transaction(api_client, db_session, machine, watch, monkeypatch):
    await seed_local_connection(db_session)
    await db_session.commit()
    monkeypatch.setattr(LocalLLMProvider, "availability", watch.around(LocalLLMProvider.availability))
    response = await api_client.get("/api/intelligence/local-models/server")
    assert response.status_code == 200, response.text
    assert watch.seen == [0]


@pytest.mark.asyncio
async def test_a_cloud_model_test_waits_on_the_provider_outside_a_transaction(api_client, db_session, machine, watch, monkeypatch):
    saved = await seed_cloud_connection(db_session)
    await db_session.commit()
    monkeypatch.setattr(
        intelligence_router, "test_cloud_llm_connection", watch.around(intelligence_router.test_cloud_llm_connection),
    )
    response = await api_client.post(f"/api/intelligence/cloud-models/{saved.id}/test")
    assert response.status_code == 200, response.text
    assert watch.seen == [0]


@pytest.mark.asyncio
async def test_the_self_test_asks_the_model_outside_a_transaction(api_client, db_session, machine, watch, monkeypatch):
    assert (await api_client.put("/api/intelligence", json={"enabled": True})).status_code == 200
    monkeypatch.setattr(machine.apple, "availability", watch.around(machine.apple.availability))
    response = await api_client.post("/api/intelligence/test", json={"text": "Staff engineer. Kubernetes."})
    assert response.status_code == 200, response.text
    assert watch.seen == [0]


@pytest.mark.asyncio
async def test_a_duplicate_assessment_asks_the_model_outside_a_transaction(api_client, db_session, watch, monkeypatch):
    seeded = await seed_lineage_contract(db_session)
    await db_session.commit()
    pin_lineage_environment(monkeypatch)
    monkeypatch.setattr(lineage_router, "assess_duplicate", watch.around(lineage_router.assess_duplicate))
    response = await api_client.post(f"/api/lineage/links/{seeded.pending_link}/analyze")
    assert response.status_code == 200, response.text
    assert watch.seen == [0]


@pytest.mark.asyncio
async def test_ending_a_read_refuses_a_session_with_unsaved_changes(db_session):
    db_session.add(make_company("hex", "Hex"))
    with pytest.raises(RuntimeError, match="unsaved changes"):
        await end_read(db_session)
    await db_session.rollback()
    assert await db_session.get(TrackedCompany, "hex") is None
    await end_read(db_session)
    assert not db_session.in_transaction()
