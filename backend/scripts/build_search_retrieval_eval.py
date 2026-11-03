"""Freeze the search-retrieval eval fixture from the live DB.

One-shot builder for `tests/fixtures/search_retrieval_eval.json`, the authored
ground truth for search retrieval. Mirrors `build_relevance_eval.py`:
hand-authored labels live here, real posting fields/text are snapshotted from
the corpus and frozen so the eval runs with production encoding seams and
cannot drift as the corpus changes.

    .venv/bin/python -m scripts.build_search_retrieval_eval          # refuses to overwrite
    .venv/bin/python -m scripts.build_search_retrieval_eval --force  # deliberate re-freeze

Re-freezing changes the benchmark and invalidates every recorded baseline: do
it deliberately and re-record in the same change (an eval that cannot fail
measures nothing).

Scope: every cohort minimum is met (exact 10, identifier 5, typo 8, structured
NL 8, semantic intent 8, no-answer 6, minimal pairs 12 directions) over 65 real
postings. What is still NOT covered is named in `cohort_todo` and must stay
there rather than being absorbed into a coverage claim.

CAVEAT: four of those 65 are `meta` postings the corpus does not hold. The
FROZEN fixture is unaffected (it snapshots the text, and no test reads the live
DB), but a re-freeze cannot resolve them, so it would quietly build a
61-posting benchmark and drop the cohorts those four carry. A re-freeze
authors replacements first.

Two authoring guards run at build time, because both mistakes are silent:
- an `exact` label is checked against a plain case/whitespace-folded title (or
  the row's URL/req_id for identifier queries). `_plain_title_key` deliberately
  does NOT import `search.policy`: labels derived from the module under test
  would make the "zero false exact" gate true by construction.
- a `semantic_intent` target is checked to be invisible to `websearch_to_tsquery`.
  `search_vector` is `to_tsvector(title || description)`, so a paraphrase that
  shares one stemmed term is found lexically and the cohort would be measuring
  the wrong half of the system.

Label model, per (query, posting):
- class in {exact, close, related, irrelevant}; unlisted postings default to
  `irrelevant` for that query (explicit, see `default_class`).
- must_not_class is DERIVED from the class (a pair must never be *over*-promoted):
  exact->[]; close->[exact]; related->[exact,close]; irrelevant->[exact,close,related].
Labels follow role-shape + mission, not surface similarity: a material one-word
difference (manager/IC, product/program, family/domain/explicit-level, org-path)
caps the class regardless of how similar the titles look.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import unicodedata
from pathlib import Path

from sqlalchemy import text

from tracker.db.session import session_scope

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "search_retrieval_eval.json"

# --- postings: (company, req_id). Real rows, verified unique + described. ----- #
# key = "{company}-{req_id}". Facts in comments are the frozen classification the
# labels below reason over (family / track / level / domains).
POSTINGS: list[tuple[str, str]] = [
    # Amazon — Prime Video science-leadership neighbourhood.
    ("amazon", "10428842"),   # Applied Science Manager, Prime Video Personalization & Discovery  [TARGET] ml_ai_research/management/mid/[media,ai_ml]
    ("amazon", "10434145"),   # Applied Science Manager, Prime Video - Content Localization        ml_ai_research/management/mid/[media,ai_ml]
    ("amazon", "10488209"),   # Applied Science Manager, Amazon Robotics                            ml_ai_research/management/mid/[ai_ml,devices_hardware]
    ("amazon", "10389713"),   # Principal Applied Scientist, Prime Video Personalization & Discovery ml_ai_research/TECHNICAL/PRINCIPAL/[media,ads,ai_ml]
    ("amazon", "3204869"),    # Principal Product Manager Tech, Prime Video Personalization & Disc.  PRODUCT_MANAGEMENT/product_program/principal/[media]
    ("amazon", "10427133"),   # Principal Technical Program Manager, Sye ..., Prime Video            TECHNICAL_PROGRAM_MANAGEMENT/product_program/principal/[media]
    ("amazon", "10399754"),   # Applied Science Manager, Ads Measurement Science                    ml_ai_research/management/mid/[advertising,ai_ml]
    # Anthropic — manager/IC and product/program minimal pairs.
    ("anthropic", "5159608008"),  # Engineering Manager, Agent Prompts & Evals        engineering_management/management/staff/[]
    ("anthropic", "4741102008"),  # Engineering Manager, Inference                     engineering_management/management/staff/[ai_ml]
    ("anthropic", "5316593008"),  # Engineering Manager, Agent Runtime Platform        engineering_management/management/staff/[cloud_infra]
    ("anthropic", "5134895008"),  # Senior Staff Software Engineer, API                SOFTWARE_ENGINEERING/TECHNICAL/principal/[]
    ("anthropic", "5211241008"),  # Senior Staff+ Software Engineer, Kubernetes Platform SOFTWARE_ENGINEERING/TECHNICAL/principal/[cloud_infra]
    ("anthropic", "5139628008"),  # Product Manager, Safeguards Rare Harms             product_management/product_program/senior/[security_privacy]
    ("anthropic", "5385653008"),  # Commercial Operations Program Manager              PROGRAM_MANAGEMENT/product_program/senior/[]
    ("anthropic", "5207565008"),  # Community & Executive Escalations Program Manager  PROGRAM_MANAGEMENT/product_program/senior/[]
    ("anthropic", "5251699008"),  # Customer Program Manager, Executive Briefing Center PROGRAM_MANAGEMENT/product_program/senior/[advertising]
    ("anthropic", "4980436008"),  # [Expression of Interest] Research Manager, Interpretability ml_ai_research/management/mid/[ai_ml]
    ("anthropic", "5192805008"),  # Applied AI Architect, Commercial                   ml_ai_research/technical/principal/[ai_ml]

    # --- Cohort fill to the cohort minimums ---------------------------------- #

    # Duplicate titles ACROSS companies. The exact-title claim is a title claim,
    # not a row claim: these must all resolve exact for a bare title query, and
    # an explicit company filter is what disambiguates.
    ("mistral", "6dfcbf55-d854-4723-85e4-f44f3032fc63"),  # Engineering Manager, Inference  == anthropic-4741102008 title  eng_mgmt/management/staff/[ai_ml] hybrid/new_york
    ("google", "100980257124688582"),  # Senior Technical Program Manager        tpm/product_program/senior/[] silicon_valley
    ("microsoft", "1970393556937283"), # Senior Technical Program Manager        tpm/product_program/senior/[] onsite silicon_valley+pnw
    ("microsoft", "1970393556850527"), # Senior Technical Program Manager        tpm/product_program/senior/[] onsite silicon_valley+pnw
    ("google", "133375036143608518"),  # Technical Program Manager               tpm/product_program/senior/[] silicon_valley
    ("google", "107140688704873158"),  # Technical Program Manager               tpm/product_program/senior/[] silicon_valley
    ("meta", "1296230207698571"),      # Technical Program Manager               tpm/product_program/senior/[] silicon_valley+pnw
    ("microsoft", "1970393556936646"), # Technical Program Manager               tpm/product_program/senior/[] onsite pnw
    ("google", "132634425941729990"),  # Product Manager                         product_mgmt/product_program/senior/[] silicon_valley
    ("meta", "1238249364564427"),      # Product Manager                         product_mgmt/product_program/senior/[] REMOTE silicon_valley+pnw
    ("meta", "2014107449312859"),      # Product Manager                         product_mgmt/product_program/senior/[] SINGAPORE
    ("microsoft", "1970393556874131"), # Senior Product Manager                  product_mgmt/product_program/senior/[] onsite pnw
    ("amazon", "10474139"),            # Senior Product Manager                  product_mgmt/product_program/STAFF/[retail,logistics] SINGAPORE
    ("nvidia", "JR2019755"),           # Principal Product Manager               product_mgmt/product_program/principal/[] united_states
    ("microsoft", "1970393556859132"), # Principal Product Manager               product_mgmt/product_program/principal/[] onsite pnw

    # Netflix: real disclosed USD bands (comp cohort) + rich multi-domain rows
    # (domain minimal pairs). Track/family flips inside one company and one org.
    ("netflix", "790315805709"),  # Senior Manager - Reliability Engineering (Member Exp)  infra_sre/MANAGEMENT/staff/[media,cloud_infra]
    ("netflix", "790312452283"),  # Principal Product Manager - Games, Social Platform     product_mgmt/product_program/principal/[media,devices]
    ("netflix", "790316327930"),  # Staff ML Software Engineer (L6) - Platform Systems     software_eng/TECHNICAL/staff/[media,data_analytics]
    ("netflix", "790315764775"),  # Engineering Manager, Privacy Infrastructure Eng        eng_mgmt/management/staff/[media,security_privacy,cloud_infra]
    ("netflix", "790314756260"),  # Group Product Manager, Payments Product Journey        product_mgmt/product_program/principal/[media,payments_fintech]
    ("netflix", "790313754528"),  # Engineering Manager, Platform Systems - AIMS           eng_mgmt/management/staff/[media,data_analytics]
    ("netflix", "790317582272"),  # Engineering Manager, AI for Member Systems             eng_mgmt/management/staff/[media,...]

    # Semantic-intent targets: the concept lives in the BODY, not the title.
    ("anthropic", "5238296008"),  # Staff + Sr. Software Engineer, Cloud Inference Launch  software_eng/technical/staff
    ("anthropic", "4778843008"),  # Staff+ Software Engineer, Safeguards ML Infrastructure software_eng/technical/staff
    ("anthropic", "4951844008"),  # Staff+ Software Engineer, Safeguards                   software_eng/technical/staff
    ("anthropic", "5270442008"),  # Staff+ Software Engineer, Identity & Access Controls   software_eng/technical/staff
    ("openai", "e1daa4e0-c42a-45a7-b9ee-559b35bfe08a"),  # Technical Lead Manager, Data Engineering, Trust & Safety  eng_mgmt/management/staff
    ("google", "128435823753208518"),  # Senior Product Manager, Engagement Safety, YouTube  product_mgmt/product_program/senior
    ("google", "116987389783483078"),  # Senior Staff Engineer, GDC AI Inference Platform    software_eng/technical/principal
    ("microsoft", "1970393556941462"), # Principal Product Manager, Personalization Lead     product_mgmt/product_program/principal
    ("microsoft", "1970393556948713"), # Principal Applied Science Manager                   ml_ai_research/management/principal
    ("apple", "200648838-0836"),       # Lead Personalization Product Manager, Apple Music   product_mgmt/product_program/staff
    ("apple", "200670904-0836"),       # Staff ML Engineer - Ads ML Infrastructure           ml_ai_research/technical/staff
    ("apple", "200671821-0836"),       # Senior Data Science Manager - WW Product Marketing  data_science/management/senior
    ("microsoft", "1970393556933204"), # Principal Data Scientist                            data_science/TECHNICAL/principal
    ("amazon", "10453249"),            # Applied Science Manager, Stores-Ads Science         ml_ai_research/management/mid/[ads,ai_ml]
    ("amazon", "10495000"),            # Sr. Product Manager, AWS Kubernetes                 product_mgmt/product_program/staff/[cloud_infra]
    ("amazon", "10448733"),            # Senior Data Center Construction Procurement Manager biz_ops/management/staff

    # Hardware / silicon: a family+domain world far from the AI rows, so a
    # no-answer or AI-intent query that reaches here has clearly over-admitted.
    ("microsoft", "1970393556939446"), # Principal Silicon Design Subsystem Lead   hardware_eng/technical/principal
    ("microsoft", "1970393556860661"), # Principal Silicon Performance Architect   hardware_eng/technical/principal
    ("meta", "2034285740545591"),      # ASIC Engineer, Architecture               hardware_eng/technical/mid
    ("amazon", "10410749"),            # Sr. Technical Program Manager - AI/ML Hardware, Annapurna tpm/product_program/staff

    # Security cluster + the sharpest available family minimal pair: same org
    # path ("Infrastructure Security"), same track, same level, family flips.
    ("openai", "8f1b8c6b-b414-4026-a434-6ca32c3b3e0d"),  # Principal Security Engineer, Infrastructure Security  SECURITY_ENGINEERING/technical/principal REMOTE
    ("openai", "ace42c6d-8663-4b30-9337-ec70cf071d73"),  # Principal Software Engineer, Infrastructure Security  SOFTWARE_ENGINEERING/technical/principal REMOTE
    ("openai", "c414f15f-60c4-40b5-a896-d2ad6c7f4415"),  # Senior Technical Program Manager - Security           tpm/product_program/senior REMOTE
    ("microsoft", "1970393556943181"), # Principal Security Research Manager       ml_ai_research/management/principal
    ("spotify", "a88002db-cb15-49f4-a0e7-efc5c79c347b"), # Principal Product Manager, Engagement Journeys  product_mgmt/product_program/principal REMOTE
]


def _k(company: str, req_id: str) -> str:
    return f"{company}-{req_id}"


# --- queries + authored class labels ---------------------------------------- #
# Each query: key, cohort, kind, text, and class->(posting_keys, reason).
# Postings not listed take `default_class` (irrelevant unless noted).
QUERIES: list[dict] = [
    {
        "key": "pv_exact",
        "cohort": "exact_title",
        "kind": "exact_title",
        "text": "Applied Science Manager, Prime Video Personalization & Discovery",
        "labels": {
            "exact": (["amazon-10428842"], "identical stored title (trailing-space only)"),
            "close": (["amazon-10434145", "microsoft-1970393556948713"],
                      "same role shape; Prime Video sub-team differs, or a single-segment title with no org path (missing mission evidence is neutral)"),
            "related": (
                ["amazon-10488209", "amazon-10389713", "amazon-3204869", "amazon-10427133",
                 "amazon-10399754", "amazon-10453249"],
                "role-shape or mission conflict vs target: robotics/ads org-path, IC track, principal level, product/program family",
            ),
        },
    },
    {
        "key": "pv_exact_lc",
        "cohort": "exact_title",
        "kind": "exact_title",
        "text": "applied science manager, prime video personalization & discovery",
        "note": "conservative key: case-fold + trailing space only -> still exact; one load-bearing phrase change is not exact",
        "labels": {
            "exact": (["amazon-10428842"], "case/whitespace damage only -> cosmetic, still exact"),
            "close": (["amazon-10434145", "microsoft-1970393556948713"],
                      "sub-team phrase differs, or single-segment title with neutral mission -> not exact"),
            "related": (
                ["amazon-10488209", "amazon-10389713", "amazon-3204869", "amazon-10427133",
                 "amazon-10399754", "amazon-10453249"],
                "role-shape or mission conflict vs target",
            ),
        },
    },
    {
        "key": "eng_manager",
        "cohort": "minimal_pair",
        "kind": "exploratory",
        "text": "Engineering Manager",
        "note": "Engineering Manager != Engineer (family+track flip)",
        "labels": {
            "close": (
                ["anthropic-5159608008", "anthropic-4741102008", "anthropic-5316593008",
                 "mistral-6dfcbf55-d854-4723-85e4-f44f3032fc63", "netflix-790315764775",
                 "netflix-790313754528", "netflix-790317582272"],
                "engineering_management/management role shape matches; team suffix -> not exact",
            ),
            "related": (
                ["anthropic-5134895008", "anthropic-5211241008", "anthropic-4980436008",
                 "anthropic-5238296008", "anthropic-4778843008", "anthropic-4951844008",
                 "anthropic-5270442008", "openai-ace42c6d-8663-4b30-9337-ec70cf071d73",
                 "google-116987389783483078", "netflix-790316327930", "netflix-790315805709",
                 "openai-e1daa4e0-c42a-45a7-b9ee-559b35bfe08a"],
                "engineers: software_engineering/technical family+track conflict; research manager: manager but ml_ai_research family; reliability manager: infra family; TLM: title head reads as Data Engineering",
            ),
        },
    },
    {
        "key": "product_manager",
        "cohort": "minimal_pair",
        "kind": "exact_title",
        "text": "Product Manager",
        "note": "Product Manager != Program Manager (family flip). Kind/labels updated when identical-titled rows entered the posting set: exact is a TITLE claim",
        "labels": {
            "exact": (
                ["google-132634425941729990", "meta-1238249364564427", "meta-2014107449312859"],
                "identical stored title",
            ),
            "close": (
                ["anthropic-5139628008", "amazon-3204869", "microsoft-1970393556874131",
                 "amazon-10474139", "nvidia-JR2019755", "microsoft-1970393556859132",
                 "netflix-790312452283", "netflix-790314756260", "microsoft-1970393556941462",
                 "spotify-a88002db-cb15-49f4-a0e7-efc5c79c347b", "google-128435823753208518",
                 "amazon-10495000", "apple-200648838-0836"],
                "product_management role shape matches; the query names no level, so level words are neutral",
            ),
            "related": (
                ["anthropic-5385653008", "anthropic-5207565008", "anthropic-5251699008", "amazon-10427133"],
                "program_management / technical_program_management: family conflict vs product_management",
            ),
        },
    },
    {
        "key": "url_amz_target",
        "cohort": "identifier",
        "kind": "identifier",
        "text": "https://www.amazon.jobs/en/jobs/10428842/applied-science-manager-prime-video-personalization-discovery",
        "note": "URL identity: only the identity match, related_items=[]",
        "labels": {
            "exact": (["amazon-10428842"], "stored URL identity"),
        },
    },
    {
        "key": "reqid_ant_em",
        "cohort": "identifier",
        "kind": "identifier",
        "text": "5316593008",
        "note": "req_id identity (unambiguous across the corpus)",
        "labels": {
            "exact": (["anthropic-5316593008"], "complete stored req_id identity"),
        },
    },
    {
        "key": "no_answer_vet",
        "cohort": "no_answer",
        "kind": "exploratory",
        "text": "Veterinary Surgeon, Small Animal Clinic",
        "note": "no-answer control: nearest dense rows must be rejected; zero semantic-only admission",
        "labels": {},  # every posting -> irrelevant
    },
    {
        "key": "typo_anthropic_em",
        "cohort": "typo_fragment",
        "kind": "exploratory",
        "text": "anthropc enginering manager",
        "note": "typo: target must survive to top-5 via fuzzy",
        "labels": {
            "close": (
                ["anthropic-5159608008", "anthropic-4741102008", "anthropic-5316593008"],
                "typo of 'anthropic engineering manager' -> EM rows are the target",
            ),
            "related": (
                ["anthropic-5134895008", "anthropic-5211241008", "anthropic-5238296008",
                 "anthropic-4778843008", "anthropic-4951844008", "anthropic-5270442008"],
                "same org engineering, IC track -> adjacency only",
            ),
        },
    },

    # ======================================================================== #
    # Cohort fill to the cohort minimums.
    # ======================================================================== #

    # --- exact titles (minimum 10) ----------------------------------------- #
    {
        "key": "exact_em_inference",
        "cohort": "exact_title",
        "kind": "exact_title",
        "text": "Engineering Manager, Inference",
        "note": "duplicate title ACROSS COMPANIES: exact is a TITLE claim, so both rows are exact; an explicit company filter is what disambiguates",
        "labels": {
            "exact": (["anthropic-4741102008", "mistral-6dfcbf55-d854-4723-85e4-f44f3032fc63"],
                      "identical stored title at two companies"),
            "related": (
                ["anthropic-5159608008", "anthropic-5316593008", "netflix-790315764775",
                 "netflix-790313754528", "netflix-790317582272", "openai-e1daa4e0-c42a-45a7-b9ee-559b35bfe08a",
                 "anthropic-5238296008", "google-116987389783483078"],
                "same EM role shape but a different mission, or the inference mission on an IC track",
            ),
        },
    },
    {
        "key": "exact_tpm",
        "cohort": "exact_title",
        "kind": "exact_title",
        "text": "Technical Program Manager",
        "note": "four exact rows across three companies; Senior TPM is close (level word only), program management is a family flip",
        "labels": {
            "exact": (["google-133375036143608518", "google-107140688704873158",
                       "meta-1296230207698571", "microsoft-1970393556936646"],
                      "identical stored title"),
            "close": (["google-100980257124688582", "microsoft-1970393556937283",
                       "microsoft-1970393556850527", "openai-c414f15f-60c4-40b5-a896-d2ad6c7f4415",
                       "amazon-10410749", "amazon-10427133"],
                      "same TPM family/track; a level word or team suffix is the only difference"),
            "related": (["anthropic-5385653008", "anthropic-5207565008", "anthropic-5251699008"],
                        "program_management is a different family from technical_program_management"),
        },
    },
    {
        "key": "exact_senior_tpm",
        "cohort": "exact_title",
        "kind": "exact_title",
        "text": "Senior Technical Program Manager",
        "note": "reverse direction of exact_tpm: the level word now belongs to the query",
        "labels": {
            "exact": (["google-100980257124688582", "microsoft-1970393556937283",
                       "microsoft-1970393556850527"], "identical stored title"),
            "close": (["google-133375036143608518", "google-107140688704873158",
                       "meta-1296230207698571", "microsoft-1970393556936646",
                       "openai-c414f15f-60c4-40b5-a896-d2ad6c7f4415"],
                      "same TPM family/track at the same senior band; level word only"),
            "related": (["anthropic-5385653008", "anthropic-5207565008", "anthropic-5251699008",
                         "amazon-10427133", "amazon-10410749"],
                        "program_management family flip; principal/staff TPM is an explicit level conflict"),
        },
    },
    {
        "key": "exact_principal_pm",
        "cohort": "exact_title",
        "kind": "exact_title",
        "text": "Principal Product Manager",
        "note": "explicit level in the QUERY: principal PM rows are close, senior/staff PM rows are a level conflict",
        "labels": {
            "exact": (["nvidia-JR2019755", "microsoft-1970393556859132"], "identical stored title"),
            "close": (["netflix-790312452283", "netflix-790314756260",
                       "microsoft-1970393556941462", "spotify-a88002db-cb15-49f4-a0e7-efc5c79c347b",
                       "amazon-3204869"],
                      "product_management/product_program at the same explicit principal band"),
            "related": (["google-132634425941729990", "meta-1238249364564427", "meta-2014107449312859",
                         "microsoft-1970393556874131", "amazon-10474139", "amazon-10495000",
                         "apple-200648838-0836", "google-128435823753208518", "anthropic-5139628008"],
                        "same PM family but the query states principal and these rows do not"),
        },
    },
    {
        "key": "exact_em_agent_runtime",
        "cohort": "exact_title",
        "kind": "exact_title",
        "text": "Engineering Manager, Agent Runtime Platform",
        "labels": {
            "exact": (["anthropic-5316593008"], "identical stored title"),
            "related": (["anthropic-5159608008", "anthropic-4741102008",
                         "mistral-6dfcbf55-d854-4723-85e4-f44f3032fc63"],
                        "same EM role shape, different mission"),
        },
    },
    {
        "key": "exact_damage_punct",
        "cohort": "exact_title",
        "kind": "exact_title",
        "text": "  Applied Science Manager, Prime Video Personalization & Discovery ,  ",
        "note": "punctuation/space damage: NBSP, doubled spaces, trailing ' ,' -> all cosmetic, still exact",
        "labels": {
            "exact": (["amazon-10428842"], "NBSP + whitespace + trailing separator damage only"),
            "close": (["amazon-10434145", "microsoft-1970393556948713"],
                      "sub-team phrase differs, or single-segment title with neutral mission"),
            "related": (["amazon-10488209", "amazon-10389713", "amazon-3204869",
                         "amazon-10427133", "amazon-10399754", "amazon-10453249"],
                        "role-shape or mission conflict vs target"),
        },
    },
    {
        "key": "near_exact_one_word",
        "cohort": "exact_title",
        "kind": "exploratory",
        "text": "Applied Science Manager, Prime Video Personalization & Delivery",
        "note": "NEGATIVE control: one load-bearing word changed (Discovery->Delivery). Nothing may be exact",
        "labels": {
            "close": (["amazon-10428842", "amazon-10434145"],
                      "same role shape and Prime Video mission, but the query names a team that does not exist"),
            "related": (["amazon-10488209", "amazon-10389713", "amazon-3204869",
                         "amazon-10427133", "amazon-10399754", "amazon-10453249"],
                        "role-shape or mission conflict"),
        },
    },
    {
        "key": "near_exact_separator",
        "cohort": "exact_title",
        "kind": "exploratory",
        "text": "Applied Science Manager — Prime Video Personalization & Discovery",
        "note": "NEGATIVE control: a dash is not a comma. Dash CODEPOINTS fold; a different separator character is not damage, so this is close and never exact",
        "labels": {
            "close": (["amazon-10428842", "amazon-10434145"],
                      "same head and mission; the separator differs so identity is not proven"),
            "related": (["amazon-10488209", "amazon-10389713", "amazon-3204869",
                         "amazon-10427133", "amazon-10399754", "amazon-10453249"],
                        "role-shape or mission conflict"),
        },
    },

    # --- identifiers (minimum 5) ------------------------------------------- #
    {
        "key": "url_tracking_fragment",
        "cohort": "identifier",
        "kind": "identifier",
        "text": "https://www.amazon.jobs/en/jobs/10428842/applied-science-manager-prime-video-personalization-discovery?utm_source=linkedin&utm_campaign=paid&ref=jobfeed#apply-now",
        "note": "URL normalization: tracking query + fragment removed, nothing else",
        "labels": {"exact": (["amazon-10428842"], "stored URL identity after tracking/fragment removal")},
    },
    {
        "key": "url_mistral_em",
        "cohort": "identifier",
        "kind": "identifier",
        "text": "@url:mistral-6dfcbf55-d854-4723-85e4-f44f3032fc63",
        "note": "identifier identity for the row whose TITLE is duplicated at anthropic — the URL disambiguates what the title cannot",
        "labels": {"exact": (["mistral-6dfcbf55-d854-4723-85e4-f44f3032fc63"], "stored URL identity")},
    },
    {
        "key": "reqid_amazon_target",
        "cohort": "identifier",
        "kind": "identifier",
        "text": "10428842",
        "labels": {"exact": (["amazon-10428842"], "complete stored req_id identity")},
    },
    {
        "key": "reqid_absent",
        "cohort": "identifier",
        "kind": "exploratory",
        "text": "99999999999",
        "note": "NEGATIVE control: looks like a req id, matches no row -> exploratory, and nothing may be exact",
        "labels": {},
    },

    # --- typos / fragments / abbreviations (minimum 8) --------------------- #
    {
        "key": "typo_company_only",
        "filter_dependent": True,
        "cohort": "typo_fragment",
        "kind": "exploratory",
        "text": "anthropc",
        "note": "company-name typo with no role claim: company adjacency only, never a role match",
        "labels": {
            "related": (
                ["anthropic-5159608008", "anthropic-4741102008", "anthropic-5316593008",
                 "anthropic-5134895008", "anthropic-5211241008", "anthropic-5139628008",
                 "anthropic-5385653008", "anthropic-5207565008", "anthropic-5251699008",
                 "anthropic-4980436008", "anthropic-5192805008", "anthropic-5238296008",
                 "anthropic-4778843008", "anthropic-4951844008", "anthropic-5270442008"],
                "company matches by fuzzy; the query names no role, so no row can be close",
            ),
        },
    },
    {
        "key": "abbrev_tpm",
        "cohort": "typo_fragment",
        "kind": "exploratory",
        "text": "TPM",
        "note": "abbreviation with no exact row; the taxonomy carries 'tpm' as a TPM keyword",
        "labels": {
            "close": (["google-133375036143608518", "google-107140688704873158",
                       "meta-1296230207698571", "microsoft-1970393556936646",
                       "google-100980257124688582", "microsoft-1970393556937283",
                       "microsoft-1970393556850527", "openai-c414f15f-60c4-40b5-a896-d2ad6c7f4415",
                       "amazon-10410749", "amazon-10427133"],
                      "technical_program_management family"),
            "related": (["anthropic-5385653008", "anthropic-5207565008", "anthropic-5251699008"],
                        "program management adjacency"),
        },
    },
    {
        "key": "fragment_personalization",
        "cohort": "typo_fragment",
        "kind": "exploratory",
        "text": "personalization",
        "note": "mission fragment, no role named -> no row may be close (a query naming no role claims no track)",
        "labels": {
            "related": (["amazon-10428842", "amazon-10389713", "amazon-3204869",
                         "microsoft-1970393556941462", "apple-200648838-0836", "amazon-10434145"],
                        "the personalization mission appears in the title/org path; the query names no role"),
        },
    },
    {
        "key": "typo_kubernetes_platform",
        "cohort": "typo_fragment",
        "kind": "exploratory",
        "text": "kubernets platform enginer",
        "note": "two typos + a mission word; targets must survive via fuzzy",
        "labels": {
            "close": (["anthropic-5211241008"], "Kubernetes Platform engineer, IC track"),
            "related": (["amazon-10495000", "anthropic-5238296008"],
                        "kubernetes/cloud mission on a product or different engineering team"),
        },
    },
    {
        "key": "typo_silicon_design",
        "cohort": "typo_fragment",
        "kind": "exploratory",
        "text": "silicn desgin enginer",
        "labels": {
            "close": (["microsoft-1970393556939446", "microsoft-1970393556860661",
                       "meta-2034285740545591"],
                      "hardware/silicon design engineering"),
            "related": (["amazon-10410749"], "AI/ML hardware program management adjacency"),
        },
    },
    {
        "key": "fragment_safeguards",
        "cohort": "typo_fragment",
        "kind": "exploratory",
        "text": "safeguards",
        "note": "org-path fragment naming no role",
        "labels": {
            "related": (["anthropic-4951844008", "anthropic-4778843008", "anthropic-5139628008"],
                        "Safeguards org path; the query names no role"),
        },
    },
    {
        "key": "typo_aplied_sience_maneger",
        "cohort": "typo_fragment",
        "kind": "exploratory",
        "text": "aplied sience maneger",
        "note": "three typos in the role phrase: no lexical token survives, so only fuzzy can find these",
        "labels": {
            "close": (["amazon-10428842", "amazon-10434145", "amazon-10488209",
                       "amazon-10399754", "amazon-10453249", "microsoft-1970393556948713"],
                      "applied science management rows"),
            "related": (["amazon-10389713", "anthropic-4980436008", "anthropic-5192805008"],
                        "applied science / research on an IC track, or research management"),
        },
    },

    # --- structured natural language (minimum 8) --------------------------- #
    {
        "key": "nl_remote_pm_meta",
        "filter_dependent": True,
        "cohort": "structured_nl",
        "kind": "exploratory",
        "text": "remote product manager at meta",
        "note": "company + workplace + family all parse; the remote meta PM is the only row satisfying all three",
        "labels": {
            "close": (["meta-1238249364564427"], "meta + remote + product_management"),
            "related": (["meta-2014107449312859"], "meta product manager, but not remote"),
        },
    },
    {
        "key": "nl_principal_pm_netflix",
        "filter_dependent": True,
        "cohort": "structured_nl",
        "kind": "exploratory",
        "text": "principal product manager at netflix",
        "labels": {
            "close": (["netflix-790312452283", "netflix-790314756260"],
                      "netflix + principal + product_management"),
            "related": (["netflix-790315805709", "netflix-790315764775", "netflix-790313754528",
                         "netflix-790317582272", "netflix-790316327930"],
                        "netflix, but a different family/track"),
        },
    },
    {
        "key": "nl_pm_singapore",
        "filter_dependent": True,
        "cohort": "structured_nl",
        "kind": "exploratory",
        "text": "product manager jobs in Singapore",
        "labels": {
            "close": (["meta-2014107449312859", "amazon-10474139"],
                      "product_management rows in the singapore location group"),
        },
    },
    {
        "key": "nl_senior_tpm_microsoft",
        "filter_dependent": True,
        "cohort": "structured_nl",
        "kind": "exploratory",
        "text": "senior technical program manager at microsoft",
        "labels": {
            "close": (["microsoft-1970393556937283", "microsoft-1970393556850527",
                       "microsoft-1970393556936646"],
                      "microsoft + TPM family at the senior band"),
            "related": (["google-100980257124688582", "google-133375036143608518",
                         "google-107140688704873158", "meta-1296230207698571",
                         "openai-c414f15f-60c4-40b5-a896-d2ad6c7f4415"],
                        "same role, wrong company"),
        },
    },
    {
        "key": "nl_remote_security_openai",
        "filter_dependent": True,
        "cohort": "structured_nl",
        "kind": "exploratory",
        "text": "remote security engineer at openai",
        "labels": {
            "close": (["openai-8f1b8c6b-b414-4026-a434-6ca32c3b3e0d"],
                      "openai + remote + security_engineering"),
            "related": (["openai-ace42c6d-8663-4b30-9337-ec70cf071d73",
                         "openai-c414f15f-60c4-40b5-a896-d2ad6c7f4415"],
                        "same openai infrastructure-security org, different family"),
        },
    },
    {
        "key": "nl_applied_science_manager_amazon",
        "filter_dependent": True,
        "cohort": "structured_nl",
        "kind": "exploratory",
        "text": "applied science manager at amazon",
        "note": "the taxonomy fix under test: 'applied science' must parse a family",
        "labels": {
            "close": (["amazon-10428842", "amazon-10434145", "amazon-10488209",
                       "amazon-10399754", "amazon-10453249"],
                      "amazon + ml_ai_research + management"),
            "related": (["amazon-10389713", "microsoft-1970393556948713"],
                        "applied science on an IC track, or the right role at the wrong company"),
        },
    },
    {
        "key": "nl_hardware_engineer_onsite",
        "filter_dependent": True,
        "cohort": "structured_nl",
        "kind": "exploratory",
        "text": "onsite silicon hardware engineer",
        "labels": {
            "close": (["microsoft-1970393556939446", "microsoft-1970393556860661"],
                      "hardware_engineering, onsite"),
            "related": (["meta-2034285740545591"], "hardware engineering, workplace not stated"),
        },
    },
    {
        "key": "nl_em_new_york",
        "filter_dependent": True,
        "cohort": "structured_nl",
        "kind": "exploratory",
        "text": "engineering manager in New York",
        "labels": {
            "close": (["mistral-6dfcbf55-d854-4723-85e4-f44f3032fc63",
                       "anthropic-5159608008", "anthropic-5316593008"],
                      "engineering_management in the new_york location group"),
            "related": (["anthropic-4741102008", "netflix-790315764775", "netflix-790313754528",
                         "netflix-790317582272", "openai-e1daa4e0-c42a-45a7-b9ee-559b35bfe08a"],
                        "engineering management elsewhere"),
        },
    },

    # --- semantic intent (minimum 8) --------------------------------------- #
    # Paraphrases: `search_vector` is to_tsvector(title || description), so a
    # query sharing ANY stemmed term with the doc is found lexically. These are
    # authored to share none, then VERIFIED non-lexical at build time.
    {
        "key": "intent_faster_model_responses",
        "cohort": "semantic_intent",
        "kind": "exploratory",
        "text": "make our models reply quicker to users",
        "note": "paraphrase of inference latency/serving work",
        "labels": {
            "close": (["anthropic-4741102008", "mistral-6dfcbf55-d854-4723-85e4-f44f3032fc63",
                       "anthropic-5238296008", "google-116987389783483078"],
                      "inference serving/latency ownership"),
        },
    },
    {
        "key": "intent_stop_bad_actors",
        "cohort": "semantic_intent",
        "kind": "exploratory",
        "text": "keep bad actors from misusing our product",
        "labels": {
            "close": (["anthropic-4951844008", "anthropic-4778843008", "anthropic-5139628008",
                       "openai-e1daa4e0-c42a-45a7-b9ee-559b35bfe08a"],
                      "safeguards / trust and safety ownership"),
            "related": (["google-128435823753208518", "anthropic-5270442008"],
                        "adjacent safety or access-control work"),
        },
    },
    {
        "key": "intent_what_to_watch_next",
        "cohort": "semantic_intent",
        "kind": "exploratory",
        "text": "decide what show a viewer sees next",
        "labels": {
            "close": (["amazon-10428842", "amazon-10389713", "netflix-790317582272"],
                      "streaming recommendation/personalization ownership"),
            "related": (["apple-200648838-0836", "microsoft-1970393556941462", "amazon-3204869"],
                        "personalization work outside streaming, or the product side of it"),
        },
    },
    {
        "key": "intent_keep_service_up",
        "cohort": "semantic_intent",
        "kind": "exploratory",
        "text": "keep the service running when things break at night",
        "labels": {
            "close": (["netflix-790315805709"], "reliability engineering leadership"),
            "related": (["anthropic-5211241008", "netflix-790313754528", "amazon-10495000"],
                        "platform/infrastructure adjacency"),
        },
    },
    {
        "key": "intent_buy_things_for_datacenters",
        "cohort": "semantic_intent",
        "kind": "exploratory",
        "text": "negotiate purchases with suppliers for new buildings",
        "labels": {
            "close": (["amazon-10448733"], "data-centre construction procurement"),
        },
    },
    {
        "key": "intent_measure_if_changes_worked",
        "cohort": "semantic_intent",
        "kind": "exploratory",
        "text": "figure out whether a launch actually changed user behaviour",
        "labels": {
            "close": (["apple-200671821-0836", "microsoft-1970393556933204"],
                      "experimentation / measurement science"),
            "related": (["amazon-10399754", "amazon-10453249"], "ads measurement science adjacency"),
        },
    },
    {
        "key": "intent_help_customers_adopt",
        "cohort": "semantic_intent",
        "kind": "exploratory",
        "text": "work alongside big customers so they succeed with our technology",
        "labels": {
            "close": (["anthropic-5192805008"], "commercial applied-AI architect, customer facing"),
            "related": (["anthropic-5251699008", "amazon-10495000"],
                        "customer program management adjacency"),
        },
    },
    {
        "key": "intent_design_the_chip",
        "cohort": "semantic_intent",
        "kind": "exploratory",
        "text": "lay out transistors and verify timing closure",
        "labels": {
            "close": (["microsoft-1970393556939446", "microsoft-1970393556860661",
                       "meta-2034285740545591"],
                      "silicon design / architecture"),
        },
    },

    # --- no-answer controls (minimum 6) ------------------------------------ #
    {
        "key": "no_answer_chef",
        "cohort": "no_answer",
        "kind": "exploratory",
        "text": "Executive Pastry Chef, Hotel Restaurant Group",
        "labels": {},
    },
    {
        "key": "no_answer_nurse",
        "cohort": "no_answer",
        "kind": "exploratory",
        "text": "Registered Nurse, Pediatric Intensive Care Unit",
        "labels": {},
    },
    {
        "key": "no_answer_truck_driver",
        "cohort": "no_answer",
        "kind": "exploratory",
        "text": "Long Haul Truck Driver, Class A CDL",
        "labels": {},
    },
    {
        "key": "no_answer_teacher",
        "cohort": "no_answer",
        "kind": "exploratory",
        "text": "High School Mathematics Teacher, Grade 11",
        "labels": {},
    },
    {
        "key": "no_answer_plumber",
        "cohort": "no_answer",
        "kind": "exploratory",
        "text": "Licensed Plumber, Residential Service Calls",
        "labels": {},
    },

    # --- minimal pairs, both directions (minimum 12 directions) ------------ #
    {
        "key": "mp_software_engineer",
        "cohort": "minimal_pair",
        "kind": "exploratory",
        "text": "Software Engineer",
        "note": "reverse of eng_manager: Engineer != Engineering Manager (family+track flip)",
        "labels": {
            "close": (["anthropic-5134895008", "anthropic-5211241008", "anthropic-5238296008",
                       "anthropic-4778843008", "anthropic-4951844008", "anthropic-5270442008",
                       "openai-ace42c6d-8663-4b30-9337-ec70cf071d73", "netflix-790316327930",
                       "google-116987389783483078"],
                      "software_engineering / technical"),
            "related": (["anthropic-5159608008", "anthropic-4741102008", "anthropic-5316593008",
                         "mistral-6dfcbf55-d854-4723-85e4-f44f3032fc63", "netflix-790315764775",
                         "netflix-790313754528", "netflix-790317582272",
                         "openai-e1daa4e0-c42a-45a7-b9ee-559b35bfe08a"],
                        "engineering MANAGEMENT: the one word that flips family and track"),
        },
    },
    {
        "key": "mp_program_manager",
        "cohort": "minimal_pair",
        "kind": "exploratory",
        "text": "Program Manager",
        "note": "reverse of product_manager: Program != Product (family flip)",
        "labels": {
            "close": (["anthropic-5385653008", "anthropic-5207565008", "anthropic-5251699008"],
                      "program_management"),
            "related": (["google-133375036143608518", "google-107140688704873158",
                         "meta-1296230207698571", "microsoft-1970393556936646",
                         "google-100980257124688582", "microsoft-1970393556937283",
                         "microsoft-1970393556850527", "amazon-10427133", "amazon-10410749",
                         "openai-c414f15f-60c4-40b5-a896-d2ad6c7f4415",
                         "google-132634425941729990", "meta-1238249364564427",
                         "meta-2014107449312859", "microsoft-1970393556874131"],
                        "technical program management and product management are different families"),
        },
    },
    {
        "key": "mp_security_engineer_infra",
        "cohort": "minimal_pair",
        "kind": "exploratory",
        "text": "Security Engineer, Infrastructure Security",
        "note": "sharpest available pair: SAME org path, same track, same level, family flips on one word",
        "labels": {
            "close": (["openai-8f1b8c6b-b414-4026-a434-6ca32c3b3e0d"], "security_engineering"),
            "related": (["openai-ace42c6d-8663-4b30-9337-ec70cf071d73",
                         "openai-c414f15f-60c4-40b5-a896-d2ad6c7f4415",
                         "anthropic-5270442008", "netflix-790315764775",
                         "microsoft-1970393556943181"],
                        "same security mission, different family"),
        },
    },
    {
        "key": "mp_software_engineer_infra",
        "cohort": "minimal_pair",
        "kind": "exploratory",
        "text": "Software Engineer, Infrastructure Security",
        "note": "reverse direction of mp_security_engineer_infra",
        "labels": {
            "close": (["openai-ace42c6d-8663-4b30-9337-ec70cf071d73"],
                      "software_engineering on the same Infrastructure Security org path"),
            "related": (["openai-8f1b8c6b-b414-4026-a434-6ca32c3b3e0d",
                         "openai-c414f15f-60c4-40b5-a896-d2ad6c7f4415",
                         "netflix-790315764775", "anthropic-5270442008"],
                        "adjacent security missions (identity/access, privacy infra) or a family flip"),
        },
    },
    {
        "key": "mp_principal_data_scientist",
        "cohort": "minimal_pair",
        "kind": "exact_title",
        "text": "Principal Data Scientist",
        "note": "IC direction: Data Scientist != Data Science Manager (track flip)",
        "labels": {
            "exact": (["microsoft-1970393556933204"], "identical stored title"),
            "related": (["apple-200671821-0836"], "data science MANAGEMENT: track flip"),
        },
    },
    {
        "key": "mp_data_science_manager",
        "cohort": "minimal_pair",
        "kind": "exploratory",
        "text": "Data Science Manager",
        "note": "management direction of mp_principal_data_scientist",
        "labels": {
            "close": (["apple-200671821-0836"], "data_science + management"),
            "related": (["microsoft-1970393556933204"], "data science on the IC track: track flip"),
        },
    },
    {
        "key": "mp_applied_science_manager",
        "cohort": "minimal_pair",
        "kind": "exploratory",
        "text": "Applied Science Manager",
        "note": "management direction; Principal Applied SCIENTIST is the IC flip",
        "labels": {
            "close": (["amazon-10428842", "amazon-10434145", "amazon-10488209",
                       "amazon-10399754", "amazon-10453249", "microsoft-1970393556948713"],
                      "ml_ai_research + management"),
            "related": (["amazon-10389713", "anthropic-5192805008", "anthropic-4980436008"],
                        "applied science / AI on the IC track, or research management elsewhere"),
        },
    },
    {
        "key": "mp_applied_scientist",
        "cohort": "minimal_pair",
        "kind": "exploratory",
        "text": "Principal Applied Scientist",
        "note": "IC direction of mp_applied_science_manager. NOT exact: the stored title carries an org path the query does not",
        "labels": {
            "close": (["amazon-10389713"],
                      "same applied-science IC role at the principal band"),
            "related": (["amazon-10428842", "amazon-10434145", "amazon-10488209",
                         "amazon-10399754", "amazon-10453249", "microsoft-1970393556948713",
                         "anthropic-5192805008"],
                        "applied science MANAGEMENT (track flip), or an architect rather than a scientist"),
        },
    },
    {
        "key": "mp_em_streaming_domain",
        "cohort": "minimal_pair",
        "kind": "exploratory",
        "text": "Engineering Manager, Streaming Platform",
        "note": "DOMAIN flip: identical family and track throughout; only media_entertainment separates them",
        "labels": {
            "close": (["netflix-790313754528"],
                      "engineering management, media_entertainment world, and a Platform Systems org path that overlaps the query's"),
            "related": (["netflix-790317582272", "netflix-790315764775",
                         "anthropic-5159608008", "anthropic-4741102008", "anthropic-5316593008",
                         "mistral-6dfcbf55-d854-4723-85e4-f44f3032fc63",
                         "openai-e1daa4e0-c42a-45a7-b9ee-559b35bfe08a"],
                        "same EM role shape but a different sub-mission, or no media world at all"),
        },
    },
    {
        "key": "mp_senior_product_manager",
        "cohort": "minimal_pair",
        "kind": "exact_title",
        "text": "Senior Product Manager",
        "note": "LEVEL flip, and the sharp case: amazon-10474139 carries this exact title but a STAFF stored band. Identity is a title claim, so exact must win over the level conflict",
        "labels": {
            "exact": (["microsoft-1970393556874131", "amazon-10474139"],
                      "identical stored title; the amazon row's staff band does not undo identity"),
            "close": (["google-132634425941729990", "meta-1238249364564427",
                       "meta-2014107449312859"],
                      "product_management at the senior band the query names"),
            "related": (["nvidia-JR2019755", "microsoft-1970393556859132", "netflix-790312452283",
                         "netflix-790314756260", "microsoft-1970393556941462",
                         "spotify-a88002db-cb15-49f4-a0e7-efc5c79c347b", "amazon-3204869"],
                        "principal PM: explicit level conflict against a senior query"),
        },
    },
]

# What THIS seed does not cover. Recorded in the fixture so "coverage" is
# never over-claimed.
COHORT_TODO = {
    "_status": (
        "Every cohort minimum is met (exact 10, identifier 6, typo 8, structured_nl 8, "
        "semantic_intent 8, no_answer 6, minimal_pair 12). What remains is listed below "
        "and is NOT covered by this fixture."
    ),
    "explicit_filter_precedence": (
        "The structured-NL cohort should exercise explicit-filter precedence (an explicit "
        "UI filter must beat a conflicting parsed one). A fixture query is only text, so "
        "this cannot be expressed here: it needs request-level filter params. It belongs "
        "in an API test, not in this scoring fixture, and is deliberately not claimed as "
        "covered."
    ),
    "comp_facet": (
        "No comp-bounded query: the corpus's disclosed bands are per-company and several "
        "are implausible, so a comp query would score against suspect ground truth."
    ),
    "int8_tier": (
        "Labels are tier-independent, but no int8 artifact has been measured, and a tier "
        "that was not run is never certified: see the eval's tiers_not_measured note."
    ),
}

_MUST_NOT = {
    "exact": [],
    "close": ["exact"],
    "related": ["exact", "close"],
    "irrelevant": ["exact", "close", "related"],
}


def _plain_title_key(text: str) -> str:
    """Case/whitespace-folded title, restated INDEPENDENTLY of `search.policy`.

    Deliberately not `policy.exact_title_key`: labels that import the module
    under test would make the "zero false exact" gate true by construction.
    This is the plain-English claim (same words, same order, ignoring case and
    spacing), so if the policy key ever drifts from it, the eval disagrees
    instead of agreeing.
    """
    folded = "".join(" " if ch.isspace() else ch for ch in unicodedata.normalize("NFKC", text or ""))
    return " ".join(folded.split()).strip(" ,;:|").casefold()


def _audit_labels(queries: list[dict], by_key: dict) -> list[str]:
    """Authoring guards. Every failure here is a mistake in THIS file."""
    problems: list[str] = []
    for q in queries:
        text = q["text"]
        # Kind and labels must agree: exact labels are exactly what direct
        # resolution finds, so an `exploratory` query with an exact label (or
        # an exact_title query without one) makes the zero-false-exact gate
        # untestable.
        has_exact = bool(q.get("labels", {}).get("exact", ([], ""))[0])
        if q["kind"] in ("identifier", "exact_title") and not has_exact:
            problems.append(f"{q['key']}: kind={q['kind']} but no exact label")
        if q["kind"] == "exploratory" and has_exact:
            problems.append(f"{q['key']}: kind=exploratory but carries an exact label")

    # Two queries whose conservative title keys are equal ARE the same query to
    # direct resolution; divergent labels would mean two ground truths for one
    # input.
    by_title_key: dict[str, list[dict]] = {}
    for q in queries:
        if q["kind"] != "identifier":
            by_title_key.setdefault(_plain_title_key(q["text"]), []).append(q)
    for group in by_title_key.values():
        if len(group) < 2:
            continue
        maps = [
            {pk: cls for cls, (pks, _) in q.get("labels", {}).items() for pk in pks}
            for q in group
        ]
        if any(m != maps[0] for m in maps[1:]):
            names = ", ".join(q["key"] for q in group)
            problems.append(f"same-title-key queries disagree on labels: {names}")
        for pk in q.get("labels", {}).get("exact", ([], ""))[0]:
            row = by_key[pk]
            if q["kind"] == "identifier":
                # Identity is by URL or complete req id, never by title.
                if text.startswith("@url:") or (row["url"] and row["url"] in text):
                    continue
                if text.strip() == (row["req_id"] or ""):
                    continue
                problems.append(f"{q['key']}: {pk} labelled exact but query is neither its URL nor its req_id")
            elif _plain_title_key(text) != _plain_title_key(row["title"]):
                problems.append(
                    f"{q['key']}: {pk} labelled exact but titles differ\n"
                    f"    query={_plain_title_key(text)!r}\n"
                    f"    row  ={_plain_title_key(row['title'])!r}"
                )
    return problems


async def build() -> dict:
    keys = [_k(c, r) for c, r in POSTINGS]
    if len(set(keys)) != len(keys):
        raise SystemExit(f"duplicate posting keys: {keys}")

    async with session_scope() as session:
        rows = (
            await session.execute(
                text(
                    "select company, req_id, id, title, url, department, team, "
                    "description_text, level_band, family, track, domains "
                    "from jobs where req_id = any(:reqs)"
                ),
                {"reqs": [r for _, r in POSTINGS]},
            )
        ).mappings().all()
    # req_id is unique within a company; key on the full (company, req_id).
    by_key = {_k(r["company"], r["req_id"]): r for r in rows}
    missing = [k for k in keys if k not in by_key or not by_key[k]["description_text"]]
    if missing:
        raise SystemExit(f"postings missing or without description: {missing}")

    postings = []
    for c, r in POSTINGS:
        row = by_key[_k(c, r)]
        postings.append(
            {
                "key": _k(c, r),
                "company": row["company"],
                "req_id": row["req_id"],
                "source_job_id": row["id"],
                "title": row["title"],
                "url": row["url"],
                # Employer category fields: the weighted search_vector's B tier
                # (db/repo.SEARCH_VECTOR_SQL). Frozen so the eval's shadow table
                # can build the production vector, not an approximation of it.
                "department": row["department"],
                "team": row["team"],
                "level_band": row["level_band"],
                "family": row["family"],
                "track": row["track"],
                "domains": list(row["domains"] or []),
                # Exactly the (title + description) composition embed_jobs uses.
                "doc_text": f"{row['title'] or ''}\n{row['description_text'] or ''}",
            }
        )

    # `@url:<posting_key>` resolves to that row's stored URL, so an identifier
    # query cannot drift from the row it is supposed to identify.
    for q in QUERIES:
        if q["text"].startswith("@url:"):
            q["text"] = by_key[q["text"][len("@url:"):]]["url"]

    problems = _audit_labels(QUERIES, by_key)

    # A "semantic intent" query must actually need the vector: `search_vector`
    # is to_tsvector(title || description), so if FTS already finds the target
    # the query is measuring lexical retrieval under a misleading cohort name.
    async with session_scope() as session:
        for q in QUERIES:
            if q["cohort"] != "semantic_intent":
                continue
            targets = q.get("labels", {}).get("close", ([], ""))[0]
            for pk in targets:
                hit = await session.scalar(
                    text(
                        "select search_vector @@ websearch_to_tsquery('english', :q) from jobs"
                        " where company = :c and req_id = :r"
                    ),
                    {"q": q["text"], "c": by_key[pk]["company"], "r": by_key[pk]["req_id"]},
                )
                if hit:
                    problems.append(
                        f"{q['key']}: {pk} is found LEXICALLY — not a semantic-intent case. "
                        f"Reword to share no stemmed term with the posting."
                    )
    if problems:
        raise SystemExit("label audit failed:\n  " + "\n  ".join(problems))

    queries = []
    labels = []
    for q in QUERIES:
        listed: set[str] = set()
        for cls, (pkeys, reason) in q.get("labels", {}).items():
            for pk in pkeys:
                if pk not in by_key:
                    raise SystemExit(f"query {q['key']}: unknown posting {pk}")
                if pk in listed:
                    raise SystemExit(f"query {q['key']}: posting {pk} labelled twice")
                listed.add(pk)
                labels.append(
                    {
                        "query": q["key"],
                        "posting": pk,
                        "class": cls,
                        "must_not_class": _MUST_NOT[cls],
                        "reason": reason,
                    }
                )
        # Every unlisted posting is an explicit irrelevant for this query.
        for pk in keys:
            if pk not in listed:
                labels.append(
                    {
                        "query": q["key"],
                        "posting": pk,
                        "class": "irrelevant",
                        "must_not_class": _MUST_NOT["irrelevant"],
                        "reason": "not labelled relevant for this query",
                    }
                )
        queries.append(
            {
                "key": q["key"],
                "cohort": q["cohort"],
                "kind": q["kind"],
                "text": q["text"],
                # True when the labels encode a STRUCTURED-FILTER fact (company,
                # location, workplace) rather than a role-shape/mission claim.
                # `TitleSignature` has no company axis by design: those
                # facets are filters applied in retrieval, so the wrong-company
                # rows never reach the classifier. The end-to-end eval applies
                # the filters and scores these; the pure policy test must not.
                "filter_dependent": bool(q.get("filter_dependent")),
                **({"note": q["note"]} if q.get("note") else {}),
            }
        )

    return {
        "version": 1,
        "frozen_at": "2026-08-16",
        "embedding_model": "lightonai/DenseOn",
        "embedding_dim": 768,
        "note": (
            "Authored ground truth for search retrieval. "
            "Posting fields/text frozen from the live corpus; labels hand-authored; scores are "
            "recomputed by scripts.eval_search_retrieval through production embed seams. "
            "This is a hard-gate SEED; see cohort_todo."
        ),
        "cohort_todo": COHORT_TODO,
        "postings": postings,
        "queries": queries,
        "labels": labels,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite an existing fixture")
    args = parser.parse_args()
    if FIXTURE.exists() and not args.force:
        raise SystemExit(
            f"{FIXTURE} exists; re-freezing invalidates recorded baselines. Use --force deliberately."
        )
    fixture = asyncio.run(build())
    FIXTURE.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n")
    n_pairs = len(fixture["labels"])
    by_cls: dict[str, int] = {}
    for lab in fixture["labels"]:
        by_cls[lab["class"]] = by_cls.get(lab["class"], 0) + 1
    print(
        f"wrote {FIXTURE}: {len(fixture['postings'])} postings, "
        f"{len(fixture['queries'])} queries, {n_pairs} labelled pairs {by_cls}"
    )


if __name__ == "__main__":
    main()
