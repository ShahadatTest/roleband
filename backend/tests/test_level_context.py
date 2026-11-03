from dataclasses import replace

import pytest

from tracker.analytics.level_context import extract_context, validate_context

ROUTES = ("This role is open at Senior, Staff, or Principal level.\n"
          "Senior:\nYears of Experience: 5+\nOwn architecture across teams.\n"
          "Staff:\nYears of Experience: 7+\n"
          "Principal:\nYears of Experience: 10+\n"
          "Benefits:\nYears of Experience: 20+\n")


def test_level_routes_keep_separate_heading_and_years_without_a_universal_requirement():
    profile = extract_context(ROUTES)
    assert [r.years for r in profile.experience_routes] == [(5,), (7,), (10,)]
    assert [r.heading.quote for r in profile.experience_routes] == ["Senior:", "Staff:", "Principal:"]
    assert all(r.availability.quote.startswith("This role is open") for r in profile.experience_routes)
    assert all(r.alternatives is True for r in profile.experience_routes)
    assert all(profile.features[k] is None for k in ("required_years", "preferred_years", "unspecified_years", "architecture"))
    for route in profile.experience_routes:
        for span in (route.heading, route.availability, route.statement):
            assert ROUTES[span.start:span.end] == span.quote
    validate_context(profile, ROUTES)


def test_route_with_missing_years_stays_missing_and_cannot_borrow_another_route():
    text = ROUTES.replace("Years of Experience: 7+\n", "")
    profile = extract_context(text)
    assert [r.years for r in profile.experience_routes] == [(5,), None, (10,)]
    assert profile.experience_routes[1].statement is None
    forged = replace(profile.experience_routes[1], years=(5,), statement=profile.experience_routes[0].statement)
    with pytest.raises(ValueError, match="route"):
        validate_context(replace(profile, experience_routes=(profile.experience_routes[0], forged, profile.experience_routes[2])), text)


def test_masked_route_identity_uses_source_positions_and_never_restores_labels():
    from scripts.bench_level_context import build_context_rows

    rows = [{"id": 1, "company": "acme", "description_text": ROUTES, "family": "software_eng",
             "track": "technical", "disclosed_base_min": 100000, "disclosed_base_max": 200000}]
    routes = build_context_rows(rows, [1], mask="hard")["cases"][0]["profile"]["experience_routes"]
    assert [r["years"] for r in routes] == [(5,), (7,), (10,)]
    assert len({r["heading"]["start"] for r in routes}) == 3
    assert all(r["heading"]["quote"] == "[withheld]:" for r in routes)


@pytest.mark.parametrize("text", [
    ROUTES.replace("This role is open at Senior, Staff, or Principal level.", "About our team"),
    "This role is open at Senior or Staff level.\nBenefits:\nSenior:\nYears of Experience: 5+\nStaff:\nYears of Experience: 7+",
    "This role is open at Senior or Staff level.\nPython:\nYears of Experience: 5+\nJava:\nYears of Experience: 7+",
])
def test_routes_require_explicit_availability_and_matching_headers_outside_boilerplate(text):
    assert extract_context(text).experience_routes == ()


def test_duplicate_section_keys_do_not_merge_routes_or_accept_swapped_headers():
    sections = [{"key": "description", "content": ROUTES}, {"key": "description", "content": ROUTES}]
    profile = extract_context(None, sections=sections)
    assert [r.heading.section_index for r in profile.experience_routes] == [0, 0, 0, 1, 1, 1]
    forged = replace(profile.experience_routes[0], heading=profile.experience_routes[3].heading)
    with pytest.raises(ValueError, match="route"):
        validate_context(replace(profile, experience_routes=(forged,) + profile.experience_routes[1:]), None, sections=sections)


