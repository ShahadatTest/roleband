"""LLM-client contracts: transport failures surface as each module's documented
error type (LocalLLMError / CloudLLMError), never as a raw httpx exception."""

from __future__ import annotations

import httpx
import pytest

from tracker.cloud_llm import client as cloud_client

# Aliased so pytest does not collect the imported coroutine as a test.
from tracker.cloud_llm.client import CloudLLMError
from tracker.cloud_llm.client import test_connection as cloud_test_connection
from tracker.cloud_llm.models import CloudLLMProfile
from tracker.local_llm.client import LocalLLMClient, LocalLLMError
from tracker.local_llm.models import LocalLLMParameters, LocalLLMProfile

# Every test here reaches the client that bills a real model call, so
# none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")


def _local_profile() -> LocalLLMProfile:
    return LocalLLMProfile(
        id="profile12345",
        name="Local Model",
        provider="omlx",
        base_url="http://127.0.0.1:8000/v1",
        model="test-model",
        api_key=None,
        parameters=LocalLLMParameters(enable_thinking=False, max_tokens=64),
    )


def _cloud_profile(**overrides) -> CloudLLMProfile:
    values = dict(
        id="profile12345",
        name="Cloud Model",
        provider="openai",
        base_url="https://api.example.com/v1",
        model="test-model",
        enabled=True,
        api_key="contract-test-key",
    )
    values.update(overrides)
    return CloudLLMProfile(**values)


def _local_client(handler) -> LocalLLMClient:
    return LocalLLMClient(
        _local_profile(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


@pytest.mark.asyncio
async def test_local_client_http_error_surfaces_as_local_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "server exploded"}})

    with pytest.raises(LocalLLMError) as excinfo:
        await _local_client(handler).list_models()
    assert excinfo.value.failure_class == "http_error"


@pytest.mark.asyncio
async def test_local_client_connection_error_surfaces_as_local_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(LocalLLMError) as excinfo:
        await _local_client(handler).list_models()
    assert excinfo.value.failure_class == "connection"


@pytest.mark.asyncio
async def test_local_client_timeout_surfaces_as_local_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(LocalLLMError) as excinfo:
        await _local_client(handler).list_models()
    assert excinfo.value.failure_class == "timeout"


@pytest.mark.asyncio
async def test_cloud_connection_http_failure_surfaces_as_cloud_llm_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    def fake_make_client(**kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(cloud_client, "make_client", fake_make_client)

    with pytest.raises(CloudLLMError, match="invalid api key"):
        await cloud_test_connection(_cloud_profile())


@pytest.mark.asyncio
async def test_cloud_connection_without_key_is_a_cloud_llm_error():
    with pytest.raises(CloudLLMError, match="API key"):
        await cloud_test_connection(_cloud_profile(api_key=None))


def test_error_types_are_the_documented_module_surface():
    assert issubclass(LocalLLMError, RuntimeError)
    assert issubclass(CloudLLMError, RuntimeError)
    err = LocalLLMError("boom")
    assert err.status_code == 502
    assert err.failure_class == "api_error"
