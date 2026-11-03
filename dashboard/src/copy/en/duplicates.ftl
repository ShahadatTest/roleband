## duplicates: moved as it was found (wording=as-is)

## features/review/ComparisonLedger.tsx
# kind=label wording=as-is
duplicates-comparison-ledger-field = Field
# kind=label wording=as-is
duplicates-comparison-ledger-earlier-posting = Earlier posting
# kind=label wording=as-is
duplicates-comparison-ledger-newer-posting = Newer posting
# kind=label wording=as-is
duplicates-comparison-ledger-fields = fields
# kind=label wording=as-is
duplicates-comparison-ledger-same = Same
# kind=label wording=as-is
duplicates-comparison-ledger-different = Different
# kind=aria wording=as-is
duplicates-comparison-ledger-side-by-side = Side by side
# kind=label wording=as-is
duplicates-comparison-ledger-show-matching-fields = { $choice ->
    [yes] Hide { $length } matching fields
   *[no] Show { $length } matching fields
}
# kind=label wording=as-is
duplicates-comparison-ledger-show = { $choice ->
    [yes] Hide
   *[no] Show
}
# kind=label wording=as-is
duplicates-comparison-ledger-title = Title
# kind=label wording=as-is
duplicates-comparison-ledger-status = Status
# kind=label wording=as-is
duplicates-comparison-ledger-level = Level
# kind=label wording=as-is
duplicates-comparison-ledger-family = Family
# kind=label wording=as-is
duplicates-comparison-ledger-locations = Locations
# kind=label wording=as-is
duplicates-comparison-ledger-workplace = Workplace
# kind=label wording=as-is
duplicates-comparison-ledger-department = Department
# kind=label wording=as-is
duplicates-comparison-ledger-team = Team
# kind=label
duplicates-comparison-ledger-comp-est = Est. TC
# kind=label
duplicates-comparison-ledger-disclosed-band = Posted range
# kind=label wording=as-is
duplicates-comparison-ledger-first-seen = First seen
# kind=label wording=as-is
duplicates-comparison-ledger-last-observed = Last observed
# kind=label wording=as-is
duplicates-comparison-ledger-age = Age
# kind=label note="The ledger row holding each posting's two links"
duplicates-comparison-ledger-links = Links
# kind=link note="Opens the role's page in the app, over the queue"
duplicates-comparison-ledger-role-details = Role details
# kind=aria note="$side: earlier or newer, the column the link is in"
duplicates-comparison-ledger-role-details-of = { $side ->
    [earlier] Role details, earlier posting
   *[newer] Role details, newer posting
}
# kind=link note="Opens the posting on the employer's careers page, in a new tab"
duplicates-comparison-ledger-careers-page = Careers page
# kind=aria note="$side: earlier or newer, the column the link is in"
duplicates-comparison-ledger-careers-page-of = { $side ->
    [earlier] Careers page, earlier posting
   *[newer] Careers page, newer posting
}
# kind=label
duplicates-comparison-ledger-not-disclosed = not posted

## features/review/DecisionConsole.tsx
# kind=label wording=as-is
duplicates-decision-console-ai-judgment-unavailable = AI judgment unavailable
# kind=label wording=as-is
duplicates-decision-console-ai = AI
# kind=label wording=as-is
duplicates-decision-console-ai-judgment = AI judgment
# kind=label wording=as-is
duplicates-decision-console-tokens-ms = { $model } · { $value } tokens · { $wall_time_ms } ms
# kind=label wording=as-is
duplicates-decision-console-current = Current
# kind=aria wording=as-is
duplicates-decision-console-make-a-decision = Make a decision
# kind=aria wording=as-is
duplicates-decision-console-ask-the-model = Ask the model
# kind=tooltip wording=as-is
duplicates-decision-console-get-an-optional-independent-assessment = Get an optional independent assessment
# kind=label wording=as-is
duplicates-decision-console-ask-ai = { $choice ->
    [v1] Analyzing…
    [v2] Ask again
   *[v3] Ask AI
}
# kind=label wording=as-is
duplicates-decision-console-uncertain = { $choice ->
    [v1] Likely the same role
    [v2] Likely different roles
   *[v3] Uncertain
}
# kind=aria wording=as-is
duplicates-decision-console-local-model-assessment = Local model assessment
# kind=label wording=as-is
duplicates-decision-console-make-a-decision-2 = { $choice ->
    [yes] Change decision
   *[no] Make a decision
}
# kind=label wording=as-is
duplicates-decision-console-your-judgment = { $choice ->
    [yes] Change your decision
   *[no] Your judgment
}
# kind=sentence wording=as-is
duplicates-decision-console-what-is-the-relationship = { $choice ->
    [yes] Reclassify this pair
   *[no] What is the relationship?
}