def test_route_omission_changed_years_and_universal_promotion_are_rejected():
    from tracker.analytics.level_context import FeatureEvidence

    profile = extract_context(ROUTES)
    first = profile.experience_routes[0]
    for routes in (profile.experience_routes[1:],
                   (replace(first, years=(10,)),) + profile.experience_routes[1:],
                   (replace(first, availability=replace(first.availability, quote="Open at any level")),) + profile.experience_routes[1:]):
        with pytest.raises(ValueError, match="route"):
            validate_context(replace(profile, experience_routes=routes), ROUTES)
    claim = FeatureEvidence("required_years", (5,), "required", False, first.statement)
    with pytest.raises(ValueError, match="route"):
        validate_context(replace(profile, features=profile.features | {"required_years": (claim,)}), ROUTES)
    with pytest.raises(ValueError, match="source"):
        validate_context(profile, ROUTES.replace("5+", "6+"))


def test_route_fields_do_not_reinterpret_degree_routes_or_conjunctive_years():
    text = ROUTES.replace("Years of Experience: 7+", "Years of Experience: 7+ preferred")
    assert extract_context(text).experience_routes[1].years is None
    plain = "Required Qualifications:\n5+ years of engineering, including 2+ years managing people."
    profile = extract_context(plain)
    assert not profile.experience_routes
    assert evidence(profile, "required_years")[0].value == (5, 2)
    assert evidence(profile, "required_years")[0].alternatives is False


def evidence(profile, feature):
    return profile.features[feature] or ()


def test_required_and_preferred_years_are_distinct_and_quote_exact_source():
    text = "Required Qualifications:\n5+ years of software engineering experience.\nPreferred Qualifications:\n10+ years of distributed systems experience."
    result = extract_context(text)
    assert evidence(result, "required_years")[0].value == (5,)
    assert evidence(result, "preferred_years")[0].value == (10,)
    assert result.features["people_management"] is None
    validate_context(result, text)
    for rows in result.features.values():
        for item in rows or ():
            assert text[item.span.start:item.span.end] == item.span.quote


def test_sentence_preference_overrides_required_heading_without_losing_required_clause():
    result = extract_context("Required Qualifications:\n3+ years of engineering experience; 8+ years is preferred.")
    assert evidence(result, "required_years")[0].value == (3,)
    assert evidence(result, "preferred_years")[0].value == (8,)


def test_alternative_degree_routes_are_not_collapsed_into_a_single_minimum():
    text = "Required Qualifications:\nBachelor's AND 5+ years OR Master's AND 3+ years OR Doctorate AND 1+ year."
    entry = evidence(extract_context(text), "required_years")[0]
    assert entry.value == (5, 3, 1)
    assert entry.alternatives is True


@pytest.mark.parametrize("text", [
    "About Us:\nWe have served customers for 20 years.",
    "Benefits:\nLeadership development and autonomy for every employee.",
    "Responsibilities:\nOur team owns architecture across the organization.",
    "About the Team:\nWe manage a team of 20 engineers and set company-wide architecture.",
    "Minimum Qualifications:\nExperience managing a team of 5 engineers is preferred.",
    "Responsibilities:\nYou will not manage a team of engineers or own architecture.",
])
def test_boilerplate_aspirations_and_negated_work_cannot_become_role_scope(text):
    profile = extract_context(text)
    assert all(profile.features[key] is None for key in (
        "autonomy", "ownership_breadth", "architecture", "people_management", "organizational_impact",
    ))


def test_positive_role_scope_has_exact_evidence_and_never_infers_a_level():
    text = ("Responsibilities:\nWork independently with minimal supervision.\n"
            "Own the payments service and drive architecture across multiple teams.\n"
            "Manage a team of 5 engineers, including hiring and performance reviews.\n"
            "Set organization-wide technical strategy.")
    profile = extract_context(text)
    for feature in ("autonomy", "ownership_breadth", "architecture", "people_management", "organizational_impact"):
        assert evidence(profile, feature)
    validate_context(profile, text)
    assert not hasattr(profile, "band")


def test_project_and_vendor_management_are_not_people_management():
    profile = extract_context("Responsibilities:\nManage vendor relationships and lead a complex engineering project.")
    assert profile.features["people_management"] is None


