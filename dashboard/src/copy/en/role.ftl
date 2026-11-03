## role: moved as it was found (wording=as-is)

## features/job-detail/JobCompPanel.tsx
# kind=label wording=as-is
role-job-comp-panel-the-employer-s-exact-words = The employer's exact words
# kind=sentence wording=as-is
role-job-comp-panel-no-compensation-data-for-this = No compensation data for this role.
# kind=label wording=as-is
role-job-comp-panel-market-median-at-this-level = Market median at this level
# kind=sentence
role-job-comp-panel-this-package-is-the-market = This estimate is { $toFixed }× the market median for this level, usually a sign the level or the discipline is wrong.
# kind=label wording=as-is
role-job-comp-panel-base = Base
# kind=sentence wording=as-is
role-job-comp-panel-base-salary-stated-in-the = Base salary stated in the posting.
# kind=sentence
role-job-comp-panel-this-employer-publishes-no-pay = This employer posts no range. Everything below is an estimate.
# kind=sentence
role-job-comp-panel-we-have-not-checked-this = This posting hasn't been checked for a posted range yet.
# kind=label wording=as-is
role-job-comp-panel-stated = stated
# kind=label wording=as-is
role-job-comp-panel-estimated = estimated
# kind=status
role-job-comp-panel-our-independent-estimate-of-total = Independent estimate of total compensation: { $range }
# kind=label note="Beside an employer's stated pay while a plugin answers pay: the plugin's estimate, never called ours"
role-job-comp-panel-estimate-of-total = Estimated total compensation: { $range }
# kind=sentence
role-job-comp-panel-from-the-posting-s-pay = From the posting's compensation field, not its text.
# kind=label wording=as-is
role-job-comp-panel-bonus = Bonus
# kind=label wording=as-is
role-job-comp-panel-equity = Equity
# kind=label wording=as-is
role-job-comp-panel-cash-every-month = cash, every month
# kind=label wording=as-is
role-job-comp-panel-target-not-guaranteed = target, not guaranteed
# kind=label wording=as-is
role-job-comp-panel-per-year-vests-over-time = per year, vests over time
# kind=label wording=as-is
role-job-comp-panel-measured-split = Measured split
# kind=label wording=as-is
role-job-comp-panel-split-from-another-discipline = Split from another discipline
# kind=label wording=as-is
role-job-comp-panel-estimated-split = Estimated split
# kind=label wording=as-is
role-job-comp-panel-this-company-s-real-base = This company's real base/bonus/equity split for this level and discipline
# kind=label wording=as-is
role-job-comp-panel-no-measured-split-for-this = No measured split for this discipline: scaled from this company's numbers for the same level in another discipline
# kind=label wording=as-is
role-job-comp-panel-no-measured-split-for-this-2 = No measured split for this company: using the seniority heuristic
# kind=sentence
role-job-comp-panel-posted-band-sits-well-above = The posted range sits well above this company's measured { $band } base salary, so the level may be higher.
# kind=sentence
role-job-comp-panel-posted-band-sits-well-below = The posted range sits well below this company's measured { $band } base salary, so the level may be lower.
# kind=toast
role-job-comp-panel-you-choose-the-cash-stock = You choose the cash / equity mix
# kind=toast
role-job-comp-panel-equity-fills-a-per-level = Equity fills a per-level total compensation target
# kind=toast wording=as-is
role-job-comp-panel-equity-is-a-dollar-grant = Equity is a dollar grant sized by level
# kind=toast wording=as-is
role-job-comp-panel-vests = { $choice ->
    [yes] vests { $vesting }, sign-on cash bridges years 1–2
   *[no] vests { $vesting }
}
# kind=toast wording=as-is
role-job-comp-panel-no-annual-bonus = no annual bonus
# kind=toast wording=as-is
role-job-comp-panel-bonus-is-a-level-set = bonus is a level-set % of base
# kind=toast wording=as-is
role-job-comp-panel-base-capped-at = base capped at { $base_cap_usd }
# kind=label wording=as-is
role-job-comp-panel-yr = / yr
# kind=label wording=as-is
role-job-comp-panel-mo = / mo
# kind=label wording=as-is
role-job-comp-panel-hr = / hr
# kind=label wording=as-is
role-job-comp-panel-hourly-rate = hourly rate
# kind=sentence
role-job-comp-panel-the-posting-gives-an-hourly = The posting gives an hourly rate, shown as stated.
# kind=label wording=as-is
role-job-comp-panel-monthly-rate = monthly rate
# kind=sentence
role-job-comp-panel-the-posting-gives-a-monthly = The posting gives a monthly rate, shown as stated.
# kind=label wording=as-is
role-job-comp-panel-period-unclear = period unclear
# kind=sentence
role-job-comp-panel-the-posting-s-wording-and = The posting's wording and the size of this figure disagree, so it's unclear whether it's paid by the hour, the month or the year. Read the employer's own words below.
# kind=sentence wording=as-is
role-job-comp-panel-states-this-as-total-annual = { $company } states this as total annual compensation with no bonus. Employees choose how much is salary versus stock options, so there is no fixed cash/equity split to show.
# kind=label note="Tag on an employer's pay figure that is not split: each employee chooses how much is salary and how much is stock"
role-job-comp-panel-employee-selected-mix = employee-selected mix
# kind=label wording=as-is
role-job-comp-panel-total-compensation = total compensation
# kind=sentence
role-job-comp-panel-the-posting-states-total-compensation = The posting states total compensation without a breakdown, so none is shown.
# kind=label wording=as-is
role-job-comp-panel-basis-not-stated = basis not stated
# kind=sentence
role-job-comp-panel-the-posting-states-this-figure = The posting doesn't say whether this figure is base salary or total compensation, so it isn't split into base, bonus and equity.
# kind=label note="No base, bonus and stock split for this level: the plugin answering pay states none, or the role's pay is outside the US pay RoleBand splits"
role-job-comp-panel-split-not-reported = split unavailable
# kind=sentence note="A plugin answers pay; RoleBand's own split is never put under its figure"
role-job-comp-panel-the-plugin-reports-no-split = The plugin that supplies compensation gives a figure for this level but not how it divides into base, bonus and equity, so it is not split.
# kind=sentence note="RoleBand's own split is measured on US pay; this posting is in another country, or names places in several"
role-job-comp-panel-roleband-splits-us-pay-only = Compensation is split into base, bonus and equity from US data only. This role is outside the US or in several countries, so it isn't split.
# kind=label note="A plugin answers pay app-wide and has not read this posting's company yet"
role-job-comp-panel-not-read-yet = not read yet
# kind=label wording=as-is
role-job-comp-panel-no-estimate-available = No estimate available
# kind=label
role-job-comp-panel-estimated-total-package = { $choice ->
    [yes] Posted total compensation
   *[no] Estimated total compensation
}
# kind=label
role-job-comp-panel-estimated-total-comp = Estimated total compensation
# kind=label wording=as-is
role-job-comp-panel-stated-by-the-employer = Stated by the employer
# kind=aria
role-job-comp-panel-about-stated-base-salary = About the posted base salary
# kind=label wording=as-is
role-job-comp-panel-of-base-stated = { $round }% of base, stated

