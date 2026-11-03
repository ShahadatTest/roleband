"""Employer ladders and numbered engineering rungs.

Contracts:
- A numeral right after "Engineer" names the employer's numbered rung
  (MongoDB 2 = its new-grad rung, Elastic and Rocket Lab I = entry, II or 3 =
  mid), and only where no other rung word is in the head: "Principal Software
  Engineer I" is a Principal, "Senior Engineer II" a Senior.
- A number outside engineering is not a rung ("Senior Specialist 2").
- No per-band pay lookup moves before the one switch: every priced band of a
  new ladder reads its pay by the band word.
- Pay facts land only where an employer source states them.
"""

from __future__ import annotations

import pytest

from tracker.enrich.classify import classify_family
from tracker.enrich.level_mapper import read_level
from tracker.levels.ladder import senior_unconfirmed, walk_guide
from tracker.levels.pay import bonus_ratio_for, pay_label, policy_for
from tracker.levels.titles import PROFILES
from tracker.schema import LevelBand, LevelBasis, RawJob

BATCH = (
    "waymo", "zoox", "zipline", "rocket-lab", "roblox", "palantir", "mongodb", "elastic",
    "asml", "synopsys", "electronic-arts", "wise",
    "jane-street", "susquehanna-international-group", "drw", "imc-trading", "optiver", "jump-trading",
    "hugging-face", "runway", "ami-labs", "lovable", "notion", "linear",
    "crowdstrike", "sentinelone", "1password", "vercel", "wiz",
    "xai", "mistral", "scaleai", "perplexity", "cohere",
    "datadog", "cloudflare", "gitlab", "grafana-labs", "doordash", "lyft", "pinterest", "snap", "instacart",
    "atlassian", "github", "docker", "hashicorp", "confluent", "twitch", "unity", "supercell", "discord",
    "valve", "riot-games", "epic-games", "take-two-interactive", "nintendo", "paypal", "block", "robinhood",
    "plaid", "brex", "ramp", "adyen", "klarna", "revolut", "tower-research-capital", "hudson-river-trading",
    "two-sigma", "xtx-markets", "citadel", "citadel-securities", "samsara", "skydio", "nuro", "aurora", "figure",
    "tesla", "boston-consulting-group", "bain-company", "roland-berger", "mckinsey-company", "oliver-wyman",
    "asana", "dropbox", "gusto", "meta", "flexport", "adobe", "shopify", "booking", "uber",
)


def _read(company: str, title: str):
    job = RawJob(company=company, req_id="", title=title, url="")
    return read_level(job, classify_family(job))


@pytest.mark.parametrize(("company", "title", "band"), [
    ("mongodb", "Software Engineer 2", "entry"),
    ("mongodb", "Software Engineer 3, Atlas Clusters", "mid"),
    ("mongodb", "Site Reliability Engineer 3", "mid"),
    ("elastic", "Software Engineer I - AI Observability", "entry"),
    ("elastic", "Software Engineer II - Full Stack - Web Engineering", "mid"),
    ("rocket-lab", "Electrical Engineer I", "entry"),
    ("rocket-lab", "Software Engineer II", "mid"),
    ("electronic-arts", "Software Engineer I", "entry"),
    ("electronic-arts", "Software Engineer II - Gameplay", "mid"),
    ("electronic-arts", "Software Engineer III", "senior"),  # posted on the Senior range
    ("crowdstrike", "Engineer III, Cloud Security", "mid"),  # below Sr. at CrowdStrike
    ("crowdstrike", "Engineer II, Full Stack", "mid"),
    ("adobe", "Software Development Engineer 4", "senior"),  # "Software Engineer 4 (P40)"
    ("adobe", "Software Development Engineer 3 - Frontend", "mid"),
    ("adobe", "Software Developer Engineer 3/4", "mid"),  # a dual req reads its lower rung
    ("booking", "Booking Holdings Romania - Software Engineer I", "entry"),
    ("twitch", "Software Engineer I, Payments", "entry"),
    ("twitch", "Software Development Engineer III", "senior"),  # Amazon's SDE III
    ("pinterest", "University Grad Software Engineer 2027 (USA)", "entry"),
    ("pinterest", "Software Engineer II, Web", "mid"),
    # Snap prints its level in the last segment: read over the whole title.
    ("snap", "Software Engineer, ML Infrastructure, Content Retrieval Platform, Level 4", "mid"),
    ("snap", "Software Engineer, Level 5", "senior"),
    ("snap", "Staff Software Engineer, Backend, Level 6", "staff"),
    # Printed codes read over the whole title, outranking its words.
    ("applied-materials", "Process and Technology Engineer - (E3)", "senior"),
    ("applied-materials", "Supplier Engineer IV - (E4)", "staff"),
    ("applied-materials", "Application Engineer V - (E5)", "principal"),
    ("applied-materials", "Software Engineer II Senior - (E2)", "mid"),  # the grade, not the word "Senior"
    ("salesforce", "Software Engineering MTS", "mid"),
    ("salesforce", "Senior (SMTS) Endpoint Security Software  Engineer", "senior"),
    ("salesforce", "Software Engineering PMTS - Search & Personalization", "principal"),
    ("salesforce", "Software Engineering AMTS (College Grad)", "entry"),
    ("salesforce", "Lead Member of Technical Staff, Platform", "staff"),
    ("salesforce", "Senior Member of Technical Staff, Data Cloud", "senior"),  # not read as plain MTS
    ("amd", "PMTS - DFT Architect", "principal"),
    ("amd", "SMTS Silicon Design Engineer", "principal"),  # not read as plain MTS
    ("amd", "MTS Software Development Engineer - GPU Compilers", "staff"),
    ("amd", "GPU Kernel Development Engineer - Fellow", "director_plus"),
    ("amd", "Sr. Fellow - Software Architect - EDA Software Development", "director_plus"),
    ("wise", "Senior Software Engineer (IC3 - Backend)", "senior"),
    ("wise", "Senior Product Analyst (IC2), SEND", "mid"),  # the code, not the word "Senior"
    ("wise", "Lead Engineer (IC4)", "staff"),
    ("salesforce", "LMTS and SMTS, Software Engineering", "senior"),  # a dual req reads its lower rung
    ("salesforce", "LMTS & SMTS, Software Engineering", "senior"),
])
def test_a_numbered_engineering_rung_is_the_employers(company, title, band):
    reading = _read(company, title)
    assert (reading.band.value, reading.basis) == (band, LevelBasis.COMPANY)


