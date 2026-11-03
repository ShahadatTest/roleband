"""Saved API keys are sealed before they reach the database.

What must hold, each a plausible way to get it wrong:

1. **No row holds a key in the clear.** The price key and every cloud and local
   model key are stored sealed, so a dump or a backup of the database holds
   ciphertext; each store still hands its callers the key itself.
2. **The key file is the owner's alone and there is one.** It is created on the
   first save with mode 0600, and processes saving their first key at once agree
   on one key rather than each writing its own.
3. **A key saved before sealing still works**, and saving seals it; sealing a
   sealed value does not seal it twice.
4. **A key this machine cannot open reads as no key**, never as an error and
   never as ciphertext handed to a provider: the key file is missing, or it is
   another machine's.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tracker.cloud_llm.models import CloudLLMProfileInput
from tracker.db.models import AppSetting
from tracker.intelligence_runtime import cloud_profiles, local_profiles
from tracker.local_llm.models import LocalLLMProfileInput
from tracker.platform import secrets
from tracker.platform.paths import REPO_ROOT
from tracker.profiles import prices

PRICE_KEY = "tiingo-0123456789abcdef"
CLOUD_KEY = "sk-live-cloud-0123456789"
LOCAL_KEY = "local-server-token-42"


@pytest.fixture(params=["cloud", "local"])
def model_store(request):
    if request.param == "cloud":
        return cloud_profiles, CloudLLMProfileInput, cloud_profiles.CLOUD_LLM_KEY, {
            "name": "Claude", "provider": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-x",
        }, CLOUD_KEY
    return local_profiles, LocalLLMProfileInput, local_profiles.LOCAL_LLM_KEY, {
        "name": "Local", "provider": "omlx", "model": "Qwen3-30B-A3B-4bit",
    }, LOCAL_KEY


async def _raw(db_session, key: str) -> str:
    db_session.expire_all()
    row = (await db_session.scalars(select(AppSetting).where(AppSetting.key == key))).one()
    return json.dumps(row.value)


# --------------------------------------------------------------------------- #
# 1. The stores
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_the_price_key_is_stored_sealed_and_read_back_as_itself(db_session):
    await prices.save_api_key(db_session, PRICE_KEY)
    await db_session.commit()

    stored = await _raw(db_session, prices.PRICE_FEED_KEY)
    assert PRICE_KEY not in stored and secrets.PREFIX in stored
    assert await prices.saved_api_key(db_session) == PRICE_KEY


@pytest.mark.asyncio
async def test_model_keys_are_stored_sealed_and_kept_through_an_edit_that_omits_them(db_session, model_store):
    store, payload, key, values, secret = model_store
    profile = await store.create_profile(db_session, payload(**values, api_key=secret))
    await db_session.commit()
    stored = await _raw(db_session, key)
    assert secret not in stored and secrets.PREFIX in stored
    assert (await store.get_profile(db_session, profile.id)).api_key == secret

    await store.update_profile(db_session, profile.id, payload(**{**values, "model": "edited-model"}))
    await db_session.commit()
    stored = await _raw(db_session, key)
    assert secret not in stored and secrets.PREFIX in stored
    edited = await store.get_profile(db_session, profile.id)
    assert edited.api_key == secret and edited.model == "edited-model"
    assert edited.public()["has_api_key"]


@pytest.mark.asyncio
async def test_a_key_saved_before_sealing_still_works_and_the_next_save_seals_it(db_session):
    db_session.add(AppSetting(key=prices.PRICE_FEED_KEY, value={"api_key": PRICE_KEY}))
    await db_session.commit()
    assert await prices.saved_api_key(db_session) == PRICE_KEY

    await prices.save_api_key(db_session, await prices.saved_api_key(db_session))
    await db_session.commit()
    assert PRICE_KEY not in await _raw(db_session, prices.PRICE_FEED_KEY)


@pytest.mark.asyncio
@pytest.mark.parametrize("available", ["missing", "foreign"])
async def test_a_key_this_machine_cannot_open_reads_as_no_key(db_session, monkeypatch, tmp_path, model_store, available):
    store, payload, key, values, secret = model_store
    await prices.save_api_key(db_session, PRICE_KEY)
    created = await store.create_profile(db_session, payload(**values, api_key=secret))
    await db_session.commit()

    elsewhere = tmp_path / "elsewhere.key"
    if available == "foreign":
        elsewhere.write_bytes(Fernet.generate_key())
    monkeypatch.setenv(secrets.KEY_FILE_ENV, str(elsewhere))
    assert await prices.saved_api_key(db_session) is None
    [profile] = (await store.get_state(db_session)).profiles
    assert profile.id == created.id and profile.model == values["model"]
    assert profile.api_key is None, "ciphertext is never handed to a provider as a key"
    assert not profile.public()["has_api_key"]
    assert secrets.PREFIX in await _raw(db_session, key), "reading cannot rewrite an unavailable key"


@pytest.mark.asyncio
async def test_the_seal_command_seals_every_key_left_in_the_clear_once(db_session):
    """`scripts.seal_secrets --apply` on rows written before sealing existed: every
    key ends sealed and still reads as itself, the price key keeps its
    `saved_at`, and a rerun finds nothing to do."""
    from scripts import seal_secrets

    saved_at = "2026-10-01T09:00:00+00:00"
    db_session.add_all([
        AppSetting(key=prices.PRICE_FEED_KEY, value={"api_key": PRICE_KEY, "saved_at": saved_at}),
        AppSetting(key=cloud_profiles.CLOUD_LLM_KEY, value={"profiles": [{
            **cloud_profiles.CloudLLMProfile(
                id="claude01", name="Claude", provider="anthropic", base_url="https://api.anthropic.com",
                model="claude-x", enabled=True,
            ).model_dump(mode="json"),
            "api_key": CLOUD_KEY,
        }]}),
    ])
    await db_session.commit()

    found = await seal_secrets.seal_all(db_session)
    await db_session.commit()
    assert found == {prices.PRICE_FEED_KEY: 1, cloud_profiles.CLOUD_LLM_KEY: 1, local_profiles.LOCAL_LLM_KEY: 0}
    price_row = await _raw(db_session, prices.PRICE_FEED_KEY)
    assert PRICE_KEY not in price_row and saved_at in price_row
    assert CLOUD_KEY not in await _raw(db_session, cloud_profiles.CLOUD_LLM_KEY)
    assert await prices.saved_api_key(db_session) == PRICE_KEY
    assert (await cloud_profiles.get_profile(db_session, "claude01")).api_key == CLOUD_KEY
    assert set((await seal_secrets.in_the_clear(db_session)).values()) == {0}


@pytest.mark.asyncio
async def test_the_seal_command_never_drops_a_profile_its_model_no_longer_reads(db_session, model_store):
    """A stored profile missing a field the model now requires reads as no
    profiles at all; resealing must not write that back. Only `api_key` changes."""
    from scripts import seal_secrets

    store, _, key, _, secret = model_store
    odd = {"id": "c9", "name": "Old", "api_key": secret, "something_new": [1, 2]}
    db_session.add(AppSetting(key=key, value={"profiles": [odd, None, "unsupported"], "extra": True}))
    await db_session.commit()
    assert (await store.get_state(db_session)).profiles == []

    await seal_secrets.seal_all(db_session)
    await db_session.commit()
    stored = json.loads(await _raw(db_session, key))
    profile, *others = stored["profiles"]
    assert others == [None, "unsupported"]
    assert stored["extra"] is True
    assert {k: v for k, v in profile.items() if k != "api_key"} == {k: v for k, v in odd.items() if k != "api_key"}
    assert secrets.unseal(profile["api_key"]) == secret
    await store.reseal(db_session)
    await db_session.commit()
    assert json.loads(await _raw(db_session, key)) == stored


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, [], {"profiles": "unsupported", "extra": [1, 2]}])
async def test_resealing_preserves_non_profile_raw_state(db_session, model_store, value):
    store, _, key, _, _ = model_store
    db_session.add(AppSetting(key=key, value=value))
    await db_session.commit()
    assert (await store.get_state(db_session)).profiles == []
    await store.reseal(db_session)
    await db_session.commit()
    assert json.loads(await _raw(db_session, key)) == value


@pytest.mark.asyncio
async def test_profile_writes_leave_the_transaction_to_the_caller(db_session, model_store):
    store, payload, key, values, secret = model_store
    await store.create_profile(db_session, payload(**values, api_key=secret))
    await db_session.rollback()
    assert await db_session.get(AppSetting, key) is None


@pytest.mark.asyncio
async def test_concurrent_profile_edits_both_survive_the_json_row_write(db_session, model_store, monkeypatch):
    store, payload, _, values, secret = model_store
    first_profile = await store.create_profile(db_session, payload(**values, api_key=secret))
    second_profile = await store.create_profile(db_session, payload(**{**values, "name": "Second"}, api_key=secret))
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    first_locked, second_waiting, release_first = asyncio.Event(), asyncio.Event(), asyncio.Event()
    lock = store.advisory_xact_lock
    async with factory() as first, factory() as second:
        async def controlled_lock(session, key):
            if session is second:
                second_waiting.set()
            await lock(session, key)
            if session is first:
                first_locked.set()
                await release_first.wait()

        async def edit(session, profile_id, model):
            result = await store.update_profile(session, profile_id, payload(**{**values, "model": model}))
            assert result is not None
            await session.commit()

        monkeypatch.setattr(store, "advisory_xact_lock", controlled_lock)
        tasks = [asyncio.create_task(edit(first, first_profile.id, "first-edited"))]
        try:
            async with asyncio.timeout(5):
                await first_locked.wait()
                tasks.append(asyncio.create_task(edit(second, second_profile.id, "second-edited")))
                await second_waiting.wait()
                release_first.set()
                await asyncio.gather(*tasks)
        finally:
            release_first.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    db_session.expire_all()
    saved = {profile.id: profile for profile in (await store.get_state(db_session)).profiles}
    assert saved[first_profile.id].model == "first-edited"
    assert saved[second_profile.id].model == "second-edited"
    assert {profile.api_key for profile in saved.values()} == {secret}


# --------------------------------------------------------------------------- #
# 2. to 4. The module
# --------------------------------------------------------------------------- #


def test_the_first_seal_creates_a_key_file_only_its_owner_can_read(tmp_path, monkeypatch):
    path = tmp_path / "fresh" / "secret.key"
    monkeypatch.setenv(secrets.KEY_FILE_ENV, str(path))
    sealed = secrets.seal(PRICE_KEY)

    assert sealed.startswith(secrets.PREFIX) and PRICE_KEY not in sealed
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert secrets.unseal(sealed) == PRICE_KEY
    assert not list(path.parent.glob(".secret-key-*")), "no temporary file is left behind"


def test_processes_saving_their_first_key_at_once_agree_on_one(tmp_path, monkeypatch):
    path = tmp_path / "secret.key"
    monkeypatch.setenv(secrets.KEY_FILE_ENV, str(path))
    code = "import sys; from tracker.platform import secrets; print(secrets.seal(sys.argv[1]))"
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "backend")}
    racers = [
        subprocess.Popen([sys.executable, "-c", code, f"key-{n}"], stdout=subprocess.PIPE, text=True, env=env)
        for n in range(8)
    ]
    sealed = [racer.communicate(timeout=60)[0].strip() for racer in racers]

    assert [secrets.unseal(value) for value in sealed] == [f"key-{n}" for n in range(8)]


def test_a_process_that_found_no_key_adopts_the_one_written_since(tmp_path, monkeypatch):
    """The window the concurrent test can miss, held open: this process read no
    key file, another wrote one before this one's write. The first key stays,
    and both seals open with it."""
    path = tmp_path / "secret.key"
    monkeypatch.setenv(secrets.KEY_FILE_ENV, str(path))
    theirs = secrets.seal("their key")
    written = path.read_bytes()

    real_read = secrets._read_key
    reads_left = {"n": 1}

    def stale_then_real(p):
        if reads_left["n"]:
            reads_left["n"] -= 1
            return None
        return real_read(p)

    monkeypatch.setattr(secrets, "_read_key", stale_then_real)
    mine = secrets.seal("my key")

    assert path.read_bytes() == written, "the key another process wrote is never replaced"
    monkeypatch.setattr(secrets, "_read_key", real_read)
    assert (secrets.unseal(theirs), secrets.unseal(mine)) == ("their key", "my key")


def test_empty_legacy_and_sealed_values_pass_through_as_they_are(tmp_path, monkeypatch):
    monkeypatch.setenv(secrets.KEY_FILE_ENV, str(tmp_path / "secret.key"))
    assert secrets.seal(None) is None and secrets.seal("") == ""
    assert not (tmp_path / "secret.key").exists(), "nothing to seal makes no key file"
    sealed = secrets.seal(PRICE_KEY)
    assert secrets.seal(sealed) == sealed, "never sealed twice"
    assert secrets.unseal(PRICE_KEY) == PRICE_KEY, "a key saved before sealing reads as itself"


def test_a_sealed_value_without_its_key_file_is_unavailable_not_garbage(tmp_path, monkeypatch):
    monkeypatch.setenv(secrets.KEY_FILE_ENV, str(tmp_path / "secret.key"))
    sealed = secrets.seal(PRICE_KEY)
    (tmp_path / "secret.key").unlink()

    with pytest.raises(secrets.SecretUnavailable):
        secrets.unseal(sealed)
    assert secrets.unseal_or_none(sealed) is None
    (tmp_path / "secret.key").write_text("not a key\n")
    with pytest.raises(secrets.SecretUnavailable):
        secrets.unseal(sealed)
