"""Skill extraction behavior contract (quality gate).

Covers the regression families: benefits/comp/EEO/recruiting copy must
never ground a skill; ambiguous aliases (React/ReAct, Ray, Spark, C/Go/R,
transformer) resolve only with context; team/company mentions score 0; negation
rejects requirements; parent/child concepts dedupe; qualifications extract as
structured non-skill rows; every quote grounds (exact substring + offsets).
"""

from __future__ import annotations

from tracker.skills.catalog import get_catalog
from tracker.skills.extract import extract_job, requirements_content_hash
from tracker.skills.segment import segment_job

CAT = get_catalog()


def _sections(**by_key) -> list[dict]:
    """Build description_sections from key=content pairs."""
    titles = {
        "minimum_qualifications": "Minimum Qualifications",
        "preferred_qualifications": "Preferred Qualifications",
        "responsibilities": "What you'll do",
        "benefits": "Benefits",
        "about": "About the team",
        "description": "Description",
    }
    return [
        {"key": k, "title": titles.get(k, k), "content": v} for k, v in by_key.items()
    ]


def _slugs(result, min_band=("core", "important", "supporting")) -> set[str]:
    return {s["slug"] for s in result.skills if s["importance_band"] in min_band}


# --------------------------------------------------------------- exclusion contexts


def test_apple_medical_coverage_is_not_healthcare():
    result = extract_job(
        CAT,
        "Senior Software Engineer",
        _sections(
            benefits=(
                "You will receive medical coverage, dental coverage, and vision insurance.\n"
                "Employees can receive commission payments in eligible roles."
            )
        ),
    )
    assert "healthcare" not in _slugs(result, min_band=("core", "important", "supporting", "context"))
    assert "payments" not in _slugs(result, min_band=("core", "important", "supporting", "context"))


def test_amazon_pay_inside_preferred_qualifications_is_rejected():
    # Heading is a prior, not authority: Amazon publishes comp inside
    # preferred_qualifications. The unit-level benefit override must win.
    result = extract_job(
        CAT,
        "Software Development Manager",
        _sections(
            preferred_qualifications=(
                "Experience with AWS services in production.\n"
                "Our compensation reflects the cost of labor. A sign-on payment and restricted stock "
                "units may be provided as part of the compensation package, in addition to a full range "
                "of medical, financial, and/or other benefits."
            )
        ),
    )
    slugs = _slugs(result)
    assert "aws" in slugs  # the real requirement stays
    all_slugs = _slugs(result, min_band=("core", "important", "supporting", "context"))
    assert "payments" not in all_slugs  # sign-on payment is comp copy, not fintech
    assert "healthcare" not in all_slugs  # medical benefits, not the domain


def test_recruiting_copy_is_not_hiring_competency():
    result = extract_job(
        CAT,
        "Engineering Manager",
        _sections(
            description="For more information, contact your recruiting partner during the hiring process."
        ),
    )
    assert "hiring" not in _slugs(result, min_band=("core", "important", "supporting", "context"))


def test_hiring_as_role_behaviour_still_counts():
    result = extract_job(
        CAT,
        "Engineering Manager",
        _sections(responsibilities="You will own hiring and team building for your organization."),
    )
    assert "hiring" in _slugs(result)


def test_netflix_eeo_medical_condition_is_not_healthcare():
    result = extract_job(
        CAT,
        "Senior Engineer",
        _sections(
            description=(
                "We consider qualified applicants without regard to race, religion, "
                "disability, or medical condition."
            )
        ),
    )
    assert "healthcare" not in _slugs(result, min_band=("core", "important", "supporting", "context"))


def test_real_industry_requirements_still_extract():
    # Prove the benefit/EEO exclusions above are not vacuous: genuine industry
    # experience for the same verticals must extract.
    result = extract_job(
        CAT,
        "Payments Engineer",
        _sections(
            minimum_qualifications="Experience building payments infrastructure at scale.",
            preferred_qualifications="Experience in the healthcare or clinical data industry.",
        ),
    )
    slugs = _slugs(result)
    assert "payments" in slugs
    assert "healthcare" in slugs


