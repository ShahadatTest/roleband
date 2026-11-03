"""Project the compiled catalogue into skill_concepts / skill_aliases.

DB rows must equal exactly one catalogue version. Concepts removed from the YAML
are marked `deprecated` (identity is forever — never deleted, so historical
job_skills rows keep a valid FK). Aliases are replaced wholesale per concept;
they carry no history of their own.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import SkillAlias, SkillConcept
from tracker.skills.catalog import Catalog, get_catalog

logger = logging.getLogger(__name__)


async def sync_catalog(session: AsyncSession, catalog: Catalog | None = None) -> dict[str, int]:
    """Upsert the catalogue into the DB. Returns slug -> concept_id."""
    cat = catalog or get_catalog()

    for concept in cat.concepts:
        stmt = insert(SkillConcept).values(
            slug=concept.slug,
            display=concept.display,
            facet=concept.facet,
            category=concept.category,
            description=concept.description,
            status="active",
            taxonomy_version=cat.taxonomy_version,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["slug"],
            set_={
                "display": stmt.excluded.display,
                "facet": stmt.excluded.facet,
                "category": stmt.excluded.category,
                "description": stmt.excluded.description,
                "status": "active",
                "taxonomy_version": stmt.excluded.taxonomy_version,
            },
        )
        await session.execute(stmt)

    id_by_slug: dict[str, int] = dict(
        (await session.execute(select(SkillConcept.slug, SkillConcept.id))).all()
    )

    # Parent wiring needs every concept row to exist first.
    for concept in cat.concepts:
        parent_id = id_by_slug.get(concept.parent) if concept.parent else None
        db_concept = await session.get(SkillConcept, id_by_slug[concept.slug])
        if db_concept.parent_id != parent_id:
            db_concept.parent_id = parent_id

    # Concepts present in DB but gone from the YAML: deprecate, never delete.
    yaml_slugs = {c.slug for c in cat.concepts}
    for slug, concept_id in id_by_slug.items():
        if slug not in yaml_slugs:
            db_concept = await session.get(SkillConcept, concept_id)
            if db_concept.status == "active":
                db_concept.status = "deprecated"
                logger.info("skill concept deprecated (removed from catalogue): %s", slug)

    # Aliases: replace per concept to mirror the YAML exactly.
    for concept in cat.concepts:
        concept_id = id_by_slug[concept.slug]
        await session.execute(delete(SkillAlias).where(SkillAlias.concept_id == concept_id))
        for a in concept.aliases:
            session.add(
                SkillAlias(
                    concept_id=concept_id,
                    alias=a.alias,
                    match_mode=a.match,
                    required_context=a.required_context,
                    excluded_context=a.excluded_context,
                )
            )

    logger.info(
        "skill catalogue synced: %d concepts, taxonomy %s",
        len(cat.concepts),
        cat.taxonomy_version,
    )
    return id_by_slug