## features/job-detail/JobDescription.tsx
# kind=sentence wording=as-is
role-job-description-no-description-captured = No description captured.

## features/job-detail/JobDetail.tsx
# kind=button wording=as-is
role-job-detail-back = Back
# kind=label wording=as-is
role-job-detail-1-in-compare-pick-one = 1 in compare · pick one more
# kind=button wording=as-is
role-job-detail-compare-roles = Compare { $compareCount } roles
# kind=link wording=as-is
role-job-detail-view-apply = View & apply
# kind=label wording=as-is
role-job-detail-postings = { $lineage_size } postings
# kind=label wording=as-is
role-job-detail-reposted = reposted ×{ $repost_count }
# kind=label wording=as-is
role-job-detail-description = Description
# kind=label wording=as-is
role-job-detail-your-progress = Your progress
# kind=label wording=as-is
role-job-detail-set-a-stage = Set a stage…
# kind=sentence note="Under the stage select before any stage is picked: what picking one does"
role-job-detail-tracking-explainer = Pick a stage to track this role: it is saved, Saved shows its stage, and a follow-up date you set later reminds you when it is due.
# kind=label wording=as-is
role-job-detail-next = Next: { $next_action }
# kind=label wording=as-is
role-job-detail-radar-s-read = Radar's read
# kind=sentence note="Radar's read, when the posting's wording sits between worlds"
role-job-detail-advisory-unclear = The posting's wording doesn't clearly match one world.
# kind=sentence note="Foot of Radar's read: where the guess comes from, and that it hides nothing"
role-job-detail-advisory-basis = A guess from the posting's wording. It never takes a role off your radar.
# kind=label wording=as-is
role-job-detail-details = Details
# kind=label wording=as-is
role-job-detail-team = Team
# kind=label wording=as-is
role-job-detail-workplace = Workplace
# kind=label wording=as-is
role-job-detail-status = Status
# kind=label wording=as-is
role-job-detail-to-apply = To apply
# kind=label wording=as-is
role-job-detail-more-like-this = More like this
# kind=label wording=as-is
role-job-detail-other-companies = Other companies
# kind=label wording=as-is
role-job-detail-same-company = Same company · { $company }
# kind=toast
role-job-detail-could-not-unsave-this-role = { $choice ->
    [yes] Couldn't save this role
   *[no] Couldn't remove this role from Saved
}
# kind=label wording=as-is
role-job-detail-couldn-t-update-the-stage = Couldn't update the stage
# kind=label wording=as-is
role-job-detail-role = { $choice ->
    [yes] Role: { $title }
   *[no] Role
}
# kind=aria wording=as-is
role-job-detail-back-2 = Back
# kind=label wording=as-is
role-job-detail-compare-is-full-max = Compare is full (max { $compareCap })
# kind=label wording=as-is
role-job-detail-compare = { $choice ->
    [yes] In compare
   *[no] Compare
}
# kind=sentence
role-job-detail-it-s-no-longer-in = This role no longer exists.
# kind=label wording=as-is
role-job-detail-not-started = { $choice ->
    [yes] Stage
   *[no] Not started
}
# kind=aria wording=as-is
role-job-detail-stage = Stage
# kind=label wording=as-is
role-job-detail-likely-your-kind-of-role = Likely your kind of role
# kind=label wording=as-is
role-job-detail-likely-outside-your-worlds = Likely outside your worlds
# kind=label wording=as-is
role-job-detail-hard-to-place = Hard to place
# kind=tooltip wording=as-is
role-job-detail-questions-the-employer-added-beyond = Questions the employer added beyond name, contact and resume, read from the posting page
# kind=tooltip wording=as-is
role-job-detail-similarity = Similarity