def _facet_of(result, slug):
    rows = [s for s in result.skills if s["slug"] == slug]
    return rows[0]["facet"] if rows else None


def test_verticals_carry_industry_facet_not_skill():
    # Industries must never be emitted as a skill facet — the core taxonomy fix.
    result = extract_job(
        CAT,
        "Staff Engineer",
        _sections(
            minimum_qualifications=(
                "Experience in the payments industry.\n"
                "Background in the healthcare sector.\n"
                "Advertising industry experience preferred.\n"
                "Built search ranking and recommendation systems."
            ),
        ),
    )
    assert _facet_of(result, "payments") == "industry"
    assert _facet_of(result, "healthcare") == "industry"
    assert _facet_of(result, "ads") == "industry"
    # Applied ML problem-domains stay skills, not industries.
    assert _facet_of(result, "search_ranking") == "professional_skill"
    assert _facet_of(result, "recommendation") == "professional_skill"


def test_seeded_vertical_extracts_when_candidate_facing_only():
    positive = extract_job(
        CAT,
        "Software Engineer",
        _sections(minimum_qualifications="5+ years in the gaming industry building live services."),
    )
    assert _facet_of(positive, "gaming") == "industry"

    # Employer marketing about the sector must not become a candidate requirement.
    marketing = extract_job(
        CAT,
        "Software Engineer",
        _sections(about="We are the world's largest gaming company with millions of players."),
    )
    rows = [s for s in marketing.skills if s["slug"] == "gaming"]
    assert not rows or rows[0]["importance_band"] == "context"


# --------------------------------------------------------------- ambiguous aliases


def test_react_framework_vs_react_verb_vs_ReAct():
    framework = extract_job(
        CAT, "Frontend Engineer",
        _sections(minimum_qualifications="Experience building applications with React and TypeScript."),
    )
    assert "react" in _slugs(framework)

    verb = extract_job(
        CAT, "Operations Engineer",
        _sections(responsibilities="React quickly to production incidents."),
    )
    assert "react" not in _slugs(verb, min_band=("core", "important", "supporting", "context"))

    react_prompting = extract_job(
        CAT, "Research Engineer",
        _sections(minimum_qualifications="Experience with ReAct reasoning loops for agents."),
    )
    assert "react" not in _slugs(react_prompting, min_band=("core", "important", "supporting", "context"))


def test_ray_framework_vs_ray_tracing():
    framework = extract_job(
        CAT, "ML Infrastructure Engineer",
        _sections(minimum_qualifications="Experience with distributed Python workloads on Ray clusters."),
    )
    assert "ray" in _slugs(framework)

    graphics = extract_job(
        CAT, "Graphics Engineer",
        _sections(minimum_qualifications="Deep experience with ray tracing and GPU rendering pipelines."),
    )
    assert "ray" not in _slugs(graphics, min_band=("core", "important", "supporting", "context"))


def test_spark_engine_vs_spark_verb():
    engine = extract_job(
        CAT, "Data Engineer",
        _sections(minimum_qualifications="5+ years building pipelines with Apache Spark."),
    )
    assert "spark" in _slugs(engine)

    verb = extract_job(
        CAT, "Product Manager",
        _sections(description="You will spark creativity across the organization. Spark your curiosity."),
    )
    assert "spark" not in _slugs(verb, min_band=("core", "important", "supporting", "context"))


def test_ml_transformer_vs_electrical_transformer():
    ml = extract_job(
        CAT, "Research Engineer",
        _sections(minimum_qualifications="Deep understanding of transformer architectures for language models."),
    )
    assert "transformers" in _slugs(ml)

    electrical = extract_job(
        CAT, "Electrical Engineer",
        _sections(minimum_qualifications="Experience with power transformer testing and high-voltage systems."),
    )
    assert "transformers" not in _slugs(electrical, min_band=("core", "important", "supporting", "context"))


