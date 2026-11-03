## profile: moved as it was found (wording=as-is)

## features/scope/ExperiencePage.tsx
# kind=link wording=as-is
profile-experience-page-back-to-summary = Back to Summary
# kind=heading wording=as-is
profile-experience-page-your-experience = Your experience
# kind=label wording=as-is
profile-experience-page-coming-soon = Coming soon
# kind=sentence wording=as-is
profile-experience-page-cv-upload-isn-t-available = CV upload isn't available yet. You'll be able to add your CV here and confirm the experience used to check each role's requirements.

## features/scope/NewMark.tsx
# kind=label wording=as-is
profile-new-mark-new = New
# kind=heading wording=as-is
profile-new-mark-added-since-you-last-saved = Added since you last saved

## features/scope/PersonaRail.tsx
# kind=label wording=as-is
profile-persona-rail-level = Level
# kind=label wording=as-is
profile-persona-rail-tuned-for = Tuned for

## features/scope/ProfileSuggestions.tsx
# kind=toast
profile-suggestions-you-marked-there-not-for = you marked { $dismissed_wrong_domain } there Not for me: wrong world
# kind=toast
profile-suggestions-more-not-for-me-with = { $dismissed_other } more marked Not for me without a reason
# kind=toast wording=as-is
profile-suggestions-in-progress = { $pursued } in progress
# kind=label wording=as-is
profile-suggestions-role-there-is = role there is
# kind=label wording=as-is
profile-suggestions-roles-there-are = roles there are
# kind=toast wording=as-is
profile-suggestions-you-saved-there = you saved { $favorited } there
# kind=label wording=as-is
profile-suggestions-followed-company-sector-points = followed company sector points
# kind=label wording=as-is
profile-suggestions-followed-company-sectors-point = followed company sectors point
# kind=toast wording=as-is
profile-suggestions-your-aim-names-it = your aim names it
# kind=toast wording=as-is
profile-suggestions-turned-on-on-your-radar = { $choice ->
    [yes] { $display } turned off · { $in_scope_changed } on your radar updated
   *[no] { $display } turned on · { $in_scope_changed } on your radar updated
}
# kind=toast
profile-suggestions-could-not-apply-the-suggestion = Couldn't apply the suggestion. It stays pending.
# kind=toast
profile-suggestions-could-not-dismiss-the-suggestion = Couldn't dismiss the suggestion. Try again.
# kind=error
profile-suggestions-could-not-load = Couldn't load your suggested adjustments. Try again.
# kind=aria wording=as-is
profile-suggestions-suggested-adjustments = Suggested adjustments
# kind=sentence wording=as-is
profile-suggestions-turn-on = { $choice ->
    [yes] Turn off { $display }?
   *[no] Turn on { $display2 }?
}
# kind=sentence wording=as-is
profile-suggestions-inferred-from-your-recent-activity = { $choice ->
    [yes] Because { $join }.
   *[no] Inferred from your recent activity.
}
# kind=label wording=as-is
profile-suggestions-accept-turn-on = { $choice ->
    [yes] Accept: turn off { $display }
   *[no] Accept: turn on { $display }
}
# kind=label wording=as-is
profile-suggestions-turn-it-on = { $choice ->
    [yes] Turn it off
   *[no] Turn it on
}
# kind=label wording=as-is
profile-suggestions-dismiss-suggestion-about = Dismiss suggestion about { $display }
# kind=label wording=as-is
profile-suggestions-no-thanks = { $choice ->
    [yes] Keep it on
   *[no] No thanks
}

## features/scope/ProfileView.tsx