def test_required_years_are_not_invented_from_unclassified_prose():
    profile = extract_context("You bring 7 years of engineering experience.")
    assert profile.features["required_years"] is None
    assert evidence(profile, "unspecified_years")[0].value == (7,)


def test_missing_features_remain_missing_and_cannot_be_filled_from_title_or_pay():
    profile = extract_context(None)
    assert profile.features and all(value is None for value in profile.features.values())
    assert set(profile.missing) == set(profile.features)
    validate_context(profile, None)


def test_duplicate_section_keys_round_trip_by_index_not_first_key_match():
    sections = [{"key": "responsibilities", "title": "Responsibilities", "content": "Build a user interface."},
                {"key": "responsibilities", "title": "Responsibilities", "content": "Own the storage service architecture."}]
    result = extract_context(None, sections=sections)
    entry = evidence(result, "architecture")[0]
    assert entry.span.section_index == 1
    assert entry.span.source == "description_sections"
    validate_context(result, None, sections=sections)
    with pytest.raises(ValueError, match="source|ground"):
        validate_context(result, None, sections=list(reversed(sections)))


def test_grounding_rejects_changed_source_and_fabricated_quotes():
    text = "Responsibilities:\nOwn the storage service architecture."
    result = extract_context(text)
    with pytest.raises(ValueError, match="source|ground"):
        validate_context(result, text.replace("storage", "payments"))
    claim = evidence(result, "architecture")[0]
    fabricated = replace(claim, span=replace(claim.span, quote="Own the payments service architecture."))
    broken = replace(result, features=result.features | {"architecture": (fabricated,)})
    with pytest.raises(ValueError, match="source|ground"):
        validate_context(broken, text)


def test_one_negated_sentence_does_not_erase_an_affirmative_responsibility():
    text = "Responsibilities:\nYou will not manage people. Own the storage service architecture."
    profile = extract_context(text)
    assert profile.features["people_management"] is None
    assert evidence(profile, "architecture")


def test_negated_and_preferred_years_are_not_promoted_to_required():
    profile = extract_context("Required Qualifications:\n5 years of experience is not required.\nPreferred Qualifications:\n8+ years of experience.")
    assert profile.features["required_years"] is None
    assert evidence(profile, "preferred_years")[0].value == (8,)


def test_parenthetical_sentence_abbreviation_does_not_change_grounding_offsets():
    text = "Responsibilities:\n• Own architecture (e.g. storage) across teams.\nRequired Qualifications:\nFive (5) years of engineering experience."
    profile = extract_context(text)
    assert evidence(profile, "architecture")
    assert evidence(profile, "required_years")[0].value == (5,)
    validate_context(profile, text)


def test_a_real_preferred_quote_cannot_validate_as_a_required_minimum():
    text = "Preferred Qualifications:\n8+ years of engineering experience."
    profile = extract_context(text)
    preferred = evidence(profile, "preferred_years")[0]
    forged = replace(preferred, feature="required_years", modality="required")
    with pytest.raises(ValueError, match="modality|source"):
        validate_context(replace(profile, features=profile.features | {"required_years": (forged,)}), text)


def test_company_experience_and_architecture_mentions_do_not_invent_scope():
    text = "Our company has 20+ years of experience.\nResponsibilities:\nBuild reports about architecture and manage deployment projects."
    profile = extract_context(text)
    assert all(value is None for value in profile.features.values())


def test_a_numeric_claim_cannot_validate_against_a_different_number_in_a_real_quote():
    text = "Required Qualifications:\n5+ years of engineering experience."
    profile = extract_context(text)
    forged = replace(evidence(profile, "required_years")[0], value=(99,))
    with pytest.raises(ValueError, match="years"):
        validate_context(replace(profile, features=profile.features | {"required_years": (forged,)}), text)