## features/job-detail/JobRequirementsPanel.tsx
# kind=sentence
role-job-requirements-panel-no-explicit-skill-requirements-found = No explicit skill requirements found in this posting. That means none matched the known skills, not that the role needs no skills.
# kind=label wording=as-is
role-job-requirements-panel-core-skills = Core skills
# kind=label wording=as-is
role-job-requirements-panel-supporting = Supporting
# kind=button wording=as-is
role-job-requirements-panel-show-more = Show { $value } more
# kind=label wording=as-is
role-job-requirements-panel-industry = Industry
# kind=label wording=as-is
role-job-requirements-panel-qualifications = Qualifications
# kind=label wording=as-is
role-job-requirements-panel-ways-of-working = Ways of working
# kind=label wording=as-is
role-job-requirements-panel-role-requirements = Role requirements
# kind=heading wording=as-is
role-job-requirements-panel-what-this-role-asks-for = What this role asks for
# kind=sentence
role-job-requirements-panel-importance-reflects-how-strongly-this = Importance reflects how strongly this posting emphasizes each item: explicit requirements found in this posting, with the employer's exact wording. It says nothing about your own skills or chances.
# kind=label wording=as-is
role-job-requirements-panel-required = { $requiredYears } { $requiredYears2 } required
# kind=label wording=as-is
role-job-requirements-panel-core = { $core } core
# kind=label wording=as-is
role-job-requirements-panel-supporting-2 = { $supporting } supporting
# kind=label wording=as-is
role-job-requirements-panel-sources = { $count ->
    [one] { $sources } source
   *[other] { $sources } sources
}
# kind=button wording=as-is
role-job-requirements-panel-show-in-description = Show in description
# kind=label wording=as-is
role-job-requirements-panel-required-2 = Required
# kind=label wording=as-is
role-job-requirements-panel-preferred = Preferred
# kind=label wording=as-is
role-job-requirements-panel-used-in-role = Used in role
# kind=label wording=as-is
role-job-requirements-panel-mentioned = Mentioned
# kind=label wording=as-is
role-job-requirements-panel-technology = Technology
# kind=label wording=as-is
role-job-requirements-panel-skill = Skill
# kind=label wording=as-is
role-job-requirements-panel-language = Language
# kind=label wording=as-is
role-job-requirements-panel-framework = Framework
# kind=label wording=as-is
role-job-requirements-panel-ml-ai = ML / AI
# kind=label wording=as-is
role-job-requirements-panel-cloud = Cloud
# kind=label wording=as-is
role-job-requirements-panel-data = Data
# kind=label wording=as-is
role-job-requirements-panel-infra = Infra
# kind=label wording=as-is
role-job-requirements-panel-security = Security
# kind=label wording=as-is
role-job-requirements-panel-process = Process
# kind=label wording=as-is
role-job-requirements-panel-leadership = Leadership
# kind=label wording=as-is
role-job-requirements-panel-collaboration = Collaboration
# kind=label wording=as-is
role-job-requirements-panel-years = { $count ->
    [one] year
   *[other] years
}
# kind=aria wording=as-is
role-job-requirements-panel-role-requirements-2 = Role requirements
# kind=sentence wording=as-is
role-job-requirements-panel-this-posting-has-no-stored = { $choice ->
    [yes] Analyzing requirements…
   *[no] This posting has no stored text to analyze.
}
# kind=label wording=as-is
role-job-requirements-panel-preferred-2 = { $choice ->
    [yes] Required
   *[no] Preferred
}
# kind=label wording=as-is
role-job-requirements-panel-show-evidence = { $choice ->
    [yes] Hide evidence
   *[no] Show evidence
}
# kind=aria wording=as-is
role-job-requirements-panel-ways-of-working-evidence = Ways of working evidence
# kind=label wording=as-is
role-job-requirements-panel-about-importance = About importance
# kind=label wording=as-is
role-job-requirements-panel-important = { $choice ->
    [yes] Core
   *[no] Important
}
# kind=sentence wording=as-is
role-job-requirements-panel-skill-sources-show-evidence = { $count ->
    [one] { $display }, { $bandLabel } { $modality } skill, { $sources } source. Show evidence.
   *[other] { $display }, { $bandLabel } { $modality } skill, { $sources } sources. Show evidence.
}
# kind=label wording=as-is
role-job-requirements-panel-requirement-sources = { $count ->
    [one] { $display }: { $bandLabel } requirement, { $modality }, { $sources } source
   *[other] { $display }: { $bandLabel } requirement, { $modality }, { $sources } sources
}
# kind=aria note="How strongly the posting stresses a skill, as $bandLabel inside the two screen-reader sentences above: Python, core required skill"
role-job-requirements-panel-importance-inline = { $band ->
    [core] core
   *[other] important
}
# kind=aria note="How the posting asks for a skill, as $modality inside the two screen-reader sentences above: Python, core required skill"
role-job-requirements-panel-modality-inline = { $modality ->
    [required] required
    [preferred] preferred
    [used_in_role] used in role
   *[context] mentioned
}
# kind=label wording=as-is
role-job-requirements-panel-title = Title

