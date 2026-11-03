"""Benchmark the place-set rule against human verdicts.

Runs `lineage.place_sets.form_place_sets` over the live open postings exactly
as the pass does, EXCEPT that human verdicts never block a group: the
point is to see what the rule alone would decide, and to hold it to the
verdicts a person already gave.

LABELS. Every lineage or twin verdict between two postings of one would-be set:
- `confirmed` duplicate, "Same role": agrees with the rule;
- rejected as `different`, "Different roles": DISAGREES, exit 1;
- `twin` (either table), "Related roles": a collision, reported by link id.
  The pass leaves those groups alone; the bench names them so a person can
  relabel or keep them.

CONTROLS (a benchmark that cannot fail measures nothing). For every
set the rule forms, three altered copies of a real member are added to its
group, or the run exits 1:
- the same posting at exactly its own places must JOIN the set as `relisted`
  (the role listed again at one place);
- the same posting with its level word changed ("Senior" -> "Staff") must
  stay OUT;
- the same posting with one word of text changed (a different text hash) must
  stay OUT.
A rule that merged on text alone or on the title key alone, or that called a
second posting at one place a second place, fails one of them. No set at all
exits 3 (unmeasured).

Read-only. The membership tables may not exist yet on a database the
migration has not reached; a person's "Different roles" rows are then empty.

    python -m scripts.bench_place_sets
    python -m scripts.bench_place_sets --list 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from tracker.db.session import session_scope
from tracker.lineage.place_sets import Posting, form_place_sets, load_postings


def controls_for(member: Posting, next_id: int) -> list[Posting]:
    """Three altered copies of a real member: the first a sound rule takes in
    as `relisted`, the other two it keeps out."""
    # Exactly the member's own places: a second posting of it, same text, same
    # place, dated after it by the employer. One city of a two-city posting
    # would be a different place.
    later = (member.first_posted or member.first_seen or datetime.now(UTC)) + timedelta(days=1)
    same_place = replace(member, id=next_id, first_posted=later, first_seen=later)
    other_level = replace(
        member,
        id=next_id + 1,
        title=("Staff " + member.title)
        if "senior" in member.title.lower() or "staff" not in member.title.lower()
        else member.title.lower().replace("staff", "senior"),
        locations=("Control City, Nowhere",),
        cities=("Control City, Nowhere",),
    )
    other_text = replace(
        member,
        id=next_id + 2,
        text_hash=member.text_hash[::-1],
        locations=("Control Town, Nowhere",),
        cities=("Control Town, Nowhere",),
    )
    return [same_place, other_level, other_text]


async def _verdicts(session, ids: list[int]) -> list:
    return list(
        (
            await session.execute(
                text(
                    """
                    SELECT 'lineage' AS kind, id, job_id AS a, prior_job_id AS b, status,
                           evidence->>'review_outcome' AS outcome
                      FROM job_lineage_link
                     WHERE status IN ('confirmed', 'rejected')
                       AND job_id = ANY(cast(:ids AS integer[]))
                       AND prior_job_id = ANY(cast(:ids AS integer[]))
                    UNION ALL
                    SELECT 'twin', id, job_a_id, job_b_id, status, evidence->>'review_outcome'
                      FROM job_twin_link
                     WHERE status IN ('confirmed', 'rejected')
                       AND job_a_id = ANY(cast(:ids AS integer[]))
                       AND job_b_id = ANY(cast(:ids AS integer[]))
                    """
                ),
                {"ids": ids},
            )
        ).all()
    )


async def _rejected(session) -> set[int]:
    exists = await session.scalar(text("SELECT to_regclass('job_place_set_member') IS NOT NULL"))
    if not exists:
        return set()
    return set(
        (
            await session.scalars(
                text("SELECT job_id FROM job_place_set_member WHERE status = 'rejected'")
            )
        ).all()
    )


async def measure() -> dict:
    async with session_scope() as session:
        postings = await load_postings(session)
        rejected = await _rejected(session)
        sets, skipped = form_place_sets(postings, rejected=rejected)
        member_ids = [i for s in sets for i in s.member_ids]
        verdicts = await _verdicts(session, member_ids)
        in_scope = set(
            (
                await session.scalars(
                    text("SELECT id FROM jobs WHERE id = ANY(cast(:ids AS integer[])) AND in_scope"),
                    {"ids": member_ids},
                )
            ).all()
        ) if member_ids else set()
        pending = await session.scalar(
            text(
                """
                SELECT count(*) FROM job_lineage_link
                 WHERE status = 'pending' AND confidence = 'suspected'
                   AND job_id = ANY(cast(:ids AS integer[]))
                   AND prior_job_id = ANY(cast(:ids AS integer[]))
                """
            ),
            {"ids": member_ids},
        ) if member_ids else 0

    set_of = {i: n for n, s in enumerate(sets) for i in s.member_ids}
    labelled = [v for v in verdicts if v.a in set_of and set_of[v.a] == set_of.get(v.b)]

    by_id = {p.id: p for p in postings}
    leaks: list[str] = []
    next_id = -1_000_000
    for place_set in sets:
        member = by_id[place_set.member_ids[0]]
        group = [by_id[i] for i in place_set.member_ids]
        same_place, *keep_out = controls_for(member, next_id)
        next_id += 10
        formed, _ = form_place_sets(group + [same_place])
        joined = [s for s in formed if same_place.id in s.member_ids]
        if not joined or joined[0].relations.get(same_place.id) != "relisted":
            leaks.append(f"{place_set.company} {place_set.title!r}: same-place copy not relisted")
        for control in keep_out:
            formed, _ = form_place_sets(group + [control])
            if any(control.id in s.member_ids for s in formed):
                leaks.append(f"{place_set.company} {place_set.title!r}: control {control.title!r}")

    return {
        "sets": sets,
        "skipped": Counter(s.reason for s in skipped),
        "labelled": labelled,
        "in_scope": in_scope,
        "pending": pending,
        "leaks": leaks,
    }


def render(m: dict, limit: int) -> int:
    sets = m["sets"]
    members = sum(len(s.member_ids) for s in sets)
    print(f"place sets: {len(sets)} over {members} open postings ({members - len(sets)} rows a person need not read)")
    in_scope_sets = [s for s in sets if any(i in m["in_scope"] for i in s.member_ids)]
    print(f"  on the Board (any member in scope): {len(in_scope_sets)} sets")
    print(f"  pending duplicate proposals between members (withdrawn by the pass): {m['pending']}")
    for reason, n in m["skipped"].most_common():
        print(f"  not a set, {reason}: {n} groups")
    by_company = Counter(s.company for s in sets)
    print("  by company: " + ", ".join(f"{c} {n}" for c, n in by_company.most_common(12)))
    for s in sorted(sets, key=lambda s: -len(s.member_ids))[:limit]:
        print(f"    {s.company:<14} {len(s.member_ids):>2}  {s.title[:60]}  [{', '.join(s.places[:4])}{'...' if len(s.places) > 4 else ''}]")

    agree = [v for v in m["labelled"] if v.outcome == "duplicate" and v.status == "confirmed"]
    disagree = [v for v in m["labelled"] if v.outcome == "different"]
    collide = [v for v in m["labelled"] if v.outcome == "twin" or (v.kind == "twin" and v.status == "confirmed")]
    print(f"\nverdicts inside a set: {len(m['labelled'])} (agree {len(agree)}, disagree {len(disagree)}, related-roles collisions {len(collide)})")
    for v in collide:
        print(f"  collision: {v.kind} link {v.id} ({v.a}, {v.b}) decided {v.outcome or v.status}; the pass leaves this group alone")
    relisted = sum(int(s.evidence.get("relisted", 0)) for s in sets)
    print(f"  postings listed again at a place a set already holds: {relisted}")
    print(f"controls: {3 * len(sets)} altered copies, {len(m['leaks'])} wrong")
    for leak in m["leaks"][:limit]:
        print(f"  LEAK {leak}")

    if not sets:
        print("UNMEASURED: no set formed")
        return 3
    if disagree or m["leaks"]:
        print("FAIL")
        return 1
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", type=int, default=10, help="largest sets to print")
    args = parser.parse_args()
    return render(asyncio.run(measure()), args.list)


if __name__ == "__main__":
    sys.exit(main())