## features/scope/ScopeGuide.tsx
# kind=label wording=as-is
profile-scope-guide-how-your-radar-works = How your radar works
# kind=label wording=as-is
profile-scope-guide-radar-guide = Radar guide
# kind=heading wording=as-is
profile-scope-guide-how-your-radar-works-2 = How your radar works
# kind=sentence wording=as-is
profile-scope-guide-five-answers-decide-what-reaches = Five answers decide what reaches your radar. A role shows up only when it fits all of them.
# kind=label wording=as-is
profile-scope-guide-decide = Decide
# kind=label wording=as-is
profile-scope-guide-sharpen-optional = Sharpen, optional
# kind=label wording=as-is
profile-scope-guide-your-radar = Your radar
# kind=heading wording=as-is
profile-scope-guide-when-changes-apply = When changes apply
# kind=sentence wording=as-is
profile-scope-guide-save-applies-your-answers-to = Save applies your answers to the roles already collected, straight away. Roles that only your new answers reach arrive with the next scan.
# kind=heading wording=as-is
profile-scope-guide-about-the-counts = About the counts
# kind=sentence wording=as-is
profile-scope-guide-progress-shows-how-many-of = Progress shows how many of the roles at your companies each answer keeps, from the latest count. Until one has run it reads No count yet, and Count now starts one.
# kind=heading wording=as-is
profile-scope-guide-nothing-hidden-by-a-guess = Nothing hidden by a guess
# kind=sentence
profile-scope-guide-a-role-we-haven-t = A role not yet sorted into a world always stays on your radar.
# kind=sentence wording=as-is
profile-scope-guide-career-track-level-discipline-and = Career track, level, discipline, and location must all match before a role appears on your radar.
# kind=label wording=as-is
profile-scope-guide-opportunity-radar = Opportunity radar
# kind=sentence wording=as-is
profile-scope-guide-saving-applies-to-roles-already = Saving applies to roles already on your radar immediately. Newly included disciplines arrive after the next full scan.
# kind=aria wording=as-is
profile-scope-guide-how-your-radar-works-3 = How your radar works
# kind=aria wording=as-is
profile-scope-guide-close-guide = Close guide
# kind=label wording=as-is
profile-scope-guide-career-track = Career track
# kind=label wording=as-is
profile-scope-guide-how-you-contribute = How you contribute
# kind=label wording=as-is
profile-scope-guide-where-you-are-and-aim = Where you are and aim
# kind=label wording=as-is
profile-scope-guide-discipline = Discipline
# kind=label wording=as-is
profile-scope-guide-the-work-you-want = The work you want
# kind=label wording=as-is
profile-scope-guide-location = Location
# kind=label wording=as-is
profile-scope-guide-where-it-can-be-based = Where it can be based

## features/scope/ScopeSection.tsx
# kind=label wording=as-is
profile-scope-section-company-exclusions = Company exclusions
# kind=sentence wording=as-is
profile-scope-section-matching-teams-and-departments-stay = Matching teams and departments stay off your radar.
# kind=button wording=as-is
profile-scope-section-remove = Remove
# kind=label wording=as-is
profile-scope-section-business-functions = Business functions
# kind=label wording=as-is
profile-scope-section-industries = Industries
# kind=label wording=as-is
profile-scope-section-roles = { $count ->
    [one] { $count2 } role
   *[other] { $count2 } roles
}
# kind=sentence
profile-scope-section-could-not-restore-that-exclusion = Couldn't restore that exclusion. Try again.
# kind=sentence wording=as-is
profile-scope-section-exclusion-restored-left-your-radar = Exclusion restored · { $in_scope_changed } left your radar again.
# kind=sentence wording=as-is
profile-scope-section-exclusion-removed-back-on-your = Exclusion removed · { $in_scope_changed } back on your radar.
# kind=label wording=as-is
profile-scope-section-undo = Undo
# kind=sentence
profile-scope-section-could-not-remove-that-exclusion = Couldn't remove that exclusion. Try again.
# kind=aria wording=as-is
profile-scope-section-company-exclusions-2 = Company exclusions
# kind=heading
profile-scope-section-rules-load-failed = Couldn't load your company exclusions
# kind=label wording=as-is
profile-scope-section-remove-exclusion-at = Remove exclusion { $value } at { $company }