## features/job-detail/LineageDiff.tsx
# kind=label
role-lineage-diff-not-disclosed = not posted
# kind=label wording=as-is
role-lineage-diff-title-changed = Title changed
# kind=label wording=as-is
role-lineage-diff-level-changed = Level changed
# kind=label
role-lineage-diff-pay-band-newly-disclosed = { $choice ->
    [yes] Posted range moved
   *[no] Range newly posted
}
# kind=label
role-lineage-diff-pay-basis-changed = Posted range basis changed
# kind=label wording=as-is
role-lineage-diff-locations-changed = Locations changed
# kind=label wording=as-is
role-lineage-diff-estimate-changed = Estimate changed
# kind=aria wording=as-is
role-lineage-diff-changes-since-the-previous-posting = Changes since the previous posting

## features/job-detail/LineageStack.tsx
# kind=sentence
role-lineage-stack-could-not-load-posting-history = Couldn't load posting history. Try again.
# kind=label wording=as-is
role-lineage-stack-postings-of-this-role = { $size } postings of this role
# kind=label wording=as-is
role-lineage-stack-first-seen = first seen { $relDays }
# kind=label wording=as-is
role-lineage-stack-req = req { $req_id }
# kind=label wording=as-is
role-lineage-stack-locations = Locations
# kind=label
role-lineage-stack-comp-est = Est. TC
# kind=label wording=as-is
role-lineage-stack-first-seen-2 = First seen
# kind=label wording=as-is
role-lineage-stack-changes-from-the-previous-posting = Changes from the previous posting
# kind=aria wording=as-is
role-lineage-stack-posting-history = Posting history
# kind=aria wording=as-is
role-lineage-stack-previous-posting = Previous posting
# kind=aria wording=as-is
role-lineage-stack-postings = Postings
# kind=label note="A posting's dot in a role's posting history, for a screen reader; $role is role-lineage-stack-role, left out when the posting has none"
role-lineage-stack-posting = { $choice ->
    [yes] Posting { $seq }: { $role }
   *[no] Posting { $seq }
}
# kind=label note="What one posting of a role posted more than once is: the first, one posted again after an earlier one, or one listed while an earlier one was still open"
role-lineage-stack-role = { $role ->
    [original] original
    [duplicate] duplicate
   *[repost] reposted
}
# kind=label note="Badge on the posting shown in a role's posting history: what it is and its place in the order, original · #1"
role-lineage-stack-badge = { $choice ->
    [yes] { $role } · #{ $seq }
   *[no] #{ $seq }
}
# kind=aria wording=as-is
role-lineage-stack-next-posting = Next posting
# kind=label wording=as-is
role-lineage-stack-last-seen = { $choice ->
    [yes] Closed
   *[no] Last seen
}