def test_bare_c_go_r_need_programming_context():
    listed = extract_job(
        CAT, "Systems Engineer",
        _sections(minimum_qualifications="Proficiency in one of: C, C++, Go, Rust, or Python. Experience with R for data analysis."),
    )
    slugs = _slugs(listed)
    assert {"c_lang", "golang", "r_lang", "cpp", "rust", "python"} <= slugs

    prose = extract_job(
        CAT, "Program Manager",
        _sections(description="Plan C is to go to the R&D review board."),
    )
    bad = _slugs(prose, min_band=("core", "important", "supporting", "context"))
    assert "c_lang" not in bad and "golang" not in bad and "r_lang" not in bad


def test_csharp_dotnet_aspnet_distinct():
    result = extract_job(
        CAT, "Software Engineer",
        _sections(minimum_qualifications="Experience with C# and ASP.NET services."),
    )
    slugs = _slugs(result)
    assert "csharp" in slugs
    assert "aspnet" in slugs
    # ASP.NET (child) suppresses bare .NET (parent) in the same unit.
    assert "dotnet" not in slugs


# --------------------------------------------------------------- actor / negation


def test_team_uses_vs_you_have():
    team_only = extract_job(
        CAT, "Backend Engineer",
        _sections(about="The team uses AWS for all deployments."),
    )
    team_aws = [s for s in team_only.skills if s["slug"] == "aws"]
    assert team_aws and team_aws[0]["importance_band"] == "context"  # score 0, audit-only

    candidate = extract_job(
        CAT, "Backend Engineer",
        _sections(minimum_qualifications="You have hands-on AWS experience."),
    )
    cand_aws = [s for s in candidate.skills if s["slug"] == "aws"]
    assert cand_aws and cand_aws[0]["importance_band"] in ("core", "important")


def test_negated_requirement_rejected():
    result = extract_job(
        CAT, "ML Engineer",
        _sections(minimum_qualifications="Kubernetes experience is not required for this role."),
    )
    assert "kubernetes" not in _slugs(result, min_band=("core", "important", "supporting", "context"))


def test_company_marketing_aws_is_context_only():
    result = extract_job(
        CAT, "Account Manager",
        _sections(about="Our AWS organization is the leading cloud provider with millions of customers."),
    )
    rows = [s for s in result.skills if s["slug"] == "aws"]
    assert not rows or rows[0]["importance_band"] == "context"


# --------------------------------------------------------------- scoring / dedupe


def test_minimum_beats_preferred_beats_responsibility():
    result = extract_job(
        CAT, "Engineer",
        _sections(
            minimum_qualifications="Strong Python experience.",
            preferred_qualifications="Experience with Terraform.",
            responsibilities="You will build services with Kafka.",
        ),
    )
    by = {s["slug"]: s for s in result.skills}
    assert by["python"]["importance_band"] == "core"
    assert by["python"]["modality"] == "required"
    assert by["terraform"]["modality"] == "preferred"
    assert by["kafka"]["modality"] == "used_in_role"
    assert by["python"]["importance_score"] > by["terraform"]["importance_score"] > by["kafka"]["importance_score"]


def test_independent_evidence_bonus_not_mention_count():
    once = extract_job(
        CAT, "Engineer",
        _sections(minimum_qualifications="Python experience. Python and more Python daily."),
    )
    twice = extract_job(
        CAT, "Engineer",
        _sections(
            minimum_qualifications="Python experience required.",
            responsibilities="You will write Python services.",
        ),
    )
    one = [s for s in once.skills if s["slug"] == "python"][0]
    two = [s for s in twice.skills if s["slug"] == "python"][0]
    # Repeating a word in one unit is not more evidence; a second unit is.
    assert two["evidence_count"] == 2
    assert two["importance_score"] > one["importance_score"]


def test_parent_child_dedupe_s3_and_pyspark():
    result = extract_job(
        CAT, "Data Engineer",
        _sections(minimum_qualifications="Experience with AWS S3 and PySpark, plus Spark tuning."),
    )
    slugs = _slugs(result)
    assert "aws_s3" in slugs and "pyspark" in slugs
    assert "aws" not in slugs  # parent suppressed in the same unit
    assert "spark" not in slugs  # parent suppressed even as a separate token