def test_offline_extraction_defaults_to_sealed_inputs_and_never_reads_stored_years():
    from scripts.bench_level_context import build_context_rows

    row = {"id": 1, "company": "microsoft", "family": "software_engineering", "track": "technical",
           "disclosed_base_min": 150000, "disclosed_base_max": 230000, "raw_level": "IC5",
           "description_text": "Software Engineering IC5\nResponsibilities:\nOwn the storage service architecture.",
           "required_years": 99, "level_band": "principal", "embedding": [99]}
    result = build_context_rows([row], [1], mask="hard")
    profile = result["cases"][0]["profile"]
    assert profile["features"]["required_years"] is None
    assert profile["features"]["architecture"]
    assert "IC5" not in str(profile)
    assert row["raw_level"] == "IC5"
    with pytest.raises(ValueError, match="duplicate"):
        build_context_rows([row], [1, 1], mask="hard")
    with pytest.raises(ValueError, match="absent"):
        build_context_rows([row], [2], mask="hard")


def test_context_cli_publishes_once_and_rejects_outputs_inside_a_checkout(tmp_path):
    import json

    from scripts.bench_level_context import main

    snapshot, ids, output = [tmp_path / filename for filename in ("snapshot.json", "ids.json", "out.json")]
    snapshot.write_text(json.dumps({"jobs": [{"id": 1, "company": "acme", "description_text": "Required Qualifications:\n5+ years of experience."}]}))
    ids.write_text("[1]")
    args = ["--snapshot", str(snapshot), "--ids", str(ids), "--mask", "none", "--out", str(output)]
    assert main(args) == 0
    assert json.loads(output.read_text())["coverage"]["required_years"] == 1
    with pytest.raises(FileExistsError):
        main(args)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").touch()
    with pytest.raises(ValueError, match="repository"):
        main(args[:-1] + [str(checkout / "out.json")])


def test_an_alternative_degree_without_years_is_preserved_as_an_alternative():
    text = "Required Qualifications:\n3+ years of experience as a data scientist; OR a PhD in a quantitative field."
    requirement = evidence(extract_context(text), "required_years")[0]
    assert requirement.value == (3,)
    assert requirement.alternatives is True
    assert "OR a PhD" in requirement.span.quote


def test_a_multi_level_experience_line_keeps_every_route_across_abbreviations():
    text = "Required Qualifications:\n4+ years (Engineer) / 6+ years (Sr. Engineer) / 8+ years (Staff Engineer)."
    requirement = evidence(extract_context(text), "required_years")[0]
    assert requirement.value == (4, 6, 8)
    assert requirement.alternatives is True


def test_using_design_expertise_to_verify_a_design_is_not_owning_its_architecture():
    text = ("Responsibilities:\nYou'll leverage your design and verification expertise to verify complex digital designs, "
            "with a specific focus on TPU architecture and its integration within AI systems.")
    assert extract_context(text).features["architecture"] is None


def test_owned_systems_and_features_keep_explicit_breadth_without_guessing_a_rank():
    profile = extract_context("Responsibilities:\nOwn the production systems.\nOwn AI features end-to-end.")
    assert len(evidence(profile, "ownership_breadth")) == 2
    assert profile.features["organizational_impact"] is None


def test_a_preferred_credential_does_not_change_the_required_experience_modality():
    text = "Required Qualifications:\nBachelor's degree (CPA preferred) with 8+ years of accounting experience at a SaaS or technology company."
    profile = extract_context(text)
    claim = evidence(profile, "required_years")[0]
    assert claim.value == (8,)
    assert claim.alternatives is False
    assert profile.features["preferred_years"] is None


def test_ownership_does_not_reach_across_a_different_action_into_another_object():
    text = "Responsibilities:\nOwn the lifecycle, and shape the platform."
    assert extract_context(text).features["ownership_breadth"] is None


@pytest.mark.parametrize("text", [
    "Own the metrics, dashboards, and experiments that inform product strategy.",
    "You'll own your work from discovery through delivery, and you'll make impactful product decisions.",
])
def test_owned_object_does_not_extend_into_a_relative_or_separate_clause(text):
    assert extract_context("Responsibilities:\n" + text).features["ownership_breadth"] is None