@pytest.mark.parametrize(("company", "title", "band"), [
    ("elastic", "Principal Software Engineer I", "principal"),
    ("elastic", "Principal Software Engineer II", "principal"),
    ("elastic", "Distinguished Engineer I", "director_plus"),
    ("rocket-lab", "Senior Software Engineer I", "senior"),
    ("rocket-lab", "Senior Software Engineer II", "senior"),
    ("mongodb", "Senior Staff Engineer", "principal"),
    ("electronic-arts", "Senior Software Engineer II", "senior"),
    ("wise", "Senior Software Engineer II", "senior"),  # one word, one band
])
def test_a_rung_word_beside_the_numeral_decides(company, title, band):
    assert _read(company, title).band.value == band


@pytest.mark.parametrize(("company", "title", "rung"), [
    ("amd", "Senior Fellow, Server Product Architecture", "Senior Fellow"),
    ("amd", "Fellow, Server Product Architecture", "Fellow"),
    ("wise", "Software Engineer (IC25)", None),  # a longer code is not IC2
    ("wise", "Software Engineer (IC2)", "IC2"),
])
def test_a_printed_code_inside_a_longer_one_is_not_the_shorter_one(company, title, rung):
    from tracker.levels.titles import rank_for_title

    found = rank_for_title(company, title)
    assert (found.rung if found is not None else None) == rung


@pytest.mark.parametrize(("company", "title"), [
    ("amd", "Senior Software Development Engineer"),
    ("wise", "Staff Software Engineer"),
])
def test_an_uncoded_title_reads_its_words(company, title):
    assert _read(company, title).basis is LevelBasis.GENERIC


def test_a_number_outside_engineering_is_no_rung():
    assert _read("mongodb", "Senior Specialist 2").band is LevelBand.SENIOR
    assert _read("mongodb", "Product Manager 2").basis is not LevelBasis.COMPANY


def test_another_company_keeps_its_reading():
    # The rule is MongoDB's: elsewhere "Engineer 2" states no level.
    assert _read("datadog", "Software Engineer 2").basis is LevelBasis.NONE
    assert "datadog" not in PROFILES


@pytest.mark.parametrize("company", BATCH)
def test_no_pay_lookup_moves_before_the_switch(company):
    for band in (LevelBand.SENIOR, LevelBand.STAFF, LevelBand.PRINCIPAL, LevelBand.DIRECTOR_PLUS):
        # A band with no rung of its own reads the nearest rung below
        # (Rocket Lab's staff reads Senior II): that rung is pinned too.
        label = pay_label(company, band)
        assert label is None or label in {b.value for b in LevelBand}, f"{company}/{band.value}: {label}"


@pytest.mark.parametrize("company", BATCH)
def test_every_batch_company_is_in_the_walk_guide(company):
    assert walk_guide(company)