def test_proficiency_cues():
    result = extract_job(
        CAT, "Engineer",
        _sections(
            minimum_qualifications="Deep expertise in Kubernetes.",
            preferred_qualifications="Familiarity with Terraform is a plus.",
        ),
    )
    by = {s["slug"]: s for s in result.skills}
    assert by["kubernetes"]["proficiency"] == "expert"
    assert by["terraform"]["proficiency"] == "familiarity"


# --------------------------------------------------------------- grounding


def test_every_evidence_quote_grounds_to_stored_text():
    sections = _sections(
        minimum_qualifications="8+ years with Python.\nExperience with AWS.",
        responsibilities="You will build Kafka pipelines.",
    )
    result = extract_job(CAT, "Engineer", sections)
    content_by_key = {s["key"]: s["content"] for s in sections}
    assert result.skills
    for skill in result.skills:
        assert skill["evidence"], "no association without evidence"
        for e in skill["evidence"]:
            source = content_by_key[e["section_key"]]
            assert source[e["start_offset"]:e["end_offset"]] == e["quote"]


def test_title_mention_is_low_weight_grounded_evidence():
    result = extract_job(CAT, "Machine Learning Engineer", [])
    rows = [s for s in result.skills if s["slug"] == "machine_learning"]
    assert rows
    assert rows[0]["importance_band"] == "context"
    assert rows[0]["evidence"][0]["section_key"] is None


# --------------------------------------------------------------- qualifications


def test_qualifications_extracted_as_structured_rows_not_skills():
    result = extract_job(
        CAT, "Senior Engineer",
        _sections(
            minimum_qualifications=(
                "8+ years of software engineering experience.\n"
                "BS in Computer Science or equivalent experience.\n"
                "Active security clearance required."
            ),
            preferred_qualifications="PMP certification is a plus.",
        ),
    )
    kinds = {q["kind"]: q for q in result.qualifications}
    assert kinds["experience"]["value"] == {"years": 8.0, "years_stated": [8.0]}
    assert kinds["experience"]["modality"] == "required"
    assert "education" in kinds
    assert "clearance" in kinds
    assert kinds["credential"]["modality"] == "preferred"
    for q in result.qualifications:
        assert q["quote"]


def test_content_hash_tracks_title_and_sections():
    s1 = _sections(minimum_qualifications="Python.")
    assert requirements_content_hash("A", s1) == requirements_content_hash("A", s1)
    assert requirements_content_hash("A", s1) != requirements_content_hash("B", s1)
    assert requirements_content_hash("A", s1) != requirements_content_hash(
        "A", _sections(minimum_qualifications="Python and Go.")
    )


# --------------------------------------------------------------- segmentation


def test_segment_offsets_roundtrip_on_bullets_and_prose():
    content = (
        "Own the ML platform roadmap.\n"
        "  \n"
        "This is a long prose paragraph about the role. It talks about building systems. "
        "It mentions collaborating across many teams and typically runs past the bullet "
        "length threshold so it must be split into sentences. Each sentence must still "
        "round-trip its offsets exactly."
    )
    units = segment_job(None, [{"key": "responsibilities", "title": "Role", "content": content}])
    assert len(units) > 2
    for u in units:
        assert content[u.start_offset:u.end_offset] == u.text


def test_graduate_exception_does_not_turn_a_qualification_into_application_instructions():
    content = "1-4 years of mechanical design experience (exceptional new grads with strong projects are welcome to apply)"
    units = segment_job(None, [{"key": "minimum_qualifications", "content": content}])
    assert len(units) == 1
    assert units[0].aspect == "minimum"
    assert units[0].text == content
    application = segment_job(None, [{"key": "minimum_qualifications", "content": content + "; contact the recruiter to apply by Friday"}])
    assert application[0].aspect == "application"