## features/scope/StageDimmer.tsx
# kind=label wording=as-is
profile-stage-dimmer-you-are-here = you are here
# kind=label wording=as-is
profile-stage-dimmer-aiming-for = aiming for
# kind=label wording=as-is
profile-stage-dimmer-roles = { $slug } roles
# kind=label wording=as-is
profile-stage-dimmer-what-this-means-at-each = What this means at each company
# kind=link
profile-stage-dimmer-see-every-company = See every company
# kind=label wording=as-is
profile-stage-dimmer-this-kind-of-role-tops = { $choice ->
    [yes] This kind of role starts higher here
   *[no] This kind of role tops out lower here
}
# kind=sentence note="Under the level rail when the chosen career track rules some levels out, which show crossed out: $from and $to are level names (Senior, Director+)"
profile-stage-dimmer-gated = { $range ->
    [from] This kind of role starts at { $from }.
    [to] This kind of role tops out at { $to }.
   *[both] This kind of role runs from { $from } to { $to }.
}
# kind=status
profile-stage-dimmer-click-your-level-today = { $choice ->
    [v1] Now pick the level you're aiming for
    [v2] Pick any level to start over
   *[v3] Pick your level today
}
# kind=aria wording=as-is
profile-stage-dimmer-level-range = Level range
# kind=aria wording=as-is
profile-stage-dimmer-your-level-today = Your level today
# kind=aria wording=as-is
profile-stage-dimmer-level-you-re-aiming-for = Level you're aiming for
# kind=label wording=as-is
profile-stage-dimmer-companies = { $count ->
    [one] company
   *[other] companies
}

## features/scope/WelcomeWizard.tsx
# kind=button wording=as-is
profile-welcome-wizard-back = Back

## features/scope/useScopeDraft.ts
# kind=error wording=as-is
profile-use-scope-draft-couldn-t-load-your-radar = Couldn't load your radar. Try again.
# kind=error wording=as-is
profile-use-scope-draft-couldn-t-save-your-radar = Couldn't save your radar. Try again.
# kind=toast
profile-use-scope-draft-refreshing-role-counts-this-reads = Counting roles again. This reads careers pages only; roles on your radar don't change.
# kind=toast
profile-use-scope-draft-that-refresh-was-deferred-because = That count waits until the current scan or count ends.
# kind=error wording=as-is
profile-use-scope-draft-couldn-t-count-roles-at = Couldn't count roles at your companies. Try again.

## features/scope/walk/PayFloorRow.tsx
# kind=heading
profile-pay-floor-row-pay-floor = Minimum base
# kind=label
profile-pay-floor-row-a-year-base = a year
# kind=button wording=as-is
profile-pay-floor-row-cancel = Cancel
# kind=label wording=as-is
profile-pay-floor-row-checking = Checking…
# kind=sentence
profile-pay-floor-row-couldn-t-read-your-pay = Couldn't read your minimum base.
# kind=button wording=as-is
profile-pay-floor-row-retry = Retry
# kind=sentence
profile-pay-floor-row-compared-where-pay-is-stated = Compared with the posted base salary, where a posting has one.
# kind=sentence
profile-pay-floor-row-no-roles-are-hidden = No roles are hidden.
# kind=error wording=as-is
profile-pay-floor-row-enter-a-yearly-amount-like = Enter a yearly amount, like 250,000 or 250k.
# kind=sentence
profile-pay-floor-row-could-not-save-the-pay = Couldn't save the minimum base. Try again.
# kind=aria
profile-pay-floor-row-pay-floor-2 = Minimum base
# kind=aria
profile-pay-floor-row-lowest-yearly-base-pay = Lowest yearly base salary
# kind=label wording=as-is
profile-pay-floor-row-currency = Currency
# kind=label
profile-pay-floor-row-save-floor = { $choice ->
    [yes] Saving…
   *[no] Save minimum base
}
# kind=label
profile-pay-floor-row-set-floor = Set minimum base
# kind=sentence
profile-pay-floor-row-could-not-remove-the-pay = Couldn't remove the minimum base. Try again.
# kind=aria
profile-pay-floor-row-retry-reading-the-pay-floor = Retry reading the minimum base
# kind=label
profile-pay-floor-row-add-a-pay-floor = { $choice ->
    [yes] Adjust minimum base
   *[no] Add a minimum base
}
# kind=label
profile-pay-floor-row-set-your-pay-floor = { $choice ->
    [yes] { $amount } a year
   *[no] Set your minimum base
}
# kind=label
profile-pay-floor-row-minimum-yearly-base-pay = { $choice ->
    [yes] Adjust
   *[no] Minimum yearly base salary
}