def test_overall_and_specialized_years_are_conjunctive_not_alternatives():
    text = "Required Qualifications:\n5+ years in Trust & Safety or CX operations, including 2+ years managing reviewers or vendor teams."
    requirement = evidence(extract_context(text), "required_years")[0]
    assert requirement.value == (5, 2)
    assert requirement.alternatives is False


def test_typical_experience_is_preserved_without_claiming_a_required_minimum():
    profile = extract_context("Required Qualifications:\nTypically 6-8 years of product experience.")
    assert profile.features["required_years"] is None
    assert evidence(profile, "unspecified_years")[0].value == (6,)


def test_qualifications_are_experience_not_current_role_scope():
    text = "Minimum Qualifications:\nAbility to own architecture across multiple teams."
    profile = extract_context(text)
    assert profile.features["architecture"] is None
    assert profile.features["ownership_breadth"] is None
    actual = extract_context("Responsibilities:\nOwn architecture across multiple teams.")
    assert evidence(actual, "architecture")
    assert evidence(actual, "ownership_breadth")


def test_grade_masking_does_not_split_an_alternative_experience_route():
    from tracker.analytics.level_evaluation import mask_inputs

    text = "Required Qualifications:\n4+ years (Engineer) / 6+ years (Sr. Engineer) / 8+ years (Staff Engineer)."
    masked = mask_inputs({"description_text": text}, ["IC5"], hard=True)["description_text"]
    before = evidence(extract_context(text), "required_years")
    after = evidence(extract_context(masked), "required_years")
    assert len(before) == len(after) == 1
    assert before[0].value == after[0].value == (4, 6, 8)
    assert before[0].alternatives == after[0].alternatives is True


@pytest.mark.parametrize("statement", [
    "Guide architectural decisions around 3D representations and training pipelines.",
    "Establish mobile architecture patterns and shared components.",
    "Establish and improve our SIEM and monitoring architecture, including signal quality.",
    "You'll work with customers and have significant influence in defining our technical architecture.",
])
def test_explicit_architecture_decisions_are_role_duties(statement):
    profile = extract_context("Responsibilities:\n" + statement)
    assert evidence(profile, "architecture")
    validate_context(profile, "Responsibilities:\n" + statement)


@pytest.mark.parametrize("statement,feature", [
    ("You'll have the autonomy to discover problems and design solutions.", "autonomy"),
    ("You’ll have significant ownership over both the research direction and the production systems that make it real.", "ownership_breadth"),
    ("You'll have significant ownership over the systems you build.", "ownership_breadth"),
])
def test_explicit_role_possession_of_scope_in_unclassified_prose(statement, feature):
    profile = extract_context(statement)
    assert evidence(profile, feature)
    validate_context(profile, statement)


@pytest.mark.parametrize("statement", [
    "Our team will establish mobile architecture patterns.",
    "Experience guiding architectural decisions is required.",
    "Ability to establish and improve monitoring architecture.",
    "You'll have experience defining our technical architecture.",
    "You'll work with engineers who have ownership over the production systems.",
    "You'll have significant ownership over the research direction that informs production systems.",
    "You'll have significant ownership over the research direction, and build production systems.",
    "You'll not have autonomy to choose projects.",
])
def test_scope_extensions_do_not_promote_team_capability_or_unowned_objects(statement):
    result = extract_context("Responsibilities:\n" + statement)
    assert all(result.features[key] is None for key in ("autonomy", "architecture", "ownership_breadth"))


def test_explicitly_optional_experience_is_preferred_even_under_required_heading():
    text = ("Core Requirements:\nEngineering Foundation: 3+ years of experience in software engineering, "
            "with a focus on full-stack development (Python, TypeScript) preferred but not required.")
    profile = extract_context(text)
    assert profile.features["required_years"] is None
    assert evidence(profile, "preferred_years")[0].value == (3,)
    validate_context(profile, text)
    assert extract_context("Requirements:\n3+ years of experience is not required.").features["preferred_years"] is None


