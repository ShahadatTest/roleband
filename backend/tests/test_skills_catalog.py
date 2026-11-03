"""Catalogue build validation: a broken catalog.yaml must fail loudly."""

from __future__ import annotations

import pytest

from tracker.skills.catalog import CatalogError, _validate, get_catalog


def _cat(concepts: list[dict], version: int = 1) -> dict:
    return {"version": version, "concepts": concepts}


def _concept(slug: str = "python", **over) -> dict:
    base = {
        "slug": slug,
        "display": slug.title(),
        "facet": "technology",
        "category": "language",
        "description": f"{slug} language",
        "aliases": [{"alias": slug}],
    }
    base.update(over)
    return base


def _build(raw: dict):
    return _validate(raw)


def test_production_catalog_loads_and_is_nontrivial():
    cat = get_catalog()
    assert len(cat.concepts) > 50
    assert cat.taxonomy_version
    # Spec-mandated separations exist.
    by_slug = cat.by_slug
    assert by_slug["csharp"].slug != by_slug["dotnet"].slug
    assert by_slug["aspnet"].parent == "dotnet"
    assert by_slug["aws_s3"].parent == "aws"
    assert by_slug["pyspark"].parent == "spark"
    facets = {c.facet for c in cat.concepts}
    assert "technology" in facets and "behavioral_competency" in facets


def test_industry_facet_separated_from_skills():
    # Industries are their own substrate; domain_knowledge is retired. Verticals must
    # never carry a skill facet, and applied problem-domains stay skills.
    cat = get_catalog()
    by_slug = cat.by_slug
    facets = {c.facet for c in cat.concepts}
    assert "industry" in facets
    assert "domain_knowledge" not in facets
    for vertical in ("healthcare", "payments", "ads", "ecommerce", "gaming", "social_media"):
        assert by_slug[vertical].facet == "industry", vertical
    # Recommendation / search-ranking are capabilities, not industries.
    assert by_slug["recommendation"].facet == "professional_skill"
    assert by_slug["search_ranking"].facet == "professional_skill"


def test_duplicate_slug_rejected():
    with pytest.raises(CatalogError, match="duplicate slug"):
        _build(_cat([_concept("python"), _concept("python")]))


def test_alias_collision_across_concepts_rejected():
    a = _concept("python")
    b = _concept("golang", aliases=[{"alias": "python"}])
    with pytest.raises(CatalogError, match="claimed by both"):
        _build(_cat([a, b]))


def test_unknown_facet_rejected():
    with pytest.raises(CatalogError, match="unknown facet"):
        _build(_cat([_concept("python", facet="tools")]))


def test_missing_description_rejected():
    c = _concept("python")
    del c["description"]
    with pytest.raises(CatalogError, match="description"):
        _build(_cat([c]))


def test_missing_aliases_rejected():
    with pytest.raises(CatalogError, match="alias"):
        _build(_cat([_concept("python", aliases=[])]))


def test_unknown_parent_rejected():
    with pytest.raises(CatalogError, match="unknown parent"):
        _build(_cat([_concept("s3", parent="aws")]))


def test_parent_cycle_rejected():
    a = _concept("a", parent="b")
    b = _concept("b", parent="a")
    with pytest.raises(CatalogError, match="cycle"):
        _build(_cat([a, b]))


def test_invalid_guard_regex_rejected():
    c = _concept("python", aliases=[{"alias": "python", "excluded_context": "(unclosed"}])
    with pytest.raises(CatalogError, match="invalid regex"):
        _build(_cat([c]))


def test_unknown_match_mode_rejected():
    c = _concept("python", aliases=[{"alias": "python", "match": "fuzzy"}])
    with pytest.raises(CatalogError, match="match mode"):
        _build(_cat([c]))


def test_taxonomy_version_follows_content_not_comments_or_layout():
    raw = {"version": 1, "concepts": [_concept("python")]}
    same = _build(raw).taxonomy_version
    assert _build({"concepts": [_concept("python")], "version": 1}).taxonomy_version == same
    changed = {"version": 1, "concepts": [_concept("python", description="Python, the language")]}
    assert _build(changed).taxonomy_version != same


def test_a_comment_in_the_file_does_not_change_the_version(tmp_path):
    from tracker.skills.catalog import CATALOG_PATH, load_catalog

    text = CATALOG_PATH.read_text(encoding="utf-8")
    plain = tmp_path / "plain.yaml"
    plain.write_text(text, encoding="utf-8")
    commented = tmp_path / "commented.yaml"
    commented.write_text("# a new comment\n" + text + "\n# and another\n", encoding="utf-8")
    assert load_catalog(commented).taxonomy_version == load_catalog(plain).taxonomy_version