## features/scope/walk/ProgressRail.tsx
# kind=heading wording=as-is
profile-progress-rail-focus-your-radar = Focus your radar
# kind=label wording=as-is
profile-progress-rail-all-roles = All roles
# kind=label wording=as-is
profile-progress-rail-no-count-yet = No count yet.
# kind=label wording=as-is
profile-progress-rail-of-all-roles = of all roles
# kind=sentence
profile-progress-rail-choose-your-role-level-and = Choose your career track, level and location to see what fits.
# kind=label wording=as-is
profile-progress-rail-review-changes = Review changes
# kind=sentence wording=as-is
profile-progress-rail-more-are-added-when-the = { $choice ->
    [yes] Up to { $arriving } more arrive when the current scan ends, or as each company is next scanned.
   *[no] More are added when the current scan ends.
}
# kind=label wording=as-is
profile-progress-rail-text = { $choice ->
    [yes] { " " }Up to { $arriving } more arrive as each company is next scanned.
   *[no] { "" }
}
# kind=label wording=as-is
profile-progress-rail-text-2 = { $choice ->
    [yes] , like { $joinAnd }
   *[no] { "" }
}
# kind=sentence
profile-progress-rail-your-board-goes-from-to = { $choice ->
    [yes] Your radar keeps its { $now }.
   *[no] Your radar goes from { $now2 } to { $after }.
}
# kind=toast wording=as-is
profile-progress-rail-of-them-from-earlier-scans = { $adds } of them from earlier scans{ $like }.
# kind=toast wording=as-is
profile-progress-rail-a-scan-is-running-from = A scan is running: { $later } from earlier scans join when it ends{ $like }.
# kind=toast wording=as-is
profile-progress-rail-more-join-as-each-company = More join as each company is next scanned.
# kind=aria wording=as-is
profile-progress-rail-your-progress = Your progress
# kind=label wording=as-is
profile-progress-rail-count-now = { $choice ->
    [yes] Starting…
   *[no] Count now
}
# kind=sentence wording=as-is
profile-progress-rail-save-to-count-the-roles = { $choice ->
    [yes] Counting the roles in { $pendingPlaces }…
   *[no] Save to count the roles in { $pendingPlaces2 }.
}
# kind=label wording=as-is
profile-progress-rail-roles-match = { $count ->
    [one] role matches
   *[other] roles match
}
# kind=label wording=as-is
profile-progress-rail-roles-when-you-save = { $choice ->
    [yes] No change when you save
   *[no] roles when you save
}
# kind=status
profile-progress-rail-we-ll-know-after-the = { $choice ->
    [v1] Updates when you save
    [v2] No change when you save
    [v3] roles when you save
   *[v4] Known after the next count
}
# kind=label wording=as-is
profile-progress-rail-save = { $choice ->
    [yes] Saving…
   *[no] Save
}
# kind=label wording=as-is
profile-progress-rail-roles = { $count ->
    [one] role
   *[other] roles
}
# kind=label wording=as-is
profile-progress-rail-roles-are = { $count ->
    [one] role is
   *[other] roles are
}
# kind=sentence wording=as-is
profile-progress-rail-text-3 = { $choice ->
    [yes] , { $promoted } of them from earlier scans.
   *[no] .
}
# kind=status
profile-progress-rail-saved-on-your-board-now = { $choice ->
    [yes] Saved. { $changed } { $value } changed on your radar.
   *[no] Saved. { $onBoard } { $value2 } on your radar now{ $value3 }{ $arriving }
}

