"""Pinned downloads resume against a real local HTTP server."""

from __future__ import annotations

import hashlib
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import MappingProxyType

import pytest

from tracker.semantic import provision
from tracker.semantic.manifest import ArtifactSpec, ModelSpec


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    graph = b"ranking-model-fixture\n" * 150000
    tokenizer = b'{"fixture":"tokenizer"}'
    payloads = {"graph": graph, "tokenizer": tokenizer}
    requests = []
    mode = {"value": "interrupt"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            name = self.path.rsplit("/", 1)[-1]
            content = payloads[name]
            offset = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
            requests.append((name, offset))
            if mode["value"] == "offline":
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            if mode["value"] == "ignore-range":
                offset = 0
            response = content[offset:]
            if mode["value"] == "corrupt":
                response = b"x" * len(response)
            elif mode["value"] == "oversized":
                response += b"untrusted excess"
            self.send_response(206 if offset else 200)
            if offset:
                self.send_header("Content-Range", f"bytes {offset}-{len(content)-1}/{len(content)}")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            if mode["value"] == "interrupt" and name == "graph":
                mode["value"] = "normal"
                self.wfile.write(response[:1 << 20])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_WR)
                return
            self.wfile.write(response)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    spec = ModelSpec(
        name="fixture", repo="fixture", revision="1" * 40, dim=2, max_tokens=16, pooling="cls",
        tiers=MappingProxyType({"fp32": ArtifactSpec("graph", "model.onnx", hashlib.sha256(graph).hexdigest(), len(graph))}),
        tokenizer=ArtifactSpec("tokenizer", "tokenizer.json", hashlib.sha256(tokenizer).hexdigest(), len(tokenizer)),
    )
    monkeypatch.setattr(provision, "DATA_DIR", tmp_path)
    monkeypatch.setattr(provision, "_MIRRORS", (f"http://127.0.0.1:{server.server_port}/{{path}}",))
    monkeypatch.setattr(provision.time, "sleep", lambda seconds: None)
    try:
        yield spec, payloads, requests, mode
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_interrupted_download_keeps_bytes_and_resumes_with_verified_progress(downloads):
    spec, payloads, requests, mode = downloads
    progress = []
    with pytest.raises(provision.ModelNotReady) as failure:
        provision.ensure_artifacts(spec, "fp32", attempts=1, progress=progress.append)
    assert failure.value.reason == "offline"
    path = provision.artifact_path(spec, spec.tiers["fp32"])
    part = path.with_name(path.name + ".part")
    offset = part.stat().st_size
    assert 0 < offset < len(payloads["graph"])
    assert not path.exists()
    provision.ensure_artifacts(spec, "fp32", attempts=1, progress=progress.append)
    assert requests[:2] == [("graph", 0), ("graph", offset)]
    assert path.read_bytes() == payloads["graph"]
    assert provision.is_ready(spec, "fp32")
    assert progress[-1].status == "ready"
    assert progress[-1].downloaded_bytes == progress[-1].total_bytes == sum(map(len, payloads.values()))
    assert any(0 < state.downloaded_bytes < state.total_bytes for state in progress)


def test_a_mirror_ignoring_range_restarts_instead_of_appending(downloads):
    spec, payloads, requests, mode = downloads
    mode["value"] = "ignore-range"
    path = provision.artifact_path(spec, spec.tiers["fp32"])
    path.parent.mkdir(parents=True)
    path.with_name(path.name + ".part").write_bytes(payloads["graph"][:100])
    provision.ensure_artifacts(spec, "fp32", attempts=1)
    assert requests[0] == ("graph", 100)
    assert path.read_bytes() == payloads["graph"]


@pytest.mark.parametrize("mode_name", ["corrupt", "oversized"])
def test_bad_downloads_never_become_a_verified_model(downloads, mode_name):
    spec, payloads, requests, mode = downloads
    mode["value"] = mode_name
    with pytest.raises(provision.ModelNotReady) as failure:
        provision.ensure_artifacts(spec, "fp32", attempts=1)
    assert failure.value.reason == "verification_failed"
    path = provision.artifact_path(spec, spec.tiers["fp32"])
    assert not path.exists() and not provision._marker(path).exists()
    part = path.with_name(path.name + ".part")
    assert not part.exists() or part.stat().st_size <= spec.tiers["fp32"].size


def test_quit_after_the_last_byte_needs_no_second_download(downloads):
    spec, payloads, requests, mode = downloads
    mode["value"] = "normal"
    for artifact, body in [(spec.tiers["fp32"], payloads["graph"]), (spec.tokenizer, payloads["tokenizer"])]:
        path = provision.artifact_path(spec, artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_name(path.name + ".part").write_bytes(body)
    provision.ensure_artifacts(spec, "fp32", attempts=1)
    assert provision.is_ready(spec, "fp32")
    assert requests == []


def test_progress_reads_never_hash_a_model(downloads, monkeypatch):
    spec, payloads, requests, mode = downloads
    path = provision.artifact_path(spec, spec.tiers["fp32"])
    path.parent.mkdir(parents=True)
    path.write_bytes(payloads["graph"])

    def unexpected_hash(path):
        raise AssertionError("polling must not hash weights")

    monkeypatch.setattr(provision, "_sha256", unexpected_hash)
    state = provision.progress_state(spec, "fp32")
    assert state.status != "ready" and state.downloaded_bytes == 0


@pytest.mark.asyncio
async def test_packaged_warmup_retries_offline_without_restarting_the_api(downloads, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from tracker.platform import preparation
    from tracker.semantic import embed

    spec, payloads, requests, mode = downloads
    mode["value"] = "offline"
    data = provision.DATA_DIR
    preparation.update(data, database="ready", service="ready")
    provision.set_tier("fp32")
    monkeypatch.setattr(embed, "PACKAGED", True)
    monkeypatch.setattr(embed, "DATA_DIR", data)
    monkeypatch.setattr(embed, "get_settings", lambda: SimpleNamespace(embedding_model="fixture"))
    monkeypatch.setattr(embed, "spec_for", lambda name: spec)
    monkeypatch.setattr(embed, "get_model", lambda: object())

    async def database_boundary():
        return "fp32"

    monkeypatch.setattr(embed, "_reconcile_tier", database_boundary)
    monkeypatch.setattr(embed, "_record_provenance", database_boundary)
    pauses = []
    original_sleep = asyncio.sleep

    async def wait_for_connection(seconds):
        if seconds != 30:
            await original_sleep(seconds)
            return
        pauses.append(seconds)
        state = preparation.read(data)
        assert state.ready and state.model == "waiting" and state.reason == "offline"
        mode["value"] = "normal"

    monkeypatch.setattr(embed.asyncio, "sleep", wait_for_connection)
    await embed.warm_model()
    state = preparation.read(data)
    assert pauses == [30]
    assert state.ready and state.model == "ready" and state.reason is None
    assert state.downloaded_bytes == state.total_bytes == sum(map(len, payloads.values()))