## features/review/DescriptionComparison.tsx
# kind=heading wording=as-is
duplicates-description-comparison-descriptions = Descriptions
# kind=sentence wording=as-is
duplicates-description-comparison-no-differing-passages = No differing passages.
# kind=label wording=as-is
duplicates-description-comparison-changed-passage = Changed passage
# kind=aria wording=as-is
duplicates-description-comparison-description-comparison = Description comparison
# kind=sentence note="Above two postings' descriptions side by side. $choice: differ or same; $count is how many passages differ. Amber marks a passage only one of the two postings has"
duplicates-description-comparison-differences = { $choice ->
    [same] No passage-level differences detected.
   *[differ] { $count ->
        [one] { $count } passage differs. Amber passages occur only in that posting.
       *[other] { $count } passages differ. Amber passages occur only in that posting.
    }
}
# kind=label wording=as-is
duplicates-description-comparison-show-differences-only = { $choice ->
    [yes] Show full descriptions
   *[no] Show differences only
}
# kind=label wording=as-is
duplicates-description-comparison-description = Description

## features/review/ReviewHistory.tsx
# kind=label wording=as-is
duplicates-review-history-decided = Decided
# kind=heading wording=as-is
duplicates-review-history-every-judgment-ready-to-revisit = Every judgment, ready to revisit
# kind=label wording=as-is
duplicates-review-history-of = { $length } of { $value }
# kind=sentence wording=as-is
duplicates-review-history-try-another-title-requisition-id = Try another title, requisition ID, or filter.
# kind=label wording=as-is
duplicates-review-history-system-score = system score
# kind=status note="Which check first paired the two postings. $kind: duplicate (as one role posted twice) or twin (as related roles)"
duplicates-proposed-as = { $kind ->
    [twin] Proposed as related roles
   *[duplicate] Proposed as the same role
}
# kind=label wording=as-is
duplicates-review-history-reviewed = Reviewed
# kind=status note="How many times the reader changed a decision on this pair"
duplicates-review-history-revised = { $count ->
    [one] Revised once
   *[other] Revised { $count } times
}
# kind=aria wording=as-is
duplicates-review-history-decided-2 = Decided
# kind=label wording=as-is
duplicates-review-history-search-decisions = Search decisions
# kind=label wording=as-is
duplicates-review-history-search-title-or-requisition-id = Search title or requisition ID
# kind=label wording=as-is
duplicates-review-history-filter-decisions = Filter decisions
# kind=label wording=as-is
duplicates-review-history-all-decisions = All decisions
# kind=heading wording=as-is
duplicates-review-history-no-matching-decisions = No matching decisions
# kind=status
duplicates-review-history-loading = Loading decisions…
# kind=heading
duplicates-review-history-load-failed = Couldn't load decisions

## features/review/ReviewScreen.tsx
# kind=sentence wording=as-is
duplicates-review-screen-every-pair-matched-automatically-has = Every pair matched automatically has been checked. You can revisit any of them under Decided.
# kind=button wording=as-is
duplicates-review-screen-open-decided = Open decided
# kind=sentence wording=as-is
duplicates-review-screen-every-close-pair-on-your = Every close pair on your radar has a decision. You can revisit any of them under Decided.
# kind=label wording=as-is
duplicates-review-screen-pairs-left-in-the-queue = { $total } pair{ $count ->
        [one] { "" }
       *[other] s
    } { $choice ->
        [yes] matched automatically, not yet checked
       *[no] left in the queue
    }