## features/scope/walk/RadarPyramid.tsx
# kind=sentence wording=as-is
profile-radar-pyramid-illustrative-funnel-each-percentage-is = Illustrative funnel. Each percentage is the share remaining after that answer.
# kind=label wording=as-is
profile-radar-pyramid-after-the-first-three-answers = After the first three answers
# kind=label wording=as-is
profile-radar-pyramid-locked = Locked
# kind=label wording=as-is
profile-radar-pyramid-not-answered-yet = { $choice ->
    [yes] Any, nothing narrowed
   *[no] Not answered yet
}
# kind=label wording=as-is
profile-radar-pyramid-choose = { $choice ->
    [yes] Any
   *[no] Choose
}
# kind=label wording=as-is
profile-radar-pyramid-answered-no-count-yet = Answered, no count yet
# kind=label wording=as-is
profile-radar-pyramid-no-count = No count
# kind=label wording=as-is
profile-radar-pyramid-counting = Counting
# kind=label wording=as-is
profile-radar-pyramid-counted-after-you-save = Counted after you save
# kind=label wording=as-is
profile-radar-pyramid-save-first = Save first
# kind=label wording=as-is
profile-radar-pyramid-keeps = Keeps { $kept }, { $kept2 }
# kind=aria wording=as-is
profile-radar-pyramid-what-each-answer-keeps = What each answer keeps
# kind=label wording=as-is
profile-radar-pyramid-url-fill = url(#{ $id }-fill)

## features/scope/walk/RolesStep.tsx
# kind=sentence
profile-roles-step-pick-a-kind-of-role = Pick a career track first.
# kind=sentence wording=as-is
profile-roles-step-nothing-called-under = Nothing called “{ $query }” under { $label }.
# kind=label wording=as-is
profile-roles-step-filter-roles = Filter roles
# kind=label wording=as-is
profile-roles-step-filter-roles-2 = Filter roles…
# kind=label wording=as-is
profile-roles-step-craft-for = Craft for { $label }
# kind=label wording=as-is
profile-roles-step-roles = { $count ->
    [one] { $count2 } role · { $examples }
   *[other] { $count2 } roles · { $examples }
}

## features/scope/walk/SubjectsStep.tsx
# kind=label wording=as-is
profile-subjects-step-choose-a-list-then-tick = Choose a list, then tick what goes in it
# kind=sentence wording=as-is
profile-subjects-step-nothing-called = Nothing called “{ $query }”.
# kind=sentence wording=as-is
profile-subjects-step-removes-of-the-roles-you = { $avoid } { $subject } removes { $dropped } of the { $of } roles you picked under { $label }. Untick one if that isn't what you meant.
# kind=sentence
profile-subjects-step-of-your-roles-aren-t = { $untagged } of your { $of } roles aren't sorted into a world yet. They stay on your radar whatever you pick.
# kind=label wording=as-is
profile-subjects-step-technologies = Technologies
# kind=sentence
profile-subjects-step-you-ll-see-roles-about = You'll see roles in these worlds, plus roles not yet sorted into one.
# kind=sentence
profile-subjects-step-roles-about-these-drop-off = Roles about these drop off, even if they also match an interest.
# kind=label wording=as-is
profile-subjects-step-switch-to-this = { $choice ->
    [yes] Picking now
   *[no] Switch to this
}
# kind=label wording=as-is
profile-subjects-step-picked = { $choice ->
    [yes] None yet
   *[no] { $picked } picked
}
# kind=label
profile-subjects-step-filter-interests = Filter worlds
# kind=label
profile-subjects-step-filter-interests-2 = Filter worlds…

## features/scope/walk/SummaryStep.tsx
# kind=heading wording=as-is
profile-summary-step-summary = Summary
# kind=button wording=as-is
profile-summary-step-adjust = Adjust
# kind=label wording=as-is
profile-summary-step-what-it-keeps = What it keeps
# kind=sentence wording=as-is
profile-summary-step-no-count-yet-once-a = No count yet. Once a scan has run, this shows how many roles each answer keeps.
# kind=label wording=as-is
profile-summary-step-counting-the-roles-in = Counting the roles in { $pendingPlaces }…
# kind=sentence wording=as-is
profile-summary-step-save-to-count-the-roles = Save to count the roles in { $pendingPlaces }.
# kind=label wording=as-is
profile-summary-step-add-your-cv = Add your CV
# kind=label same-as=profile-scope-guide-career-track
profile-summary-step-role = Career track
# kind=label same-as=profile-scope-guide-location
profile-summary-step-where = Location
# kind=label same-as=profile-scope-guide-discipline
profile-summary-step-which-roles = Discipline
# kind=label
profile-summary-step-interests = World
# kind=label wording=as-is
profile-summary-step-nothing-picked-yet = Nothing picked yet
# kind=label wording=as-is
profile-summary-step-any-role-that-fits = Any role that fits
# kind=label
profile-summary-step-none-yet = Any world
# kind=label wording=as-is
profile-summary-step-not-set = Not set
# kind=label wording=as-is
profile-summary-step-adjust-2 = Adjust { $label }
# kind=label wording=as-is
profile-summary-step-after-you-save = { $choice ->
    [yes] counting
   *[no] after you save
}
# kind=label wording=as-is
profile-summary-step-see-your-radar = { $choice ->
    [v1] Saving…
    [v2] Save and see your radar
   *[v3] See your radar
}

## features/scope/walk/Walk.tsx
# kind=sentence note="Beside the step tabs while the steps after the first three are locked"
profile-walk-locked-reason = The other steps open once you answer the first three.
# kind=label note="Beside the question of a step the walk can be finished without (Discipline, World)"
profile-walk-optional = Optional
# kind=button note="The forward button of an optional step while it still keeps everything; skipping keeps every choice"
profile-walk-skip = Skip
# kind=label wording=as-is
profile-walk-summary = Summary
# kind=aria wording=as-is
profile-walk-what-your-radar-looks-for = What your radar looks for
# kind=label wording=as-is
profile-walk-steps = Steps
# kind=sentence note="Shown beside the disabled Continue on the Role step, saying what opens it"
profile-walk-continue-reason-accountable = Pick at least one career track to continue.
# kind=sentence note="Shown beside the disabled Continue on the Level step: both the level today and the level aimed for are needed"
profile-walk-continue-reason-level = Pick your level today and the one you're aiming for to continue.
# kind=sentence note="Shown beside the disabled Continue on the Where step: a place is a city, country or region"
profile-walk-continue-reason-where = Add at least one place to continue.
# kind=label wording=as-is
profile-walk-continue = { $choice ->
    [yes] Done
   *[no] Continue
}

## First-run setup: Profile's walk in setup mode (features/scope/ProfileView.tsx, walk/Walk.tsx, walk/SummaryStep.tsx)

# kind=sentence note="Top of Profile while setup was left for later; followed by the link Finish setting up"
profile-setup-unfinished = Setup isn't finished, so your radar is using starter settings.
# kind=link
profile-setup-finish = Finish setting up
# kind=button
profile-setup-later = Set up later
# kind=heading
profile-setup-title = Set up your radar
# kind=status note="Over setup's title, shown in capitals as the welcome's kicker is: the step on screen, $step of $count steps, Summary and Companies included"
profile-setup-step = Setup, step { $step } of { $count }
# kind=label
profile-setup-companies-tab = Companies
# kind=heading
profile-setup-companies-title = Where should your radar look?
# kind=sentence
profile-setup-companies-note = You start with well-known companies. Follow more now, or at any time later.
# kind=sentence
profile-setup-summary-later = You can change any answer later in Profile.

## features/scope/walk/WhereStep.tsx
# kind=button wording=as-is
profile-where-step-go-worldwide = Go worldwide
# kind=sentence wording=as-is
profile-where-step-nothing-called-try-a-city = Nothing called “{ $query }”. Try a city or a country.
# kind=button wording=as-is
profile-where-step-include-all = Include all
# kind=sentence wording=as-is
profile-where-step-nothing-called-in = Nothing called “{ $inside }” in { $display }.
# kind=label wording=as-is
profile-where-step-haven-t-been-scanned-for = { $count ->
    [one] { $companies } hasn't been scanned for { $few } yet.
   *[other] { $companies } haven't been scanned for { $few } yet.
}
# kind=label wording=as-is
profile-where-step-replaces-the-places-you-ve = Replaces the places you've added with anywhere
# kind=label wording=as-is
profile-where-step-in-choose-to-narrow-to = { $choice ->
    [yes] already added
   *[no] in { $display }, choose to narrow to it
}
# kind=label wording=as-is
profile-where-step-add-back = Add back { $name }
# kind=label wording=as-is
profile-where-step-excepted-add-it-back = excepted, add it back
# kind=label wording=as-is
profile-where-step-add = { $choice ->
    [yes] Narrow { $display } to { $name }
   *[no] Add { $name2 }
}
# kind=label wording=as-is
profile-where-step-add-2 = Add { $display }
# kind=label wording=as-is
profile-where-step-all-member-countries = { $choice ->
    [yes] already added
   *[no] All { $length } member countries
}
# kind=label wording=as-is
profile-where-step-add-another-place = { $choice ->
    [v1] Where are you based?
    [v2] Name a place instead
   *[v3] Add another place
}
# kind=label wording=as-is
profile-where-step-add-another-place-2 = { $choice ->
    [v1] City, country or region
    [v2] Name a place instead
   *[v3] Add another place
}
# kind=aria wording=as-is
profile-where-step-places = Places
# kind=aria wording=as-is
profile-where-step-your-bases = Your bases
# kind=sentence wording=as-is
profile-where-step-any-country-any-city = Any country, any city.
# kind=label wording=as-is
profile-where-step-include-all-of = Include all of { $display }
# kind=label wording=as-is
profile-where-step-choose-in = { $choice ->
    [yes] Done choosing { $noun } in { $display }
   *[no] Choose { $noun2 } in { $display2 }
}
# kind=label wording=as-is
profile-where-step-choose = { $choice ->
    [yes] Done
   *[no] Choose { $noun }
}
# kind=label wording=as-is
profile-where-step-how-far-from = How far from { $display }
# kind=label wording=as-is
profile-where-step-remove = Remove { $display }
# kind=label wording=as-is
profile-where-step-filter-in = Filter { $noun } in { $display }
# kind=label wording=as-is
profile-where-step-filter = Filter { $noun }
# kind=label wording=as-is
profile-where-step-and-more = { $join } and { $value } more
# kind=sentence note="Companies whose careers sites can't be asked about the places picked, and those places: Apple and Accenture, Stockholm or Berlin"
profile-where-step-careers-sites-cant-be-searched = { $count ->
    [one] { $companies }'s careers site can't be searched for { $places } yet, so its { -role(num: "other") } there won't reach your radar.
   *[other] The careers sites of { $companies } can't be searched for { $places } yet, so their { -role(num: "other") } there won't reach your radar.
}

## features/scope/walk/walkModel.ts
# kind=label wording=as-is
profile-walk-model-leading-a-team = Leading a team
# kind=label
profile-walk-model-people-managers-and-directors-any = Managers and directors
# kind=label wording=as-is
profile-walk-model-leading-a-team-2 = leading a team
# kind=label
profile-walk-model-owning-a-product-or-program = Owning a product
# kind=label
profile-walk-model-product-program-or-project-management = Product, program, project
# kind=label
profile-walk-model-owning-a-product-or-program-2 = owning a product
# kind=label wording=as-is
profile-walk-model-hands-on-as-the-expert = Hands-on, as the expert
# kind=label
profile-walk-model-engineer-scientist-designer-analyst = Engineer, scientist, designer
# kind=label wording=as-is
profile-walk-model-working-with-customers = Working with customers
# kind=label
profile-walk-model-sales-partnerships-customer-success = Sales and customer success
# kind=label wording=as-is
profile-walk-model-working-with-customers-2 = working with customers
# kind=label wording=as-is
profile-walk-model-anywhere = Anywhere
# kind=label wording=as-is
profile-walk-model-no-chosen-yet = No { $locations } chosen yet
# kind=label wording=as-is
profile-walk-model-only = Only { $names }
# kind=label wording=as-is
profile-walk-model-everywhere = { $choice ->
    [v1] Every country
    [v2] Every city
   *[v3] Everywhere
}
# kind=label wording=as-is
profile-walk-model-anywhere-in = Anywhere in { $display }
# kind=toast wording=as-is
profile-walk-model-anywhere-in-2 = anywhere in { $wide }
# kind=label wording=as-is
profile-walk-model-interested-in = Interested in
# kind=label wording=as-is
profile-walk-model-not-interested-in = Not interested in
# kind=label wording=as-is
profile-walk-model-or = { $join }, or { $parts }
# kind=label wording=as-is
profile-walk-model-not = Not: { $off }
# kind=label wording=as-is
profile-walk-model-from-to = { $choice ->
    [yes] at { $first }
   *[no] from { $first2 } to { $last }
}
# kind=label wording=as-is
profile-walk-model-from-to-2 = { $count ->
    [one] at { $display }
   *[other] from { $display2 } to { $display3 }
}

## features/scope/walk/walkSteps.ts
# kind=tooltip wording=as-is
profile-walk-steps-what-kind-of-role-are = What kind of role are you looking for?
# kind=sentence wording=as-is
profile-walk-steps-pick-one-or-more = Pick one or more.
# kind=label wording=as-is
profile-walk-steps-the-kind-of-work-you = The kind of work you're accountable for
# kind=tooltip wording=as-is
profile-walk-steps-your-level = Your level
# kind=sentence wording=as-is
profile-walk-steps-today-and-the-one-you = Today, and the one you're aiming for.
# kind=label wording=as-is
profile-walk-steps-where-you-are-today-up = Where you are today, up to where you're aiming
# kind=tooltip wording=as-is
profile-walk-steps-where-do-you-want-to = Where do you want to work?
# kind=sentence wording=as-is
profile-walk-steps-where-you-re-based-and = Where you're based, and how far you'd go for the right role.
# kind=label wording=as-is
profile-walk-steps-your-bases-and-how-far = Your bases, and how far you'd go
# kind=tooltip wording=as-is
profile-walk-steps-any-particular-roles = Any particular roles?
# kind=sentence
profile-walk-steps-every-role-of-each-kind = Every role of each kind, or only the ones you pick. Skip it to keep them all.
# kind=label wording=as-is
profile-walk-steps-particular-roles-or-any-that = Particular roles, or any that fits
# kind=tooltip wording=as-is
profile-walk-steps-anything-you-care-about-or = Anything you care about, or want to avoid?
# kind=sentence
profile-walk-steps-the-fields-and-industries-the = Fields and industries to look for or avoid. Skip it to rule nothing out.
# kind=status
profile-walk-steps-topics-to-look-for-and = Worlds to look for, and worlds to drop

## features/scope/walk/walkModel.ts (by hand)
# kind=label wording=as-is
profile-walk-model-the-place = the { $place }

## features/scope/ProfileSuggestions.tsx
# kind=toast wording=as-is
profile-suggestions-there = { $length } there

## features/scope/walk/ProgressRail.tsx
# kind=label wording=as-is
profile-progress-rail-at = { $title } at { $company_display }

## features/scope/walk/WhereStep.tsx
# kind=label wording=as-is
profile-where-step-in = { $noun }{ $slice } in { $display }

## features/scope/walk/walkModel.ts
# kind=label wording=as-is
profile-walk-model-except = except { $names }
# kind=label wording=as-is
profile-walk-model-except-2 = { $every } except { $joinAnd }
# kind=label wording=as-is
profile-walk-model-and = { $join } and { $parts }
# kind=label wording=as-is
profile-walk-model-only-2 = { $display } only
# kind=label wording=as-is
profile-walk-model-in = in { $display }
# kind=label wording=as-is
profile-walk-model-or-3 = { $parts } or { $parts2 }
# kind=label wording=as-is
profile-walk-model-more = { $said }{ $comma } { $word } { $value } more
