"""A bundle without a browser cannot silently ship a source that requires one."""

from dataclasses import replace

import pytest

from scripts import check_source_review
from tracker.source_review import SOURCE_REVIEWS, FetchTier


@pytest.mark.parametrize("tier", [FetchTier.HEADLESS, FetchTier.PROXY])
def test_packaged_build_check_is_offline_and_rejects_browser_tiers(monkeypatch, capsys, tier):
    monkeypatch.setattr("sys.argv", ["check_source_review", "--packaged"])
    assert check_source_review.main() == 0
    capsys.readouterr()
    row = replace(SOURCE_REVIEWS["workday"], fetch_tier=tier, refuses_identified_client=True)
    monkeypatch.setitem(SOURCE_REVIEWS, "workday", row)
    assert check_source_review.main() == 1
    assert f"workday: {tier.value}" in capsys.readouterr().out
