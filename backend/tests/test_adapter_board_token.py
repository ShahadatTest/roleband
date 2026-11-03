"""Adapter board-token plumbing — DB-registered companies carry their own token."""

from __future__ import annotations

from tracker.connectors.listing import build_adapter
from tracker.connectors.listing.ashby import AshbyAdapter
from tracker.connectors.listing.google import GoogleAdapter
from tracker.connectors.listing.greenhouse import GreenhouseAdapter


def test_greenhouse_prefers_explicit_board_token():
    # slug != token: a user-added company whose slug differs from its board.
    a = GreenhouseAdapter("acme", board_token="acmeco")
    assert a._board_token() == "acmeco"


def test_greenhouse_falls_back_to_module_map_then_slug():
    # built-in mapping (anthropic) still resolves without an explicit token
    assert GreenhouseAdapter("anthropic")._board_token() == "anthropic"
    # unknown slug with no token falls back to the slug itself
    assert GreenhouseAdapter("stripe")._board_token() == "stripe"


def test_ashby_prefers_explicit_board_token():
    a = AshbyAdapter("acme", board_token="AcmeBoard")
    assert a._board_name() == "AcmeBoard"


def test_ashby_falls_back_to_slug():
    assert AshbyAdapter("someco")._board_name() == "someco"


def test_build_adapter_threads_token_through():
    a = build_adapter("acme", "greenhouse", "acmeco")
    assert isinstance(a, GreenhouseAdapter)
    assert a._board_token() == "acmeco"


def test_build_adapter_without_token_is_backwards_compatible():
    a = build_adapter("anthropic", "greenhouse")
    assert a.board_token is None
    assert a._board_token() == "anthropic"


def test_google_company_board_uses_company_filter_without_google_level_filter():
    adapter = GoogleAdapter("deepmind", board_token="DeepMind")
    params = adapter._params("London, UK", 1)

    assert ("company", "DeepMind") in params
    assert not any(key == "target_level" for key, _ in params)


def test_builtin_google_does_not_hide_selectable_levels():
    params = GoogleAdapter("google")._params("London, UK", 1)

    assert ("company", "DeepMind") not in params
    assert not any(key == "target_level" for key, _ in params)