@pytest.mark.parametrize("statement", [
    "Develop rigorously substantiated architectural analyses comparing metadata scaling and durability tradeoffs.",
    "You'll guide observability architecture discussions during customer evaluations.",
])
def test_architecture_analysis_or_discussion_does_not_claim_architecture_decisions(statement):
    assert extract_context("Responsibilities:\n" + statement).features["architecture"] is None


def test_taking_ownership_of_a_service_remains_explicit_role_scope():
    assert evidence(extract_context("Responsibilities:\nTake ownership of the payments service."), "ownership_breadth")


def test_architectural_roadmap_is_explicit_architecture_ownership():
    text = "Responsibilities:\nOwn the architectural roadmap and delivery of the agent infrastructure."
    assert evidence(extract_context(text), "architecture")


@pytest.mark.parametrize("heading,feature", [("You May Be a Good Fit If You", "unspecified_years"),
                                              ("Required Qualifications", "required_years")])
def test_preference_for_a_different_skill_does_not_change_the_years_modality(heading, feature):
    text = f"{heading}:\nHave 6+ years of experience in compensation - leadership experience is a plus"
    profile = extract_context(text)
    assert evidence(profile, feature)[0].value == (6,)
    assert profile.features["preferred_years"] is None
    assert evidence(extract_context("Qualifications:\n6+ years of experience is a plus."), "preferred_years")[0].value == (6,)


def test_owned_projects_do_not_reach_through_a_from_to_phrase_into_a_feature():
    text = "You'll join a small design team and own projects from the kernel of an idea to a feature customers use every day."
    assert extract_context(text).features["ownership_breadth"] is None
    assert evidence(extract_context("Responsibilities:\nOwn features from discovery to production."), "ownership_breadth")


def test_inline_responsibility_label_and_hardware_component_keep_direct_ownership():
    for text in ("Responsibilities:\nExtensibility: Own the systems teams use to extend the platform.",
                 "Responsibilities:\nOwn a subassembly and its parts through design and validation."):
        profile = extract_context(text)
        assert evidence(profile, "ownership_breadth")
        validate_context(profile, text)
    assert extract_context("Qualifications:\nExperience: Own the systems teams use.").features["ownership_breadth"] is None
    assert extract_context("Responsibilities:\nTeam: Our team owns the systems.").features["ownership_breadth"] is None


def test_timeline_prefixed_role_statement_is_a_duty_even_after_qualifications():
    text = "Qualifications:\n3+ years of experience.\nMonth 2 - you will independently own an implementation from kickoff to go-live"
    assert evidence(extract_context(text), "autonomy")
    assert extract_context("Qualifications:\nMonth 2 - you will have experience working independently.").features["autonomy"] is None


def test_participial_architecture_duty_is_not_prior_experience():
    assert evidence(extract_context("Responsibilities:\nPartnering on determining the architecture and stack for our AI capabilities"), "architecture")
    assert extract_context("Qualifications:\nExperience partnering on determining the architecture.").features["architecture"] is None


def test_nominal_architecture_ownership_retains_heading_as_separate_grounding():
    text = "What You'll Own:\nRuggedization architecture across the laser source and supporting subsystems"
    profile = extract_context(text)
    claim = evidence(profile, "architecture")[0]
    assert claim.context.quote == "What You'll Own:"
    assert text[claim.context.start:claim.context.end] == claim.context.quote
    validate_context(profile, text)
    forged = replace(claim, context=replace(claim.context, start=0, end=5, quote="What "))
    with pytest.raises(ValueError):
        validate_context(replace(profile, features=profile.features | {"architecture": (forged,)}), text)
    with pytest.raises(ValueError):
        validate_context(replace(profile, features=profile.features | {
            "architecture": (replace(claim, context=None),),
        }), text)
    for heading in ("About the Team", "Qualifications", "What You'll Do"):
        assert extract_context(heading + ":\nRuggedization architecture across the laser source").features["architecture"] is None
    assert extract_context("What You'll Own:\nQualifications:\nKnowledge of architecture.").features["architecture"] is None