## features/job-detail/ListingAge.tsx
# kind=label wording=as-is
role-listing-age-reading-the-history = Reading the history…
# kind=label wording=as-is
role-listing-age-couldn-t-read-the-history = Couldn't read the history.
# kind=button wording=as-is
role-listing-age-retry = Retry
# kind=label wording=as-is
role-listing-age-role-listed-for-across-postings = Role listed for { $days } across { $postings } postings.
# kind=button wording=as-is
role-listing-age-compare-the-postings = Compare the postings
# kind=label wording=as-is
role-listing-age-possibly-the-same-role-not = Possibly the same role: { $value }, not counted until confirmed.
# kind=button wording=as-is
role-listing-age-review = Review
# kind=label wording=as-is
role-listing-age-listed-for = Listed for
# kind=label wording=as-is
role-listing-age-since = since { $listed_since }, { $bASIS }
# kind=button wording=as-is
role-listing-age-history = History
# kind=label wording=as-is
role-listing-age-listing-history = Listing history
# kind=label wording=as-is
role-listing-age-role = Role
# kind=label wording=as-is
role-listing-age-first-listed-postings = First listed { $roleSince } · { $rolePostings } postings
# kind=label wording=as-is
role-listing-age-the-employer-s-date = the employer's date
# kind=label
role-listing-age-when-roleband-first-saw-it = when first seen
# kind=tooltip wording=as-is
role-listing-age-title = Title
# kind=label
role-listing-age-stated-pay = Posted range
# kind=label wording=as-is
role-listing-age-level = Level
# kind=label wording=as-is
role-listing-age-discipline = Discipline
# kind=label wording=as-is
role-listing-age-location = Location
# kind=label wording=as-is
role-listing-age-posting = Posting
# kind=label wording=as-is
role-listing-age-same-role-matched-automatically = { $choice ->
    [yes] same role, confirmed
   *[no] same role, matched automatically
}
# kind=label wording=as-is
role-listing-age-published-by-the-employer = Published by the employer
# kind=label wording=as-is
role-listing-age-the-start = the start
# kind=label same-as=role-lineage-stack-first-seen-2
role-listing-age-first-seen-by-roleband = First seen
# kind=label wording=as-is
role-listing-age-gone-from-the-careers-page = Gone from the careers page
# kind=label wording=as-is
role-listing-age-came-back-same-requisition = Came back, same requisition
# kind=label wording=as-is
role-listing-age-employer-changed-its-date-to = Employer changed its date to { $to_at }
# kind=label wording=as-is
role-listing-age-never-the-start = never the start
# kind=label wording=as-is
role-listing-age-an-earlier-posting-was-listed = { $choice ->
        [yes] Earlier posting { $posting } listed
       *[no] An earlier posting was listed
    }{ $choice2 ->
        [yes] , closed { $until }
       *[no] { "" }
    }