# kind=label wording=as-is
duplicates-review-screen-system-similarity = System similarity
# kind=sentence wording=as-is
duplicates-review-screen-undone-your-later-decision-on = Undone. Your later decision on these postings stays.
# kind=label
duplicates-review-screen-could-not-undo = Couldn't undo: { $message }
# kind=toast note="After a decision on a pair of postings. $decision: duplicate (the same role), twin (related roles) or different (different roles)"
duplicates-review-screen-marked-as = { $decision ->
    [duplicate] Marked as same role
    [twin] Marked as related roles
   *[different] Marked as different roles
}
# kind=label wording=as-is
duplicates-review-screen-undo = Undo
# kind=toast
duplicates-review-screen-could-not-record-the-verdict = Couldn't record the verdict: { $message }
# kind=label wording=as-is
duplicates-review-screen-duplicate-review-views = Duplicate review views
# kind=label wording=as-is
duplicates-review-screen-queue = Queue
# kind=label wording=as-is
duplicates-review-screen-matched-automatically = Matched automatically
# kind=heading wording=as-is
duplicates-review-screen-nothing-to-check = Nothing to check
# kind=heading wording=as-is
duplicates-review-screen-queue-clear = Queue clear
# kind=heading
duplicates-review-screen-none-found = No duplicates found yet
# kind=empty note="What the Duplicates screen is for, shown while no scan has found a pair. The three answers are the verdict buttons: Same role, Related roles, Different roles"
duplicates-review-screen-none-found-why = A company often posts one { -role(num: "one") } more than once: in several cities, or again after a while. When a scan finds two { -posting(num: "other") } that look alike, they wait here for you to say whether they are the same role, related roles or different roles.
# kind=empty
duplicates-review-screen-none-found-yet = Nothing to decide yet. New pairs show up here as scans find them.
# kind=aria wording=as-is
duplicates-review-screen-candidate-pair = Candidate pair
# kind=label wording=as-is
duplicates-review-screen-system-similarity-2 = System similarity { $score }
# kind=label wording=as-is
duplicates-review-screen-about-system-similarity = About system similarity
# kind=status
duplicates-review-screen-loading = Loading the queue…
# kind=heading
duplicates-review-screen-load-failed = Couldn't load the queue

## features/review/decision.ts
# kind=label wording=as-is
duplicates-decision-different-roles = Different roles
# kind=sentence wording=as-is
duplicates-decision-two-different-roles-keep-both = Two different roles. Keep both.
# kind=label wording=as-is
duplicates-decision-related-roles = Related roles
# kind=label wording=as-is
duplicates-decision-related = Related
# kind=sentence wording=as-is
duplicates-decision-close-but-not-the-same = Close, but not the same: related roles with real differences.
# kind=label wording=as-is
duplicates-decision-same-role = Same role
# kind=label wording=as-is
duplicates-decision-duplicate = Duplicate
# kind=sentence
duplicates-decision-one-role-two-postings-listed = One role, two postings: listed again under a different requisition ID.

## routes/ReviewRoute.tsx

## features/review/DescriptionComparison.tsx
# kind=label wording=as-is
duplicates-description-comparison-description-2 = { $label } description
# kind=label note="Why a detector paired two postings: their titles match"
duplicates-reason-same-title = Same title
# kind=label note="Their titles share $pct percent of their words"
duplicates-reason-titles-alike = Titles { $pct }% alike
# kind=label note="Their descriptions read $pct percent alike"
duplicates-reason-descriptions-alike = Descriptions { $pct }% alike
# kind=label note="Both postings were open at the same time"
duplicates-reason-listed-at-once = Both listed at once
# kind=label
duplicates-reason-same-department = Same department
# kind=label note="One of the two postings states no department"
duplicates-reason-department-unknown = One states no department
# kind=status note="Passages only the earlier posting has, and only the newer one has"
duplicates-reason-passages-differ = { $earlier } passages only in the earlier, { $later } only in the newer
