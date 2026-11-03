"""Settings > Language and region (docs/copy.md, Language and region).

The backend stores the choice and checks only that each value is a language
tag; the dashboard's manifest decides which languages exist."""

from __future__ import annotations

import pytest

from tracker.settings_store import LOCALE_KEY, get_locale, set_setting_dict


@pytest.mark.asyncio
async def test_unset_reads_as_english_and_the_system_region(api_client):
    response = await api_client.get("/api/settings/locale")
    assert response.status_code == 200, response.text
    assert response.json() == {"language": "en", "region": None}


@pytest.mark.asyncio
async def test_put_saves_language_and_region_and_get_answers_them(api_client):
    saved = await api_client.put("/api/settings/locale", json={"language": "es", "region": "en-GB"})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"language": "es", "region": "en-GB"}
    assert (await api_client.get("/api/settings/locale")).json() == {"language": "es", "region": "en-GB"}

    back = await api_client.put("/api/settings/locale", json={"language": "en", "region": None})
    assert back.json() == {"language": "en", "region": None}
    assert (await api_client.get("/api/settings/locale")).json() == {"language": "en", "region": None}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"language": "english"},
        {"language": ""},
        {"language": "es", "region": "GB<script>"},
        {"language": "es", "region": "x" * 40},
        {"language": 7},
        {},
        {"language": "es", "extra": 1},
    ],
)
async def test_put_refuses_anything_but_language_tags_and_keeps_the_saved_choice(api_client, body):
    assert (await api_client.put("/api/settings/locale", json={"language": "de", "region": None})).status_code == 200
    refused = await api_client.put("/api/settings/locale", json=body)
    assert refused.status_code == 422
    assert (await api_client.get("/api/settings/locale")).json() == {"language": "de", "region": None}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored",
    [{"language": "<b>", "region": "en-GB"}, {"language": 3}, {"region": "!!"}, {"unrelated": True}],
)
async def test_a_malformed_stored_value_never_reaches_the_dashboard(db_session, stored):
    await set_setting_dict(db_session, LOCALE_KEY, stored)
    got = await get_locale(db_session)
    assert got["language"] == "en"
    assert got["region"] in (None, "en-GB")
