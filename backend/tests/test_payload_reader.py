"""One reader for a page's JSON-LD.

None is a legitimate answer ("this page carries no posting"), so a reader that
misses a shape returns None silently and the failure never surfaces as an
error. These pin every shape the reader must accept. Each case is a shape at least one real board serves.
"""

from __future__ import annotations

import pytest

from tracker.connectors.extract.payload import job_posting, text_of


def _page(body: str, *, attrs: str = 'type="application/ld+json"') -> str:
    return f"<html><head><script {attrs}>{body}</script></head><body>x</body></html>"


def test_a_bare_posting_object_is_read():
    assert job_posting(_page('{"@type": "JobPosting", "title": "Staff Engineer"}'))["title"] == (
        "Staff Engineer"
    )


def test_a_posting_inside_an_array_is_read():
    """A page that also describes its employer."""
    page = _page('[{"@type": "Organization", "name": "Acme"},'
                 ' {"@type": "JobPosting", "title": "Staff Engineer"}]')
    assert job_posting(page)["title"] == "Staff Engineer"


def test_a_posting_inside_an_at_graph_is_read():
    """A CMS emits `@graph` when one page describes
    several things — the posting, the employer, the breadcrumb trail."""
    page = _page('{"@context": "https://schema.org", "@graph": ['
                 '{"@type": "BreadcrumbList"}, {"@type": "JobPosting", "title": "Staff Engineer"}]}')
    assert job_posting(page)["title"] == "Staff Engineer"


def test_a_raw_control_character_does_not_cost_the_posting():
    """Employers paste descriptions, tabs and
    all, into a JSON string. Refusing the document loses a posting that is
    otherwise complete."""
    page = _page('{"@type": "JobPosting", "title": "Staff\tEngineer"}')
    assert job_posting(page)["title"] == "Staff\tEngineer"


def test_a_posting_that_also_declares_another_type_is_still_a_posting():
    """schema.org permits a list of types."""
    page = _page('{"@type": ["JobPosting", "Thing"], "title": "Staff Engineer"}')
    assert job_posting(page)["title"] == "Staff Engineer"


def test_the_first_posting_wins_over_later_blocks():
    page = (
        _page('{"@type": "JobPosting", "title": "First"}')
        + _page('{"@type": "JobPosting", "title": "Second"}')
    )
    assert job_posting(page)["title"] == "First"


@pytest.mark.parametrize("page", [
    "",
    "<html><body>a careers page with no structured data</body></html>",
    _page('{"@type": "Organization", "name": "Acme"}'),
    _page("{not json at all"),
    _page('{"@type": "JobPosting"}', attrs='type="application/json"'),
])
def test_a_page_with_no_posting_says_so_rather_than_raising(page):
    """None must stay reachable and cheap: it is the honest answer for a URL
    the sitemap listed that turns out not to be a posting."""
    assert job_posting(page) is None


def test_a_malformed_block_does_not_hide_a_good_one_after_it():
    page = _page("{broken") + _page('{"@type": "JobPosting", "title": "Staff Engineer"}')
    assert job_posting(page)["title"] == "Staff Engineer"


def test_blank_and_absent_are_the_same_answer():
    """An employer who sends "" and one who sends nothing have said the same
    thing, and every caller treats them alike."""
    assert text_of("  Staff Engineer  ") == "Staff Engineer"
    assert text_of("") is None
    assert text_of("   ") is None
    assert text_of(None) is None
    # Not emptiness: a zero is a value the source stated.
    assert text_of(0) == "0"
    assert text_of(False) == "False"