def test_pay_facts_stand_on_employer_statements():
    assert policy_for("elastic").bonus_rule == "none"  # "does not have a variable compensation component"
    assert policy_for("mongodb").vesting == "25/25/25/25"  # 10-K: 25% at one year, then quarterly
    assert policy_for("roblox").vesting == "33/33/33"  # 10-K: three years for grants after July 2022
    assert policy_for("spotify").equity_rule == "employee_election"  # 20-F: the employee picks the mix
    assert policy_for("shopify").equity_rule == "employee_election"  # Flex Comp: the employee picks the split
    assert policy_for("shopify").vesting == "33/33/33"  # 6-K: monthly over three years, no cliff
    assert policy_for("meta").annual_refresh is True  # proxy: refresher awards to all employees
    assert policy_for("block").bonus_rule == "none"  # proxy: no company-wide cash incentive plan
    assert policy_for("block").vesting == "25/25/25/25"  # candidate FAQ: quarterly, no cliff
    assert policy_for("atlassian").vesting == "25/25/25/25"  # 10-K: quarterly, no cliff
    assert policy_for("klarna").vesting == "25/25/25/25"  # 20-F: 25% each year
    assert policy_for("gitlab").annual_refresh is True  # handbook: reviewed for a refresh yearly
    assert policy_for("instacart").annual_refresh is True  # postings: "annual refresh grants"
    assert policy_for("cohere").equity_vehicle == "options"  # careers page: "Equity / stock options"
    assert policy_for("linear").equity_vehicle == "options"  # postings: early exercise
    assert policy_for("asml").vesting == "0/0/100"  # 20-F: one vest after 2.5 to 3 years
    # Stated nowhere by the employer: stays unverified.
    assert policy_for("palantir").bonus_rule == "unverified"
    assert policy_for("waymo").vesting is None


def test_pay_policy_batch_stands_on_filings_proxies_and_postings():
    assert policy_for("microsoft").vesting == "25/25/25/25"  # 10-K: "vest ratably over ... four years"
    assert policy_for("micron").vesting == "25/25/25/25"  # 10-K: 25% after a year, then 6.25% a quarter
    assert policy_for("mongodb").annual_refresh is True  # 10-K: "an annual performance-related refresh"
    assert policy_for("uber").annual_refresh is True  # proxy: annual equity awards to all employees in March
    assert policy_for("broadcom").annual_refresh is True  # 10-K: annual employee equity awards in Q2
    assert policy_for("qualcomm").annual_refresh is True  # postings: "opportunity for annual RSU grants"
    assert policy_for("google-deepmind").bonus_rule == "pct_of_base"  # postings: "+ 20% bonus target"
    # A schedule is recorded only where the employer says ratable or equal, in its latest filing.
    # Not employer-stated (no "ratable" or "equal"); these ship as estimated where 3+
    # independent sources agree; other values stay empty.
    assert policy_for("crowdstrike").stated_by("vesting") == "estimated"
    assert policy_for("dropbox").stated_by("vesting") == "estimated"
    assert policy_for("synopsys").stated_by("vesting") == "estimated"
    assert policy_for("lyft").vesting is None  # the latest 10-K says only "up to four years"
    assert policy_for("nvidia").vesting is None  # no employer statement or filing gives it
    # A bonus is pct_of_base only where employees' bonus is stated as a share of base.
    assert policy_for("snap").stated_by("bonus_rule") == "estimated"  # engineers report 10-15% of base
    assert policy_for("waymo").bonus_rule == "unverified"  # a discretionary bonus with no % is no rule


def test_deepmind_bonus_reads_its_posted_targets():
    # Its postings print "+ N% bonus target": 15-20% at senior, 20% at staff, 25% at principal.
    # The policy reads the parent's rung targets, not a heuristic.
    assert 0.15 <= bonus_ratio_for("google-deepmind", LevelBand.SENIOR) <= 0.20
    assert 0.20 <= bonus_ratio_for("google-deepmind", LevelBand.STAFF) <= 0.25
    assert 0.25 <= bonus_ratio_for("google-deepmind", LevelBand.PRINCIPAL) <= 0.30


def test_synopsys_senior_is_unconfirmed():
    # Its "Sr Engineer" asks 1-3 years: the word reads senior, never confirmed.
    assert senior_unconfirmed("synopsys")
    assert _read("synopsys", "Sr Engineer, Physical Design").confidence.value == "unconfirmed"