# kind=label wording=as-is
role-listing-age-reposted = { $choice ->
    [yes] Reposted as { $posting }
   *[no] Reposted
}
# kind=label wording=as-is
role-listing-age-still-listed-at-the-last = Still listed at the last scan
# kind=aria wording=as-is
role-listing-age-events = Events

## features/job-detail/PayFloorLine.tsx
# kind=status
role-pay-floor-line-clears-your-pay-floor = Clears your { $floor } minimum base
# kind=status
role-pay-floor-line-your-pay-floor-falls-inside = Your { $floor } minimum base falls inside this range
# kind=status
role-pay-floor-line-below-your-pay-floor = Below your { $floor } minimum base

## features/job-detail/PlaceSetSection.tsx
# kind=sentence
role-place-set-section-could-not-load-this-role = Couldn't load this role's other places. Try again.
# kind=label wording=as-is
role-place-set-section-you-marked-this-posting-as = You marked this posting as a different role from the same text at other places.
# kind=button wording=as-is
role-place-set-section-undo = Undo
# kind=sentence
role-place-set-section-same-title-and-the-same = Same title and the same description at each place, apart from the place and what comes with it (local compensation, benefits or legal text) or a few reworded words, so it counts as one role.
# kind=button wording=as-is
role-place-set-section-different-roles = Different roles
# kind=label wording=as-is
role-place-set-section-marked-as-a-different-role = Marked as a different role
# kind=label wording=as-is
role-place-set-section-undo-2 = Undo
# kind=toast
role-place-set-section-could-not-record-the-verdict = Couldn't record the verdict: { $message }
# kind=aria wording=as-is
role-place-set-section-also-listed-in = Also listed in
# kind=label wording=as-is
role-place-set-section-same-place = Same place
# kind=label wording=as-is
role-place-set-section-place-not-stated = Place not stated
# kind=label wording=as-is
role-place-set-section-listed = · listed { $listed_since }
# kind=status note="Beside a sibling posting: the base band it states, where it differs from this posting's"
role-place-set-section-states-pay = · posts { $range }
# kind=status note="Beside a sibling posting that states no pay while this posting states a band"
role-place-set-section-states-no-pay = · posts no range
# kind=sentence wording=as-is
role-place-set-section-a-second-posting-at-the = A second posting at the same place is the role listed again.
# kind=sentence wording=as-is
role-place-set-section-the-employer-files-them-all = The employer files them all under { $employer_label }.
# kind=label wording=as-is
role-place-set-section-other-places = { $count ->
    [one] 1 other place
   *[other] { $otherPlaces } other places
}
# kind=label wording=as-is
role-place-set-section-times-here = { $value } times here
# kind=label wording=as-is
role-place-set-section-also-listed-in-and = Also listed in { $places }, and { $times }
# kind=label wording=as-is
role-place-set-section-listed-2 = Listed { $times }
# kind=label wording=as-is
role-place-set-section-also-listed-in-2 = Also listed in { $places }