def test_new_graduate_exception_keeps_the_years_and_the_qualitative_route():
    text = "Minimum Qualifications:\n1-4 years of mechanical design experience (exceptional new grads with strong projects are welcome to apply)"
    profile = extract_context(text)
    claim = evidence(profile, "required_years")[0]
    assert claim.value == (1,)
    assert claim.alternatives is True
    assert "welcome to apply" in claim.span.quote
    validate_context(profile, text)
    forged = replace(claim, alternatives=False)
    with pytest.raises(ValueError):
        validate_context(replace(profile, features=profile.features | {"required_years": (forged,)}), text)
    assert all(v is None for v in extract_context("How to Apply:\n3 years of experience; new grads are welcome to apply.").features.values())


def test_ownership_heading_proof_cannot_be_replayed_from_another_section():
    sections = [{"key": "role", "content": "What You'll Own:\nStorage architecture."},
                {"key": "role", "content": "What You'll Own:\nMonitoring architecture."}]
    profile = extract_context(None, sections=sections)
    claims = evidence(profile, "architecture")
    assert len(claims) == 2
    assert claims[1].context.section_index == 1
    forged = replace(claims[1], context=claims[0].context)
    with pytest.raises(ValueError):
        validate_context(replace(profile, features=profile.features | {"architecture": (forged,)}), None, sections=sections)


def test_grounding_rejects_a_source_excerpt_that_hides_a_preference():
    text = "Required Qualifications:\n5+ years of experience is preferred."
    profile = extract_context(text)
    claim = evidence(profile, "preferred_years")[0]
    quote = "5+ years of experience"
    forged = replace(claim, feature="required_years", modality="required",
                     span=replace(claim.span, end=claim.span.start + len(quote), quote=quote))
    with pytest.raises(ValueError):
        validate_context(replace(profile, features=profile.features | {"required_years": (forged,)}), text)


def test_hyphenated_end_to_end_does_not_hide_the_owned_product():
    text = "Responsibilities:\nOwn the end-to-end product development, collaborating with the designer."
    assert evidence(extract_context(text), "ownership_breadth")


@pytest.mark.parametrize("heading", ["About Us", "About the Team", "Benefits", "How to Apply", "Equal Opportunity"])
def test_whole_quotes_from_excluded_sections_cannot_validate_as_experience(heading):
    from tracker.analytics.level_context import FeatureEvidence, SourceSpan

    quote = "Our engineers bring 5+ years of experience."
    text = heading + ":\n" + quote
    profile = extract_context(text)
    assert all(value is None for value in profile.features.values())
    start = text.index(quote)
    claim = FeatureEvidence("unspecified_years", (5,), "unspecified", False,
                            SourceSpan("description_text", None, start, start + len(quote), quote))
    with pytest.raises(ValueError):
        validate_context(replace(profile, features=profile.features | {"unspecified_years": (claim,)}), text)


@pytest.mark.parametrize("text", [
    "You will partner closely with teams across the organization to resolve local gaps.",
    "Drive collaboration and attend organization-wide meetings.",
    "Lead company-wide collaboration sessions.",
])
def test_collaboration_across_the_organization_is_not_accountability_for_its_outcomes(text):
    assert extract_context("Responsibilities:\n" + text).features["organizational_impact"] is None


@pytest.mark.parametrize("text", [
    "Set organization-wide technical strategy.",
    "Own technical standards across the organization.",
    "Lead company-wide security initiatives.",
])
def test_explicit_organization_wide_outcomes_retain_their_direct_duty(text):
    assert evidence(extract_context("Responsibilities:\n" + text), "organizational_impact")