def test_a_pinned_ladder_keeps_every_bands_own_word():
    # SIG's ladder tops out at Senior: staff and principal read the Senior rung,
    # but retain their own pay lookup word. Senior's word
    # must not become a match for a staff lookup.
    sig = "susquehanna-international-group"
    assert [pay_label(sig, b) for b in (LevelBand.SENIOR, LevelBand.STAFF, LevelBand.PRINCIPAL)] == [
        "senior", "staff", "principal"]
    # A flat ladder retains the title word for pay lookup too.
    assert pay_label("jane-street", LevelBand.STAFF) == "staff"


def test_an_unpinned_ladder_reads_its_rung_label():
    # Amazon has no Staff rung and keys pay by its own codes: staff reads SDE III.
    assert pay_label("amazon", LevelBand.STAFF) == "SDE III"
    assert pay_label("microsoft", LevelBand.STAFF) == "64"


def test_a_flat_firm_reads_no_rung_from_a_plain_title():
    assert _read("jane-street", "Software Engineer").basis is LevelBasis.NONE


def test_a_printed_level_outranks_the_title_word():
    # Snap prints "Level 6" on a Principal-worded scientist title: the employer's level stands,
    # as a printed code does; a title with no printed level reads its words.
    assert _read("snap", "Principal Marketing Scientist, Level 6").band is LevelBand.STAFF
    assert _read("snap", "Principal Software Engineer, Ads Format").band is LevelBand.PRINCIPAL
    assert _read("snap", "Software Engineering Intern, Level 3").band is LevelBand.INTERN


def test_a_consulting_firm_ladders_its_ranks_company_wide():
    # A firm's rank applies to every role it hires, so its ladder is the company row.
    from tracker.levels.ladder import ladder_for
    for firm in ("boston-consulting-group", "bain-company", "mckinsey-company", "oliver-wyman", "roland-berger"):
        assert ladder_for(firm).family == "company"
    assert [r.code for r in ladder_for("boston-consulting-group").rungs] == [
        "Associate", "Consultant", "Project Leader", "Principal", "Partner"]


def test_pay_policy_sweep_lands_only_what_clears_the_bar():
    # Employer statements: the employer says it of employees.
    assert policy_for("okta").bonus_rule == "pct_of_base"  # rewards site: % of base by job level
    assert policy_for("okta").stated_by("bonus_rule") == "employer"
    assert policy_for("gitlab").bonus_rule == "pct_of_base"  # handbook: 10% below Director
    assert policy_for("arm").bonus_rule == "none"  # bonus plan covers the leadership team only
    assert policy_for("adyen").bonus_rule == "none"  # US pay doc: bonus only for sales roles
    assert policy_for("tsmc").equity_rule == "none"  # restricted stock only for executives
    assert policy_for("revolut").vesting == "25/25/25/25"  # annual report: 25% each anniversary
    assert policy_for("netflix").stated_by("equity_vehicle") == "employer"  # The employee elects the mix yearly.
    # Estimated: 3+ independent sources, score above 1.0, evidence against at most half.
    assert policy_for("meta").vesting == "25/25/25/25" and policy_for("meta").stated_by("vesting") == "estimated"
    assert policy_for("databricks").vesting == "40/30/20/10"
    # A dollar-to-shares conversion never makes "by level" an employer statement.
    assert policy_for("servicenow").stated_by("equity_rule") == "estimated"
    # One-year grants wait for a format; below-the-bar facts stay empty.
    for company in ("coinbase", "stripe", "asana", "netflix"):
        assert policy_for(company).vesting is None, company
    assert policy_for("broadcom").vesting is None  # "over four years", cadence disputed
    assert policy_for("twitch").bonus_rule == "unverified"  # rests on a posting's omission
    assert policy_for("palo-alto-networks").vesting is None  # 1.3, an executive grant is 40/30/20/10


def test_unreadable_printed_codes_stay_unread():
    # Applied Materials' manager codes have no employer mapping to its E grades: the code
    # decides nothing, so the title reads as it would without the code.
    from tracker.levels.titles import rank_for_title

    assert rank_for_title("applied-materials", "Mechanical Engineering Manager (M5)") is None
    assert rank_for_title("applied-materials", "Process Engineer E3 Lab") is None  # unparenthesised: not the grade
    assert rank_for_title("salesforce", "Systems Engineer, Customer Success") is None


@pytest.mark.parametrize(("code", "band"), [("IC3", "mid"), ("IC5", "staff"), ("IC6", "principal"), ("IC7", "principal")])
def test_dropbox_reads_every_ic_code_its_board_prints(code, band):
    # Its "Dropboxer Level" field prints the IC rung; the published framework bands it.
    job = RawJob(company="dropbox", req_id="", title="Product Manager", url="", raw_level=code)
    reading = read_level(job, classify_family(job))
    assert (reading.band.value, reading.basis) == (band, LevelBasis.STATED)