## features/job-detail/PostingReality.tsx
# kind=label wording=as-is
role-posting-reality-of-signs = { $length } of { $criteria_total } signs · { $sTANDING_HEDGE }

## features/job-detail/TwinDeck.tsx
# kind=sentence
role-twin-deck-could-not-load-twin-postings = Couldn't load twin postings for this role. Try again.
# kind=label wording=as-is
role-twin-deck-separate-roles-with-closely-related = Separate roles with closely related work
# kind=label wording=as-is
role-twin-deck-req = req { $req_id } · { $value }
# kind=label wording=as-is
role-twin-deck-via-a-related-group-not = Via a related group · not directly related
# kind=button wording=as-is
role-twin-deck-req-2 = { $title } · req { $req_id }
# kind=button wording=as-is
role-twin-deck-compare-with-related-roles = Compare with related roles
# kind=aria wording=as-is
role-twin-deck-related-roles = Related roles
# kind=label wording=as-is
role-twin-deck-has-related-roles = { $count ->
    [one] Has a related role
   *[other] Has { $length } related roles
}
# kind=label wording=as-is
role-twin-deck-location-not-listed = location not listed

## features/job-detail/applyAsk.ts
# kind=label wording=as-is
role-apply-ask-nothing-beyond-your-resume = Nothing beyond your resume
# kind=label note="How many questions applying asks beyond name, contact and resume"
role-apply-ask-questions = { $count ->
    [one] { $count } question
   *[other] { $count } questions
}
# kind=label note="How many of those questions want a written answer"
role-apply-ask-written-answers = { $count ->
    [one] { $count } written answer
   *[other] { $count } written answers
}
# kind=toast
role-apply-ask-asks-your-expected-pay = asks your expected compensation

## features/job-detail/JobRequirementsPanel.tsx
# kind=label wording=as-is
role-job-requirements-panel-evidence = { $display } evidence

## features/job-detail/LineageDiff.tsx
# kind=toast wording=as-is
role-lineage-diff-added = added { $join }
# kind=toast wording=as-is
role-lineage-diff-removed = removed { $join }

## features/job-detail/ListingAge.tsx
# kind=label wording=as-is
role-listing-age-changed = { $choice ->
    [yes] { $field } changed { $count } times
   *[no] { $field } changed
}

## features/job-detail/JobCompPanel.tsx
# kind=tooltip
role-job-comp-panel-the-posted-band-does-not = { $sPLIT_TITLE }. The posted range does not match that level, so treat the split as provisional

## A posting's status code, said.
# kind=label wording=as-is
role-job-status-open = open
# kind=label wording=as-is
role-job-status-closed = closed

## The base-only estimate
# kind=label
role-job-comp-panel-estimated-base = Estimated base salary
# kind=sentence
role-job-comp-panel-from-roleband-data = From built-in data.

## Who supplied the split
# kind=sentence
role-job-comp-panel-split-from-roleband = { $choice ->
    [yes] Split from built-in data, as of { $date }.
   *[no] Split from built-in data.
}
# kind=sentence
role-job-comp-panel-split-from-plugin = { $choice ->
    [yes] Split from { $plugin }, as of { $date }.
   *[no] Split from { $plugin }.
}