@pytest.mark.parametrize("text", [
    "Own product activation and usage for the account.",
    "Own platform adoption for customers using the system.",
    "Own feature usage and activation metrics.",
])
def test_customer_adoption_is_not_ownership_of_the_underlying_component(text):
    assert extract_context("Responsibilities:\n" + text).features["ownership_breadth"] is None


def test_a_separate_owned_component_survives_an_adoption_clause():
    profile = extract_context("Responsibilities:\nOwn product activation and own the payments service.")
    assert evidence(profile, "ownership_breadth")
    assert evidence(extract_context("Responsibilities:\nOwn product areas end-to-end."), "ownership_breadth")


def test_unrelated_erp_expertise_does_not_negate_the_years_requirement():
    text = "Minimum Qualifications:\n2+ years in engineering or technical program management - ERP experience not required (though it is a plus)"
    profile = extract_context(text)
    assert evidence(profile, "required_years")[0].value == (2,)
    assert profile.features["preferred_years"] is None
    assert evidence(profile, "required_years")[0].span.quote == "2+ years in engineering or technical program management"
    validate_context(profile, text)


@pytest.mark.parametrize("text", [
    "2+ years of engineering experience is not required.",
    "2+ years - engineering experience not required.",
    "2+ years in engineering - engineering experience not required.",
    "2+ years in ERP - ERP experience not required.",
])
def test_a_negation_of_the_same_experience_cannot_be_split_away(text):
    assert extract_context("Minimum Qualifications:\n" + text).features["required_years"] is None


@pytest.mark.parametrize("text", [
    "Architect and optimize our reinforcement learning infrastructure.",
    "Architect key parts of the system.",
    "Close open architectural decisions rather than leaving them unresolved.",
    "You're the first dedicated data hire: you own the architecture and tooling choices.",
])
def test_direct_architecture_actions_and_an_explicit_you_owned_clause_are_duties(text):
    assert evidence(extract_context("Responsibilities:\n" + text), "architecture")


@pytest.mark.parametrize("text", [
    "Work with an architect to document our infrastructure.",
    "Experience architecting distributed systems.",
    "Our team owns the architecture.",
    "Familiarity with architectural decisions.",
])
def test_architect_as_a_collaborator_or_prior_experience_does_not_become_scope(text):
    assert extract_context("Responsibilities:\n" + text).features["architecture"] is None


def test_direct_decision_authority_remains_a_duty_under_a_qualification_heading():
    text = "Qualifications:\nYou make scoping and trade-off calls on your own, without waiting for sign-off."
    assert evidence(extract_context(text), "autonomy")
    assert extract_context("Qualifications:\nExperience making scoping calls on your own, without waiting for sign-off.").features["autonomy"] is None


def test_a_preference_for_the_same_experience_keeps_its_scope():
    profile = extract_context("Required Qualifications:\n6+ years of leadership - leadership experience preferred")
    assert profile.features["required_years"] is None
    assert evidence(profile, "preferred_years")[0].value == (6,)


@pytest.mark.parametrize("text", [
    "Lead organization-wide meetings about technical strategy.",
    "Close the ticket about architecture.",
])
def test_meetings_and_ticket_closure_do_not_imply_responsibility_for_the_topic(text):
    profile = extract_context("Responsibilities:\n" + text)
    assert profile.features["organizational_impact"] is None
    assert profile.features["architecture"] is None


@pytest.mark.parametrize("text", [
    "Partner with engineering: you'll embed with a pod of team members who own a specific product initiative.",
    "You'll coordinate with engineers who own the storage service architecture.",
])
def test_responsibilities_owned_by_other_people_are_not_the_applicants_scope(text):
    profile = extract_context("Responsibilities:\n" + text)
    assert profile.features["ownership_breadth"] is None
    assert profile.features["architecture"] is None


def test_an_applicant_can_coordinate_with_others_and_still_own_a_service():
    text = "Responsibilities:\nYou'll coordinate with engineers and own the storage service architecture."
    profile = extract_context(text)
    assert evidence(profile, "ownership_breadth")
    assert evidence(profile, "architecture")
