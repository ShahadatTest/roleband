## Words every settings section shares: one message each, never borrowed from a section.

# kind=error
settings-save-failed = Couldn't save it. Try again.
# kind=label wording=as-is
settings-loading = Loading…
# kind=button wording=as-is
settings-cancel = Cancel
# kind=label wording=as-is
settings-company = Company

## Settings > Language and region (docs/copy.md)

# kind=heading
settings-language-title = Language and region
# kind=sentence
settings-language-intro = Choose the app's language and how numbers and dates are written. It changes at once, and nothing you have open is reloaded.
# kind=label
settings-language-label = Language
# kind=sentence
settings-language-description = Company names, titles and postings stay as their employers wrote them.
# kind=label note="A language only partly translated: the rest shows in English"
settings-language-partial = { $name }, partly translated
# kind=label note="A pseudo language for checking copy, listed only with the copy-check flag"
settings-language-check = { $name }, for checking copy
# kind=label
settings-region-label = Numbers and dates
# kind=sentence
settings-region-description = How numbers and dates are written: { $number }, { $date }.
# kind=label note="The region option that follows the operating system"
settings-region-automatic = As your system
# kind=label note="A region option: the country, then a sample of its formats"
settings-region-option = { $country }: { $number }, { $date }

## features/settings/ChronographDial.tsx
# kind=label wording=as-is
settings-chronograph-dial-night = NIGHT
# kind=label wording=as-is
settings-chronograph-dial-full-scan = Full scan
# kind=label wording=as-is
settings-chronograph-dial-quick-scan = Quick scan
# kind=label wording=as-is
settings-chronograph-dial-usually-off = Usually off
# kind=label wording=as-is
settings-chronograph-dial-a-time-you-set = A time you set
# kind=label
settings-chronograph-dial-reconciliation-orbit = Full scans
# kind=label
settings-chronograph-dial-discovery-orbit = Quick scans
# kind=label
settings-chronograph-dial-authoritative-cycle = Full scan window
# kind=aria wording=as-is
settings-chronograph-dial-scan-clock = Scan clock
# kind=aria wording=as-is
settings-chronograph-dial-draggable-schedule-marks = Draggable schedule marks
# kind=label wording=as-is note="A running planned scan's handle on the dial; kind = full or quick, time = when it started"
settings-chronograph-dial-scan-running = { $kind ->
    [full] Full scan running since { $time }
   *[quick] Quick scan running since { $time }
}
# kind=label wording=as-is note="A planned scan's handle on the dial; kind = full or quick; start = wake (it runs when the computer is turned on) or clock (at a time of day)"
settings-chronograph-dial-move-planned-scan = { $kind ->
    [full] { $start ->
        [wake] Move full scan, when you turn it on, about { $time }
       *[clock] Move full scan, at { $time }
    }
   *[quick] { $start ->
        [wake] Move quick scan, when you turn it on, about { $time }
       *[clock] Move quick scan, at { $time }
    }
}
# kind=label wording=as-is note="A company's mark on the dial; scan = the name of its scan, such as full scan"
settings-chronograph-dial-move-company = Move { $company } { $scan }, currently { $time }
# kind=label wording=as-is note="A stack of company marks that a drag can split; stack = how many and what, such as 3 full scans; state = overdue or scheduled; company = the one a drag moves out"
settings-chronograph-dial-stack-movable = { $stack } { $state ->
        [overdue] due now
       *[scheduled] at { $time }
    }, open to see all, drag to move { $company } out
# kind=label wording=as-is note="A stack of company marks that are all locked; stack = how many and what, such as 3 full scans; state = overdue or scheduled"
settings-chronograph-dial-stack-locked = { $stack } { $state ->
        [overdue] due now
       *[scheduled] at { $time }
    }, open to see all
# kind=label wording=as-is note="The marks a drag leaves behind in a stack; stack = how many and what, such as 2 full scans"
settings-chronograph-dial-still-at = { $stack } still at { $time }
# kind=aria wording=as-is
settings-chronograph-dial-schedule-clock-legend = Schedule clock legend

## features/settings/ChronographInspector.tsx
# kind=label wording=as-is note="A stack's header in the inspector; count = how many marks, time = the time they share"
settings-chronograph-inspector-share = { $count } share { $time }
# kind=label wording=as-is
settings-chronograph-inspector-due-now = Due now
# kind=label wording=as-is
settings-chronograph-inspector-scheduled = Scheduled
# kind=label wording=as-is
settings-chronograph-inspector-closes-roles = Closes roles
# kind=label wording=as-is
settings-chronograph-inspector-held-until = Held until
# kind=label wording=as-is
settings-chronograph-inspector-locked = Locked
# kind=label wording=as-is
settings-chronograph-inspector-scan-schedule-inspector = Scan schedule inspector
# kind=sentence wording=as-is note="Under a stack's header when a drag can split it; company = the one a drag moves out"
settings-chronograph-inspector-stack-movable = Give any of them its own time here, or drag the mark to move { $company } out first.
# kind=sentence wording=as-is note="Under a stack's header when no mark in it can move"
settings-chronograph-inspector-stack-locked = Every mark in this stack is locked.
# kind=label note="A pass's name; mode = discovery or reconcile"
settings-chronograph-inspector-pass = { $mode ->
    [discovery] Quick scan
   *[reconcile] Full scan
}
# kind=label wording=as-is
settings-chronograph-inspector-runs-at = Runs at

## features/settings/PlanRunInspector.tsx
# kind=label wording=as-is
settings-plan-run-inspector-scanning-now = Scanning now
# kind=label wording=as-is
settings-plan-run-inspector-when-you-turn-it-on = When you turn it on
# kind=label wording=as-is
settings-plan-run-inspector-planned = Planned
# kind=label wording=as-is
settings-plan-run-inspector-companies = Companies
# kind=label wording=as-is
settings-plan-run-inspector-takes = Takes
# kind=label wording=as-is
settings-plan-run-inspector-starts = Starts
# kind=label wording=as-is
settings-plan-run-inspector-yes = yes
# kind=label wording=as-is
settings-plan-run-inspector-repeats = Repeats
# kind=label wording=as-is
settings-plan-run-inspector-every = Every
# kind=button wording=as-is
settings-plan-run-inspector-count-from-the-last-scan = Count from the last scan instead
# kind=button wording=as-is
settings-plan-run-inspector-use-my-usual-start = Use my usual start
# kind=sentence wording=as-is
settings-plan-run-inspector-it-also-runs-when-you = It also runs when you turn the computer on after two hours or more.
# kind=label wording=as-is
settings-plan-run-inspector-scan-inspector = Scan inspector
# kind=label wording=as-is note="How the quick scans repeat; anchor = fixed (at fixed times) or last (counted from the last scan); hours = how far apart"
settings-plan-run-inspector-repeats-every = { $anchor ->
    [fixed] every { $hours }h at fixed times
   *[last] every { $hours }h after the last scan
}
# kind=label wording=as-is note="Beside a quick scan's time field; state = planned (it can move) or running"
settings-plan-run-inspector-quick-time = { $state ->
    [planned] Quick scans at
   *[running] Started
}
# kind=label wording=as-is
settings-plan-run-inspector-quick-scan-time = Quick scan time
# kind=label wording=as-is
settings-plan-run-inspector-quick-scan-every = Quick scan every
# kind=sentence wording=as-is note="Said when the quick scans' interval changes; hours = the new interval"
settings-plan-run-inspector-a-quick-scan-every-hours = A quick scan every { $hours } hours.
# kind=sentence wording=as-is
settings-plan-run-inspector-quick-scans-every-hours-after = Quick scans every { $repeat_hours } hours after the last scan.
# kind=label wording=as-is note="Beside a full scan's time field; state = planned (it can move) or running"
settings-plan-run-inspector-full-time = { $state ->
    [planned] Done by
   *[running] Started
}
# kind=label wording=as-is
settings-plan-run-inspector-full-scan-done-by = Full scan done by
# kind=sentence wording=as-is
settings-plan-run-inspector-full-scan-back-to-your = Full scan back to your usual start.

## features/settings/RecipesSection.tsx
# kind=label wording=as-is
settings-recipes-section-the-recipe-has-problems = { $count ->
    [one] The recipe has a problem:
   *[other] The recipe has { $length } problems:
}
# kind=sentence
settings-recipes-section-this-careers-page-asks-not = This careers page asks not to be read automatically, so it won't be scanned.
# kind=sentence wording=as-is
settings-recipes-section-no-roles-found-on-the = No roles found on the first pages.
# kind=sentence wording=as-is
settings-recipes-section-no-recipes-yet-write-one = No recipes yet. Write one below and preview it.
# kind=button wording=as-is
settings-recipes-section-open = Open
# kind=label wording=as-is
settings-recipes-section-recipe-json = Recipe (JSON)
# kind=button wording=as-is
settings-recipes-section-save-draft = Save draft
# kind=button wording=as-is
settings-recipes-section-edit = Edit
# kind=button wording=as-is
settings-recipes-section-check-the-whole-page = Check the whole page
# kind=button wording=as-is
settings-recipes-section-use-this-version = Use this version
# kind=button wording=as-is
settings-recipes-section-scan-with-it = Scan with it
# kind=sentence wording=as-is
settings-recipes-section-a-recipe-is-one-json = A recipe is one JSON object.
# kind=label wording=as-is
settings-recipes-section-not-valid-json = Not valid JSON: { $caught }
# kind=toast
settings-recipes-section-could-not-read-it = couldn't read it
# kind=label wording=as-is
settings-recipes-section-whole-page-check-result = { $choice ->
    [yes] Preview result
   *[no] Whole-page check result
}
# kind=sentence wording=as-is
settings-recipes-section-not-checked-the-whole-page = { $choice ->
    [yes] Checked: read the whole page, { $found } roles over { $pages } pages.
   *[no] Not checked: the whole page did not read to its end.
}
# kind=label wording=as-is
settings-recipes-section-no-place-stated = no place stated
# kind=label wording=as-is
settings-recipes-section-in-use = in use
# kind=label wording=as-is
settings-recipes-section-not-checked = { $choice ->
    [yes] checked { $validated_at }
   *[no] not checked
}
# kind=toast wording=as-is
settings-recipes-section-couldn-t-preview-the-recipe = Couldn't preview the recipe.
# kind=toast wording=as-is
settings-recipes-section-saved-version-of = Saved version { $version } of { $slug }.
# kind=toast wording=as-is
settings-recipes-section-couldn-t-save-the-recipe = Couldn't save the recipe.
# kind=toast wording=as-is
settings-recipes-section-couldn-t-check-the-whole = Couldn't check the whole page.
# kind=toast wording=as-is
settings-recipes-section-version-is-now-the-one = Version { $version } is now the one new companies are scanned with.
# kind=toast wording=as-is
settings-recipes-section-couldn-t-switch-versions = Couldn't switch versions.
# kind=toast wording=as-is
settings-recipes-section-is-now-scanned-with-its = { $company } is now scanned with { $slug }. Its missing roles close only once a checked version reads its whole page.
# kind=toast wording=as-is
settings-recipes-section-couldn-t-scan-that-company = Couldn't scan that company with this recipe.
# kind=heading wording=as-is
settings-recipes-section-recipes = Recipes
# kind=sentence
settings-recipes-section-a-recipe-tells-roleband-how = A recipe says how to read a careers page that isn't supported yet.
# kind=label wording=as-is
settings-recipes-section-draft-only = { $choice ->
    [yes] version { $active_version } in use
   *[no] draft only
}
# kind=label wording=as-is
settings-recipes-section-not-checked-2 = { $choice ->
    [yes] checked
   *[no] not checked
}
# kind=label wording=as-is
settings-recipes-section-scans-no-company = { $choice ->
    [yes] scans { $join }
   *[no] scans no company
}
# kind=label wording=as-is
settings-recipes-section-new-recipe = New recipe
# kind=label wording=as-is
settings-recipes-section-preview = { $choice ->
    [yes] Previewing…
   *[no] Preview
}
# kind=heading wording=as-is
settings-recipes-section-versions = Versions
# kind=aria wording=as-is
settings-recipes-section-versions-2 = Versions
# kind=label wording=as-is
settings-recipes-section-version = Version { $version }
# kind=heading wording=as-is
settings-recipes-section-scan-a-company-with-it = Scan a company with it
# kind=sentence wording=as-is
settings-recipes-section-no-company-is-scanned-with = { $choice ->
    [yes] Scans { $join }.
   *[no] No company is scanned with it yet.
}
# kind=label wording=as-is
settings-recipes-section-choose-a-company = Choose a company

## features/settings/RetentionSection.tsx
# kind=label wording=as-is
settings-retention-section-kept = { $stored } kept
# kind=button wording=as-is
settings-retention-section-remove-after = Remove after { $choiceLabel }
# kind=label wording=as-is
settings-retention-section-1-year = 1 year
# kind=label wording=as-is
settings-retention-section-never = Never
# kind=sentence
settings-retention-section-makes-postings-due-they-are = With { $days }, { $due } postings are due for removal. They're removed during the next scans.
# kind=label wording=as-is
settings-retention-section-none-yet = None yet
# kind=label wording=as-is
settings-retention-section-text = { $choice ->
    [yes] { " " }· more are removed at the next scan
   *[no] { "" }
}
# kind=label wording=as-is
settings-retention-section-removed = { $at } · { $removed } removed{ $more }
# kind=heading wording=as-is
settings-retention-section-data-retention = Data retention
# kind=sentence
settings-retention-section-roleband-keeps-every-posting-its = Every posting a scan finds is kept, so a change to what you look for can put roles on your radar at once.
# kind=heading wording=as-is
settings-retention-section-remove-postings-after = Remove postings after
# kind=sentence
settings-retention-section-a-posting-stops-being-read = A posting stops being scanned when it is no longer listed, or when you stop following its company. Once no scan has seen it for this long, it is removed. Roles on your radar, what you saved and their history are never removed.
# kind=label wording=as-is
settings-retention-section-no-longer-listed = · { $no_longer_listed } no longer listed
# kind=label wording=as-is
settings-retention-section-from-companies-you-stopped-following = · { $stopped_following } from companies you stopped following
# kind=label wording=as-is
settings-retention-section-remove-postings-after-2 = Remove postings after
# kind=heading wording=as-is
settings-retention-section-last-removal = Last removal
# kind=heading
settings-retention-section-due-for-removal = Due for removal
# kind=status note="How many postings the saved window makes due now; count = the number, due = it formatted"
settings-retention-section-due-count = { $count ->
    [one] { $due } { -posting(num: "one") }
   *[other] { $due } { -posting(num: "other") }
}
# kind=sentence note="Under Due for removal. never = the window is Never; set = a window is chosen"
settings-retention-section-due-detail = { $state ->
    [never] Nothing is removed while this is set to Never.
   *[set] Due postings are removed during scans, never by saving.
}
# kind=status note="A new window was saved"
settings-retention-section-saved = Saved.

## features/settings/ScheduleChronograph.tsx
# kind=label wording=as-is note="A planned scan's label on the dial when it runs as the computer is turned on; kind = full or quick"
settings-schedule-chronograph-on-wake = { $kind ->
        [full] Full scan
       *[quick] Quick scan
    } on wake
# kind=label wording=as-is
settings-schedule-chronograph-due = due · { $name }
# kind=tooltip wording=as-is note="The dial's centre while the plan waits; waiting = paused, day_off or mains (it waits for power)"
settings-schedule-chronograph-waiting = { $waiting ->
    [paused] Paused
    [day_off] Day off
   *[mains] Waiting for power
}
# kind=label wording=as-is note="Under the dial's centre while the plan waits; waiting = paused, day_off or mains (it waits for power)"
settings-schedule-chronograph-waiting-status = { $waiting ->
    [paused] paused
    [day_off] no scans today
   *[mains] on battery
}
# kind=label wording=as-is
settings-schedule-chronograph-the-next-scan-runs-once = the next scan runs once it is plugged in
# kind=label wording=as-is
settings-schedule-chronograph-next-scan = next scan { $time }
# kind=tooltip wording=as-is note="The dial's centre under the plan; state = running or next"
settings-schedule-chronograph-hub-title = { $state ->
    [running] Scanning now
   *[next] Next scan
}
# kind=label wording=as-is
settings-schedule-chronograph-due-now = due now
# kind=label wording=as-is
settings-schedule-chronograph-on-wake-2 = on wake
# kind=label wording=as-is
settings-schedule-chronograph-when-you-turn-it-on = when you turn it on, about { $time }
# kind=tooltip
settings-schedule-chronograph-next-dispatch = Next scan
# kind=label note="The dial's centre for a stack of deadlines; mode = reconcile or discovery"
settings-schedule-chronograph-hub-stack = { $mode ->
    [reconcile] { $count } full scans
   *[discovery] { $count } quick scans
}
# kind=label note="The dial's centre for one company's deadline; mode = reconcile or discovery"
settings-schedule-chronograph-hub-company = { $mode ->
    [reconcile] { $company } · full scan
   *[discovery] { $company } · quick scan
}
# kind=label wording=as-is
settings-schedule-chronograph-projected-through = projected through { $time }
# kind=toast note="Said when a stack of marks opens and a drag can split it; count = how many marks, time = the time they share, company = the one a drag moves out"
settings-schedule-chronograph-stack-movable = { $count } marks share { $time }. Set any time below, or drag the mark to move { $company } out.
# kind=toast note="Said when a stack of marks opens and none of them can move; count = how many marks, time = the time they share"
settings-schedule-chronograph-stack-locked = { $count } marks share { $time }. Every one of them is locked.
# kind=label wording=as-is
settings-schedule-chronograph-saving-schedule = Saving schedule…
# kind=label wording=as-is
settings-schedule-chronograph-drag-a-scan-to-move = Drag a scan to move it · click it for the exact time

## features/settings/ScheduleSection.tsx
# kind=heading wording=as-is
settings-schedule-section-how-scanning-works = How scanning works
# kind=sentence
settings-schedule-section-reads-every-company-s-whole = Reads the whole careers page of every company you follow, so it can also close a role that is gone. It runs when you turn the computer on, and at least once a day.
# kind=sentence
settings-schedule-section-looks-for-new-and-changed = Looks for new and changed roles at every company you follow, every { $repeat_hours } hours while the computer is on. It never closes a role.
# kind=label wording=as-is
settings-schedule-section-when-the-computer-is-off = When the computer is off
# kind=sentence
settings-schedule-section-nothing-runs-and-missed-scans = Nothing runs, and missed scans are not repeated: the next one runs when you turn it on. The schedule follows when you usually use the computer, so there's nothing to set.
# kind=label wording=as-is
settings-schedule-section-times-you-set = Times you set
# kind=sentence wording=as-is
settings-schedule-section-a-company-with-a-time = A company with a time of its own keeps it. Drag its mark, or click it to type a time.
# kind=sentence wording=as-is
settings-schedule-section-outer-orbit-is-the-full = Outer orbit is the full scan, inner is the quick scan; each arc is as long as the scan takes. Tinted hours are when the computer is usually off, and the hand is now.
# kind=label same-as=settings-chronograph-dial-quick-scan
settings-schedule-section-discovery = Quick scan
# kind=sentence
settings-schedule-section-probes-a-company-s-board = Looks at a company's careers page for new and changed roles. It can add or update a role, but never closes one.
# kind=label same-as=settings-chronograph-dial-full-scan
settings-schedule-section-reconciliation = Full scan
# kind=sentence
settings-schedule-section-the-authoritative-cycle-only-this = Only a full scan can close a role that has disappeared, and only after a complete read of the company's careers page.
# kind=label
settings-schedule-section-the-cycle = Scans together
# kind=sentence
settings-schedule-section-marks-coming-due-together-dispatch = Scans due at the same time run together, up to { $maxParallel } sites at once, so the arc shows how long they run, not just when they start.
# kind=label wording=as-is
settings-schedule-section-editing = Editing
# kind=sentence wording=as-is
settings-schedule-section-drag-a-mark-around-the = Drag a mark around the dial or click it to type a time. Times snap to 10 minutes. Marks a provider policy blocks stay locked.
# kind=sentence
settings-schedule-section-outer-orbit-is-reconciliation-inner = Outer orbit is full scans, inner is quick scans; tinted hours are overnight, and the hand is the current local time.
# kind=label wording=as-is
settings-schedule-section-first-scan-of-the-day = First scan of the day
# kind=label wording=as-is
settings-schedule-section-full-scan-done-by = Full scan, done by
# kind=label wording=as-is
settings-schedule-section-then-while-it-is-on = Then, while it is on
# kind=label wording=as-is
settings-schedule-section-a-quick-scan-every-hours = a quick scan every { $repeat_hours } hours
# kind=label wording=as-is
settings-schedule-section-days = Days
# kind=label wording=as-is
settings-schedule-section-power = Power
# kind=label wording=as-is
settings-schedule-section-only-when-plugged-in = Only when plugged in
# kind=label wording=as-is
settings-schedule-section-pause = Pause
# kind=label wording=as-is
settings-schedule-section-paused-until = Paused until
# kind=button wording=as-is
settings-schedule-section-resume = Resume
# kind=sentence wording=as-is note="The note under the plan's settings; learned = the sentence about when the computer is usually on"
settings-schedule-section-after-two-hours-or-more = { $learned } After two hours or more off, one full scan runs when you are back; missed scans are not repeated.
# kind=label wording=as-is
settings-schedule-section-need-attention = { $count ->
    [one] { $count } needs attention
   *[other] { $count } need attention
}
# kind=heading wording=as-is
settings-schedule-section-scan-clock = Scan clock
# kind=label wording=as-is
settings-schedule-section-next-scans = Next scans
# kind=label wording=as-is note="Under a planned scan in the list; companies = how many it reads, duration = how long it takes"
settings-schedule-section-companies = { $companies } companies · { $duration }
# kind=button wording=as-is
settings-schedule-section-companies-keep-a-time-you = { $count ->
    [one] { $count } company keeps a time you set
   *[other] { $count } companies keep a time you set
}
# kind=label wording=as-is
settings-schedule-section-upcoming = Upcoming
# kind=status note="Under the authoritative cycle's row; count = how many deadlines it dispatches, end = when it is projected to finish"
settings-schedule-section-bindings-projected-through = { $count ->
    [one] Full scan · projected through ~{ $end }
   *[other] { $count } scans · projected through ~{ $end }
}
# kind=label wording=as-is note="Under the upcoming list when it is cut short; count = how many rows are not shown"
settings-schedule-section-more-see-all-deadlines = +{ $count } more · see all deadlines
# kind=label
settings-schedule-section-discovery-cadence = Quick scan interval
# kind=status
settings-schedule-section-adapts-to-8-12-24h = adapts to 8 / 12 / 24h after empty quick scans
# kind=status
settings-schedule-section-only-this-cycle-can-close = only full scans can close missing roles
# kind=label wording=as-is
settings-schedule-section-provider-pressure = Provider pressure
# kind=label wording=as-is
settings-schedule-section-max = { $max_parallel_providers } max
# kind=label wording=as-is
settings-schedule-section-one-binding-per-provider-in = one binding per provider in each shard
# kind=label wording=as-is note="The line under the dial with the plan on; companies = every company, roster = how many each full scan reads"
settings-schedule-section-plan-roster = { $companies } companies · { $roster } in every full scan
# kind=label wording=as-is note="The line under the dial with the plan on; pinned = how many companies keep a time you set"
settings-schedule-section-plan-roster-pinned = { $companies } companies · { $roster } in every full scan · { $pinned } at a time you set
# kind=label wording=as-is note="The line under the dial with the plan on; excepted = how many companies need attention"
settings-schedule-section-plan-roster-excepted = { $companies } companies · { $roster } in every full scan · { $excepted } excepted
# kind=label wording=as-is note="The line under the dial with the plan on, with companies at a time you set and companies that need attention"
settings-schedule-section-plan-roster-pinned-excepted = { $companies } companies · { $roster } in every full scan · { $pinned } at a time you set · { $excepted } excepted
# kind=label wording=as-is note="The line under the dial with the per-company timers; companies = every company, scheduled = how many have a deadline"
settings-schedule-section-timers-roster = { $companies } companies · { $scheduled } scheduled
# kind=label wording=as-is note="The line under the dial with the per-company timers; excepted = how many companies need attention"
settings-schedule-section-timers-roster-excepted = { $companies } companies · { $scheduled } scheduled · { $excepted } excepted
# kind=status note="The line under the dial with the per-company timers; reconcileOnly = how many companies have no discovery pass"
settings-schedule-section-timers-roster-reconcile-only = { $companies } companies · { $scheduled } scheduled · { $reconcileOnly } full scan only
# kind=status note="The line under the dial with the per-company timers, with companies that need attention and companies with no discovery pass"
settings-schedule-section-timers-roster-excepted-reconcile-only = { $companies } companies · { $scheduled } scheduled · { $excepted } excepted · { $reconcileOnly } full scan only
# kind=heading wording=as-is
settings-schedule-section-every-company-s-scans = Every company's scans
# kind=sentence wording=as-is
settings-schedule-section-a-full-scan-reads-a = A full scan reads a company's whole careers page and can close a role that is gone. A quick scan looks for new and changed roles and never closes one.
# kind=label wording=as-is
settings-schedule-section-last-full-scan = Last full scan
# kind=label wording=as-is
settings-schedule-section-last-quick-scan = Last quick scan
# kind=label wording=as-is
settings-schedule-section-how-it-is-scanned = How it is scanned
# kind=label wording=as-is
settings-schedule-section-not-yet = Not yet
# kind=label wording=as-is
settings-schedule-section-not-available = Not available
# kind=label wording=as-is
settings-schedule-section-until = until { $cooldown_until }
# kind=heading wording=as-is
settings-schedule-section-persisted-deadlines = Persisted deadlines
# kind=sentence
settings-schedule-section-discovery-can-add-or-update = Quick scans can add or update roles but never close a missing role. A full scan closes roles only after a complete read of the careers page. Provider cooldown moves the eligible time without overwriting the company's natural deadline.
# kind=label wording=as-is
settings-schedule-section-provider-state = Provider state
# kind=label
settings-schedule-section-reconciliation-only = Full scans only
# kind=label
settings-schedule-section-non-authoritative = can't close roles
# kind=label wording=as-is
settings-schedule-section-not-scheduled = Not scheduled
# kind=label wording=as-is
settings-schedule-section-only-when-you-press-scan = Only when you press Scan now
# kind=label wording=as-is
settings-schedule-section-only-after-you-allow-it = Only after you allow it
# kind=label wording=as-is
settings-schedule-section-full-scan-at = full scan at { $reconcile_anchor_minute }
# kind=label wording=as-is
settings-schedule-section-quick-scan-at = quick scan at { $discovery_anchor_minute }
# kind=label wording=as-is note="How the plan scans a company with a time of its own; times = its times, as a list"
settings-schedule-section-its-own-time = Its own time: { $times }
# kind=label wording=as-is note="How the plan scans a company; scans = all (full and quick) or full (it has no quick scan)"
settings-schedule-section-planned-scans = { $scans ->
    [all] Every planned scan
   *[full] Full scans only
}
# kind=label wording=as-is
settings-schedule-section-only-when-you-scan = Only when you scan
# kind=label wording=as-is
settings-schedule-section-needs-your-ok = Needs your OK
# kind=label wording=as-is
settings-schedule-section-policy-denied = Policy denied
# kind=label wording=as-is
settings-schedule-section-cooling-down = Cooling down
# kind=label wording=as-is
settings-schedule-section-unscheduled = Unscheduled
# kind=label wording=as-is
settings-schedule-section-manual-priority = Manual priority
# kind=label wording=as-is
settings-schedule-section-paused = Paused
# kind=status
settings-schedule-section-provider-policy-denies-scheduled-collection = its site doesn't allow scheduled scans
# kind=label wording=as-is
settings-schedule-section-provider-scheduling-is-paused = provider scheduling is paused
# kind=status note="Followed companies the scheduler has not given scan times yet; its next run does"
settings-schedule-section-setting-scan-times = { $count ->
    [one] Setting scan times for { $count } new company.
   *[other] Setting scan times for { $count } new companies.
}
# kind=label wording=as-is
settings-schedule-section-cooling-down-until = cooling down until { $cooldown_until }
# kind=aria wording=as-is
settings-schedule-section-how-scanning-works-2 = How scanning works
# kind=label wording=as-is
settings-schedule-section-how-scanning-works-3 = How scanning works
# kind=label wording=as-is
settings-schedule-section-1-hour = 1 hour
# kind=label wording=as-is
settings-schedule-section-3-hours = 3 hours
# kind=label wording=as-is
settings-schedule-section-until-tomorrow = Until tomorrow
# kind=error wording=as-is
settings-schedule-section-couldn-t-save-that-change = Couldn't save that change. Try again.
# kind=aria wording=as-is
settings-schedule-section-plan-settings = Plan settings
# kind=label wording=as-is note="Under the full scan's done-by time; source = usual (learned) or set (typed); time = when it starts, companies = how many it reads"
settings-schedule-section-starts-about = { $source ->
    [usual] Your usual start, learned. Starts about { $time } · { $companies } companies
   *[set] Starts about { $time } · { $companies } companies
}
# kind=label wording=as-is note="Under the full scan's done-by time once a full scan is planned; duration = how long it takes"
settings-schedule-section-starts-about-duration = { $source ->
    [usual] Your usual start, learned. Starts about { $time } · { $companies } companies · { $duration }
   *[set] Starts about { $time } · { $companies } companies · { $duration }
}
# kind=label wording=as-is note="Under the full scan's done-by time when none is set; companies = how many it reads"
settings-schedule-section-no-time-set = No time set: it runs when you turn the computer on, and at least once a day · { $companies } companies
# kind=label wording=as-is note="Under the full scan's done-by time when none is set, once a full scan is planned; duration = how long it takes"
settings-schedule-section-no-time-set-duration = No time set: it runs when you turn the computer on, and at least once a day · { $companies } companies · { $duration }
# kind=label wording=as-is note="Clears the done-by time; fallback = usual (a learned start takes over) or none"
settings-schedule-section-clear-ready-by = { $fallback ->
    [usual] Use my usual start
   *[none] Clear
}
# kind=aria wording=as-is
settings-schedule-section-scan-days = Scan days
# kind=label wording=as-is note="How many days a week the plan scans; count = 1 to 7"
settings-schedule-section-days-a-week = { $count ->
    [7] Every day
    [one] { $count } day a week
   *[other] { $count } days a week
}
# kind=sentence wording=as-is note="Under Only when plugged in; power = waiting (on battery now and only scanning plugged in), mains (only scanning plugged in) or any"
settings-schedule-section-power-note = { $power ->
    [waiting] On battery now: the next scan waits for power.
    [mains] Scans wait while the computer is on battery.
   *[any] Scans also run on battery.
}
# kind=aria wording=as-is
settings-schedule-section-pause-scans = Pause scans
# kind=aria
settings-schedule-section-when-roleband-scans = When scans run
# kind=aria wording=as-is
settings-schedule-section-next-scans-2 = Next scans
# kind=label wording=as-is note="A planned scan in the list; kind = full or quick; state = running, ready (it has a done-by time), wake (it runs when the computer is turned on) or planned; time = when it is done by"
settings-schedule-section-run-title = { $state ->
    [running] { $kind ->
            [full] Full scan
           *[quick] Quick scan
        } · scanning
    [ready] { $kind ->
            [full] Full scan
           *[quick] Quick scan
        } · ready by { $time }
    [wake] { $kind ->
            [full] Full scan
           *[quick] Quick scan
        } · when you turn it on
   *[planned] { $kind ->
            [full] Full scan
           *[quick] Quick scan
        }
}
# kind=aria wording=as-is
settings-schedule-section-times-you-set-2 = Times you set
# kind=label wording=as-is note="Under a company with a time of its own; mode = reconcile (its full scan) or discovery (its quick scan)"
settings-schedule-section-scan-at-a-time-you-set = { $mode ->
    [reconcile] Full scan at a time you set
   *[discovery] Quick scan at a time you set
}
# kind=aria wording=as-is
settings-schedule-section-upcoming-scans = Upcoming scans
# kind=label wording=as-is note="An upcoming row's title once it is due; title = a company, or Authoritative cycle"
settings-schedule-section-title-due-now = { $title } · due now
# kind=label note="Under a company's upcoming deadline; mode = reconcile or discovery, provider = the careers site it reads"
settings-schedule-section-pass-provider = { $mode ->
    [reconcile] Full scan · { $provider }
   *[discovery] Quick scan · { $provider }
}
# kind=aria wording=as-is
settings-schedule-section-scheduler-policy = Scheduler policy
# kind=label wording=as-is note="Opens the sheet of every company's deadlines; schedule = plan or timers"
settings-schedule-section-deadlines-link = { $schedule ->
    [plan] Every company's scans
   *[timers] All persisted deadlines
}
# kind=label wording=as-is
settings-schedule-section-every-company-s-scans-2 = Every company's scans
# kind=label wording=as-is
settings-schedule-section-what-the-columns-mean = What the columns mean
# kind=label wording=as-is
settings-schedule-section-all-persisted-deadlines-2 = All persisted deadlines
# kind=label wording=as-is
settings-schedule-section-how-scheduling-safety-works = How scheduling safety works
# kind=aria wording=as-is
settings-schedule-section-schedule = Schedule

## features/settings/charts/plan.ts
# kind=label wording=as-is note="How long a scan takes, an hour or more; hours and minutes"
settings-plan-hours-minutes = { $hours } h { $minutes } min
# kind=label wording=as-is note="How long a scan takes, in whole hours"
settings-plan-hours = { $hours } h
# kind=sentence wording=as-is
settings-plan-still-learning-when-your-computer = Still learning when your computer is on: { $observed_days } of { $needed_days } days seen.
# kind=sentence note="The learned hours, the same every day; days = how many days it learned from; usual = all (on all day), off (usually off) or set (on the times in times)"
settings-plan-learned-every-day = Learned from the last { $days } days: your computer is { $usual ->
        [all] on all day
        [off] usually off
       *[set] on { $times }
    } every day.
# kind=sentence note="The learned hours when weekdays and weekends differ; weekdays and weekends = all (on all day), off (usually off) or set (on the times in weekdayTimes or weekendTimes)"
settings-plan-learned-weekdays-weekends = Learned from the last { $days } days: your computer is { $weekdays ->
        [all] on all day
        [off] usually off
       *[set] on { $weekdayTimes }
    } on weekdays and { $weekends ->
        [all] on all day
        [off] usually off
       *[set] on { $weekendTimes }
    } at weekends.
# kind=sentence note="The learned hours when only weekdays or only weekends were seen; usual = all (on all day), off (usually off) or set (on the times in times)"
settings-plan-learned = Learned from the last { $days } days: your computer is { $usual ->
        [all] on all day
        [off] usually off
       *[set] on { $times }
    }.
# kind=sentence note="The learned hours when the computer was not seen on; days = how many days it learned from"
settings-plan-learned-unseen = Learned from the last { $days } days: your computer is not seen on yet.
# kind=label wording=as-is note="Under the time in the dial's centre; kind = full or quick, companies = how many the scan reads"
settings-plan-companies = { $kind ->
        [full] Full scan
       *[quick] Quick scan
    } · { $companies } companies
# kind=label wording=as-is note="A planned scan's name; kind = full or quick"
settings-plan-scan-kind = { $kind ->
    [full] Full scan
   *[quick] Quick scan
}

## features/settings/charts/schedule.ts
# kind=sentence wording=as-is note="The dial's account for a screen reader under the plan, with no scan planned; runs = planned scans, pinned = companies at a time you set"
settings-schedule-24-hour-scan-clock-planned = 24-hour scan clock: { $runs } planned { $runs ->
        [one] scan
       *[other] scans
    }, and { $pinned } { $pinned ->
        [one] company
       *[other] companies
    } at a time you set.
# kind=sentence wording=as-is note="The dial's account for a screen reader under the plan; kind = full or quick, the next scan's kind; companies = how many it reads"
settings-schedule-24-hour-scan-clock-planned-next = 24-hour scan clock: { $runs } planned { $runs ->
        [one] scan
       *[other] scans
    }, the next a { $kind ->
        [full] full scan
       *[quick] quick scan
    } of { $companies } companies, and { $pinned } { $pinned ->
        [one] company
       *[other] companies
    } at a time you set.
# kind=sentence
settings-schedule-24-hour-chronograph-discovery-probes = 24-hour scan clock: { $probes } quick scans, { $reconciliations } full scans, and { $excluded } excluded or unscheduled companies.
# kind=label note="How many marks a stack holds and what they are; schedule = plan or timers; mode = reconcile or discovery"
settings-schedule-stack = { $count } { $schedule ->
        [plan] { $mode ->
            [reconcile] full scans
           *[discovery] quick scans
        }
       *[timers] { $mode ->
            [reconcile] full scans
           *[discovery] quick scans
        }
    }
# kind=label note="One deadline's name; schedule = plan or timers; mode = reconcile or discovery"
settings-schedule-mode-name = { $schedule ->
    [plan] { $mode ->
        [discovery] quick scan
       *[reconcile] full scan
    }
   *[timers] { $mode ->
        [discovery] quick scan
       *[reconcile] full scan
    }
}
# kind=sentence wording=as-is
settings-schedule-provider-policy-denies-scheduled-collection = Provider policy denies scheduled collection.
# kind=sentence wording=as-is
settings-schedule-provider-scheduling-is-paused = Provider scheduling is paused.
# kind=sentence wording=as-is
settings-schedule-scan-schedule-is-not-set = Scan schedule is not set up yet.
# kind=sentence wording=as-is
settings-schedule-cancel-the-queued-manual-scan = Cancel the queued manual scan before changing this time.

## features/settings/useDialDrag.ts
# kind=label wording=as-is
settings-use-dial-drag-drag-a-mark-to-reschedule = Drag a mark to reschedule · click it for an exact time
# kind=toast wording=as-is note="Said after a company's mark is moved; scan = the name of its scan, such as full scan"
settings-use-dial-drag-moved-to = { $company } { $scan } moved to { $time }.
# kind=error wording=as-is
settings-use-dial-drag-couldn-t-move-that-scan = Couldn't move that scan. Try again.

## features/settings/usePlanDrag.ts
# kind=sentence wording=as-is
settings-use-plan-drag-quick-scans-moved-one-at = Quick scans moved: one at { $time }.
# kind=sentence wording=as-is note="Said after the full scan is moved; start = its new start, doneBy = when it is done"
settings-use-plan-drag-full-scan-moved-to-done = Full scan moved to { $start }, done by { $doneBy }.

## routes/SettingsRoute.tsx
# kind=label wording=as-is
settings-route-settings-sections = Settings sections

## features/settings/charts/plan.ts (by hand)
# kind=label wording=as-is same-as=settings-chronograph-dial-usually-off
settings-plan-usually-off = Usually off
# kind=label wording=as-is
settings-plan-all-day = All day

## features/settings/ChronographInspector.tsx
# kind=label wording=as-is note="How often a pass repeats; unit = day or hour, count = how many"
settings-chronograph-inspector-every = { $unit ->
    [day] every { $count }d
   *[hour] every { $count }h
}
# kind=label wording=as-is note="In place of how often, for a pass that does not repeat"
settings-chronograph-inspector-no-cadence = —
# kind=label wording=as-is note="The name of a company's time field; scan = the name of its scan, such as full scan"
settings-chronograph-inspector-time = { $company } { $scan } time
# kind=label note="The answer beside Closes roles when the company's site cannot show that a role closed; its yes is the one the scan inspector says"
settings-chronograph-inspector-no = no

## features/settings/RecipesSection.tsx
# kind=label wording=as-is
settings-recipes-section-saved = saved { $created_at }
# kind=heading
settings-recipes-section-load-failed = Couldn't load recipes
# kind=sentence
settings-recipes-section-refresh-failed = Couldn't update recipes. Showing the last result.
# kind=heading
settings-recipes-section-versions-load-failed = Couldn't load this recipe's versions
# kind=sentence
settings-recipes-section-versions-refresh-failed = Couldn't update this recipe's versions. Showing the last result.

## features/settings/RetentionSection.tsx
# kind=label wording=as-is
settings-retention-section-days = { $days } days
# kind=label wording=as-is
settings-retention-section-due = { $days } ({ $due } due)
# kind=heading
settings-retention-section-load-failed = Couldn't load data retention

## features/settings/ScheduleChronograph.tsx
# kind=label wording=as-is
settings-schedule-chronograph-companies = { $count } companies
# kind=label wording=as-is note="How long until the next scan, an hour or more away"
settings-schedule-chronograph-in-hours-minutes = in { $hours }h { $minutes }m
# kind=label wording=as-is note="How long until the next scan, under an hour away"
settings-schedule-chronograph-in-minutes = in { $minutes }m
# kind=label wording=as-is
settings-schedule-chronograph-since = since { $time }

## features/settings/ScheduleSection.tsx
# kind=label wording=as-is
settings-schedule-section-every = every { $cadence }
# kind=status
settings-schedule-section-loading = Loading the scan schedule…
# kind=heading
settings-schedule-section-load-failed = Couldn't load the scan schedule
# kind=heading
settings-schedule-section-empty = No scan schedule yet
# kind=label note="Said in place of a clock time, for a scan that is running or already due"
settings-schedule-section-now = now

## features/settings/charts/plan.ts
# kind=label wording=as-is
settings-plan-min = { $minutes } min
# kind=label wording=as-is
settings-plan-to = { $start } to { $end }
# kind=label note="How long a scan takes while RoleBand has not yet timed one of its kind; duration is a length such as 41 min"
settings-plan-about = about { $duration }

## A schedule's cadence and quick-scan interval, in hours or days.
# kind=label wording=as-is
settings-schedule-hours = { $hours }h
# kind=label wording=as-is
settings-schedule-days = { $days }d

## Settings > Plugins. A plugin's own name,
## attribution and licence are third-party text and never appear in these
## messages except as an argument of an accessible name.
# kind=heading
settings-plugins-section-title = Plugins
# kind=sentence
settings-plugins-section-intro = Optional add-ons that bring more data and features.
# kind=aria
settings-plugins-section-search = Search plugins
# kind=status note="How many installed plugins are on"
settings-plugins-section-on-count = { $on } of { $total } on
# kind=sentence
settings-plugins-section-none = No plugins installed yet.
# kind=heading note="A card on Settings, Plugins: where listed companies' daily closing prices come from"
settings-price-feed-title = Stock prices
# kind=sentence note="The card's intro"
settings-price-feed-intro = Daily closing prices for listed companies, shown on their profiles and updated once a day.
# kind=name note="The card's one row: the price service, by its name"
settings-price-feed-source = Tiingo
# kind=sentence note="Under Tiingo: the terms the key comes with. A Get a free key link follows it"
settings-price-feed-source-terms = Free for personal use with your own key.
# kind=status note="First fact under Tiingo: whether a key is set and where. $origin: settings (saved here), environment (set outside the app, as ROLEBAND_TIINGO_API_KEY), none"
settings-price-feed-key-state = { $origin ->
    [settings] Key saved
    [environment] Key set outside the app
   *[none] No key yet
}
# kind=status note="A fact under Tiingo. $count companies with a live price; $date the newest close, a calendar day"
settings-price-feed-priced = { $count ->
    [one] { $count } company · latest close { $date }
   *[other] { $count } companies · latest close { $date }
}
# kind=status note="A fact under Tiingo: when the prices last updated. $ago is a relative time (2 hours ago)"
settings-price-feed-updated = updated { $ago }
# kind=button note="Opens the key dialog while no key is saved here"
settings-price-feed-add = Add key
# kind=button note="Opens the key dialog over a saved key"
settings-price-feed-replace = Replace key
# kind=button
settings-price-feed-remove = Remove key
# kind=heading note="The key dialog's title"
settings-price-feed-dialog-title = Tiingo key
# kind=sentence note="The key dialog's note: where the key comes from and where it goes. A Get a free key link follows it"
settings-price-feed-dialog-note = Paste the key from your Tiingo account. It stays on this computer and is sent only to Tiingo.
# kind=label note="The key field's label in the dialog"
settings-price-feed-dialog-field = Key
# kind=button note="The key dialog's submit. $choice: yes while saving"
settings-price-feed-dialog-save = { $choice ->
    [yes] Saving
   *[no] Save key
}
# kind=status note="The price service refused the saved key at the last update; shown while a key is set"
settings-price-feed-unauthorized = Tiingo refused the key at the last update. Check it in your Tiingo account and save it again.
# kind=status note="The price service's hourly limit stopped the last update part way"
settings-price-feed-rate-limited = Tiingo's hourly limit was reached. The remaining prices arrive once it resets.
# kind=status note="A key was saved. $check: ok when Tiingo answered its first request (one price is already in); other when Tiingo could not be reached or was busy"
settings-price-feed-saved = { $check ->
    [ok] Saved, and Tiingo answered. The other prices follow as its limits allow.
   *[other] Saved. Tiingo could not check the key yet; prices follow once it answers.
}
# kind=status note="A fact under Tiingo: prices still to fetch, held by Tiingo's limits. $time is when the next batch can start (in 40 minutes)"
settings-price-feed-waiting = { $count ->
    [one] { $count } more { $time }
   *[other] { $count } more { $time }
}
# kind=status note="A fact under Tiingo while prices are being fetched"
settings-price-feed-updating = Updating prices…
# kind=button note="Fetches the prices that are due now, within Tiingo's limits"
settings-price-feed-update-now = Update now
# kind=status note="Shown after the saved key is deleted"
settings-price-feed-removed = Removed. Prices already shown stay.
# kind=heading
settings-price-feed-load-failed = Couldn't load the stock price settings
# kind=sentence
settings-plugins-section-no-match = No installed plugin matches your search.
# kind=label note="An install's state, shown at the end of its row; needs_approval = never approved, or changed since it was"
settings-plugins-section-state = { $state ->
    [needs_approval] Needs approval
    [enabled] On
    [disabled] Off
    [paused] Paused
    [updating] Updating
    [removed] Uninstalled
   *[other] Installed
}
# kind=label note="What a plugin brings, joined into a list"
settings-plugins-section-slot = { $slot ->
    [pay_levels] comp bands
    [pay_observations] compensation estimates
    [company_facts] company facts
    [company_benefits] benefits
   *[other] other data
}
# kind=label
settings-plugins-section-answers = Answers { $slots }
# kind=label
settings-plugins-section-brings = Brings { $slots }
# kind=status
settings-plugins-section-waiting = Waiting for its first update
# kind=status note="Followed companies the plugin's own updates answer for (each read whole), out of every followed company: per kind of data on its settings page, the largest kind on the list row. read = those, companies = followed companies"
settings-plugins-section-read = { $companies ->
    [one] { $read } of { $companies } { -company(num: "one") } read
   *[other] { $read } of { $companies } { -company(num: "other") } read
}
# kind=status note="When the next scheduled update is due"
settings-plugins-section-next-update = next update { $when }
# kind=status
settings-plugins-section-paused = paused
# kind=aria note="The switch that turns one plugin on or off; the name is the plugin's own"
settings-plugins-section-use = Use { $name }
# kind=aria note="The gear that opens one plugin's settings; the name is the plugin's own"
settings-plugins-section-open-settings = Settings for { $name }
# kind=button note="Runs an update now; shown while the plugin is not updating"
settings-plugins-section-start = Start
# kind=aria note="Start's accessible name on a plugin's row of the list, so each row's Start is told apart; the name is the plugin's own"
settings-plugins-section-start-name = Start { $name }
# kind=button note="Stops an update and holds every scheduled one"
settings-plugins-section-pause = Pause
# kind=button same-as=settings-schedule-section-resume
settings-plugins-section-resume = Resume
# kind=label
settings-plugins-section-turn-on-first = Turn it on first
# kind=label note="Why Start waits on a plugin that is on but whose approval lapsed with an update"
settings-plugins-section-approve-first = Approve it first
# kind=label note="The sign that stands in for the list of installed plugins while plugins are not part of this release"
settings-plugins-section-coming-soon = Coming soon
# kind=sentence note="Under Coming soon: what arrives later is turning plugins on and managing them on this screen"
settings-plugins-section-coming-soon-note = Turning plugins on and managing them here arrives in a later release.
# kind=label note="The placeholder row for plugins that are not installed"
settings-plugins-section-more = More plugins
# kind=sentence note="Followed by the install command, shown as code the person copies"
settings-plugins-section-more-note = Finding and adding plugins here is coming. For now, install one from the command line, in the RoleBand folder:
# kind=sentence
settings-plugins-section-waiting-wake = The update starts when this Mac fully wakes.
# kind=sentence
settings-plugins-section-moved = { $moved ->
    [one] Estimates changed for { $moved } role
   *[other] Estimates changed for { $moved } roles
} at { $companies ->
    [one] { $companies } company
   *[other] { $companies } companies
} { $when }.
# kind=sentence
settings-plugins-section-pending = { $pending ->
    [one] Updating estimates: { $pending } role to go.
   *[other] Updating estimates: { $pending } roles to go.
}
# kind=button
settings-plugins-section-review = Review and approve
# kind=heading
settings-plugins-section-approve-title = Approve this plugin?
# kind=label note="The sites' robots rules for RoleBand, in the approval and on a plugin's settings"
settings-plugins-section-robots-heading = Site rules
# kind=status note="While the approval reads each declared site's robots file"
settings-plugins-section-robots-reading = Reading each site's rules
# kind=sentence note="The robots files could not be read at all just now"
settings-plugins-section-robots-failed = Couldn't read the sites' rules just now. It follows them as it finds them on each update.
# kind=sentence note="After a site's name (third-party text): what its robots file says for RoleBand"
settings-plugins-section-robots-site = { $state ->
    [none] sets no rule against RoleBand.
    [refused] won't show its rules, so RoleBand treats it as closed to it.
    [failed] couldn't be reached; its rules are read on each update.
   *[rules] asks RoleBand to skip these pages:
}
# kind=status note="Under a site's listed rules when there are more than shown"
settings-plugins-section-robots-more = and { $count } more
# kind=label note="Switch in the approval and Review: let the plugin read pages its sites' rules disallow"
settings-plugins-section-robots-allow = Read past these rules
# kind=sentence note="Under that switch: what allowing means for the user"
settings-plugins-section-robots-allow-note = These rules are followed unless you allow this, and the sites may slow or block this computer for it. If a site changes its rules, you'll be asked again.
# kind=heading note="Review dialog for a plugin's sites' robots rules"
settings-plugins-section-robots-title = Read past the sites' rules?
# kind=sentence note="Review dialog when no declared site sets a rule against RoleBand"
settings-plugins-section-robots-nothing = None of its sites sets a rule against RoleBand right now.
# kind=button note="Review dialog: allow the plugin past the rules shown"
settings-plugins-section-robots-allow-button = Allow
# kind=button note="Closes the Review dialog when there is nothing to allow"
settings-plugins-section-robots-close = Close
# kind=heading note="Asked before an approved plugin is turned on while it has not read every followed company"
settings-plugins-section-turn-on-title = Turn this plugin on?
# kind=sentence note="Turn-on dialog lead: the one-source rule"
settings-plugins-section-turn-on-lead = While it's on, what it brings replaces the built-in data for every company.
# kind=button note="Confirms turning an approved plugin on"
settings-plugins-section-turn-on = Turn on
# kind=sentence
settings-plugins-section-approve-lead = Approving lets it run on this Mac. While it's on, what it brings replaces the built-in data for every company. It runs on its own, reads only the sites below, and never changes your levels.
# kind=sentence note="Approve dialog, under the lead: what a followed company the plugin has not read yet shows while it is on"
settings-plugins-section-approve-gap = Until it reads a company, that company shows none of what it brings, and no built-in data in its place.
# kind=sentence note="Approve dialog: how far the plugin has read, per kind of data. slots = a list of kind-and-count items (settings-plugins-section-approve-slot)"
settings-plugins-section-approve-read = Read so far: { $slots }.
# kind=status note="One item of Read so far: a kind of data, then how many followed companies it has read, e.g. 'pay by level: 7 of 1,180 companies'"
settings-plugins-section-approve-slot = { $slot }: { $count }
# kind=sentence note="Approve dialog: how long the plugin takes to read the companies it has not, measured from its own updates. duration = e.g. 22 hr; pace = one company, e.g. 1 min"
settings-plugins-section-approve-left = Reading the rest takes about { $duration } of updates, at about { $pace } a company.
# kind=label
settings-plugins-section-approve-reads = Reads
# kind=label
settings-plugins-section-approve-updates = Updates
# kind=label
settings-plugins-section-approve-licence = Licence
# kind=label note="The credit the plugin's data requires, shown as the plugin states it (it often begins with its own label)"
settings-plugins-section-credit = Credit
# kind=label note="The plugin's code repository, shown as the plugin states it"
settings-plugins-section-approve-code = Code
# kind=sentence note="How the plugin presents itself to the sites it reads (its fetch tier)"
settings-plugins-section-approve-identity = { $identity ->
    [identified] It visits them openly, as RoleBand.
    [browser_identity] It visits them looking like a web browser.
    [tls_fingerprint] It visits them looking like a web browser, down to the connection.
    [headless] It visits them in a hidden web browser.
    [proxy] It visits them through another network.
   *[other] It visits them in a way this version can't describe.
}
# kind=sentence note="What one of its updates receives from RoleBand"
settings-plugins-section-approve-needs = { $need ->
    [followed_companies] It receives the list of companies you follow.
   *[other] It receives other data stored here.
}
# kind=sentence note="The company facts a plugin may supply, as a list of fact names"
settings-plugins-section-approve-facts = It may state each company's { $fields }.
# kind=label note="One company fact a plugin may supply, joined into a list"
settings-plugins-section-fact-field = { $field ->
    [display_name] name
    [ticker] stock ticker
    [is_public] whether it's public
    [headcount] headcount
    [hq_city] headquarters city
    [website] website
    [year_founded] year founded
    [logo_url] logo
    [brand_color] brand colour
   *[other] another detail
}
# kind=sentence note="A plugin's company facts never mix with RoleBand's: while it is on they replace RoleBand's, never sit beside them"
settings-plugins-section-approve-fact-rank = While it's on, they show in place of the built-in ones, never beside them.
# kind=sentence note="Shown when an update lapsed the approval of a plugin the person left on"
settings-plugins-section-approve-still-on = It's still on. It changed since you approved it, so it waits for you before it runs or answers again.
# kind=label note="How often a plugin updates"
settings-plugins-section-schedule = { $schedule ->
    [daily] Daily, when plugged in
    [weekly] Weekly, when plugged in
    [monthly] Monthly, when plugged in
    [manual] Only when you ask
   *[other] On its own schedule
}
# kind=button
settings-plugins-section-approve = Approve
# kind=button note="Approves a plugin the person turned on, then turns it on"
settings-plugins-section-approve-and-turn-on = Approve, turn on
# kind=button note="Approves a plugin that is still on after an update lapsed its approval: approving lets it run and answer again"
settings-plugins-section-approve-and-use = Approve, use again
# kind=heading
settings-plugins-section-remove-title = Remove this plugin's data?
# kind=sentence
settings-plugins-section-remove-lead = { $what ->
    [rows] This deletes the { $kinds } it added, and the estimates and compensation history worked out from them. Estimates go back to the built-in data. What it recorded as history stays, unread.
   *[history] This deletes the estimates worked out from it and what it noted about its own reading. The { $kinds } it recorded stays as history, unread while it's off.
}
# kind=label note="The name is the plugin's id, shown as written; typing it exactly confirms"
settings-plugins-section-remove-confirm = Type { $name } to confirm
# kind=button
settings-plugins-section-remove = Remove data
# kind=sentence
settings-plugins-section-removed = { $rows ->
    [0] Removed its data.
    [one] Removed { $rows } row.
   *[other] Removed { $rows } rows.
}
# kind=error note="A write on one plugin failed; review = reading what approval would show"
settings-plugins-section-failed = { $action ->
    [review] Couldn't load what it asks to do. Try again.
    [approve] Couldn't approve it. Try again.
    [on_after_approve] Approved, but couldn't turn it on. Try again.
    [on] Couldn't turn it on. Try again.
    [off] Couldn't turn it off. Try again.
    [update] Couldn't start the update. Try again.
    [pause] Couldn't pause it. Try again.
    [resume] Couldn't resume it. Try again.
    [schedule] Couldn't change how often it updates. Try again.
    [uninstall] Couldn't uninstall it. Try again.
    [remove] Couldn't remove its data. Try again.
    [robots] Couldn't save your choice about the sites' rules. Try again.
   *[other] That didn't work. Try again.
}
# kind=status
settings-plugins-section-loading = Loading plugins…
# kind=heading
settings-plugins-section-load-failed = Couldn't load plugins
# kind=sentence
settings-plugins-section-refresh-failed = Couldn't update plugins. Showing the last result.

## One plugin's settings (Settings > Plugins > a plugin).
# kind=button
settings-plugin-settings-back = All plugins
# kind=sentence
settings-plugin-settings-not-found = This plugin isn't installed.
# kind=sentence
settings-plugin-settings-needs-approval = It needs your approval before it can run: it's new, or it changed since you approved it.
# kind=heading
settings-plugin-settings-updates = Updates
# kind=label
settings-plugin-settings-how-often = How often
# kind=label note="A short choice in a segmented control"
settings-plugin-settings-option = { $schedule ->
    [daily] Daily
    [weekly] Weekly
    [monthly] Monthly
    [manual] When you ask
   *[other] Other
}
# kind=sentence note="What the plugin's author set; the person's choice replaces it"
settings-plugin-settings-suggests = { $schedule ->
    [daily] The plugin suggests daily. Scheduled updates wait until this Mac is plugged in.
    [weekly] The plugin suggests weekly. Scheduled updates wait until this Mac is plugged in.
    [monthly] The plugin suggests monthly. Scheduled updates wait until this Mac is plugged in.
    [manual] The plugin suggests updating only when you ask. Scheduled updates wait until this Mac is plugged in.
   *[other] Scheduled updates wait until this Mac is plugged in.
}
# kind=label
settings-plugin-settings-next = Next update
# kind=status note="When the next update happens, or why none is planned"
settings-plugin-settings-next-value = { $state ->
    [paused] Paused. Nothing updates on its own until you resume.
    [manual] Only when you press Start
    [off] None while it's off
    [first] At the next scan
    [approval] None until you approve it
    [continues] Soon, to finish the last update
   *[due] { $when }
}
# kind=label
settings-plugin-settings-last = Last update
# kind=status note="How one update ended, then when; stands alone. continues = it ended cleanly partway and the next update carries on"
settings-plugin-settings-run = { $outcome ->
    [clean] Updated { $when }
    [partial] Partly updated { $when }
    [continues] Partly updated { $when }, continuing soon
    [running] Updating now
    [stopped] Stopped { $when }
    [bounded] Ran out of time { $when }
    [error] Couldn't update { $when }
   *[other] Last ran { $when }
}
# kind=status note="How one update ended, when, and how far it got; read = how many companies it read, as 4 of 1,180 companies; stands alone. continues = it ended cleanly partway and the next update carries on"
settings-plugin-settings-run-progress = { $outcome ->
    [running] Updating { $read }
    [partial] Partly updated { $when }: { $read }
    [continues] Partly updated { $when }: { $read }, continuing soon
    [stopped] Stopped { $when } after { $read }
    [bounded] Ran out of time { $when } after { $read }
    [error] Couldn't update { $when } after { $read }
   *[other] Last ran { $when }: { $read }
}
# kind=status same-as=settings-plugins-section-approve-slot note="How one update ended and when, then the plugin's own words for what it did (third-party text, shown as written). run = how it ended and when, as Stopped 2 days ago; summary = the plugin's words"
settings-plugin-settings-run-summary = { $run }: { $summary }
# kind=status
settings-plugin-settings-never = Not updated yet
# kind=label note="How one update in Recent updates ended, beside when it started; continues = it ended cleanly partway and the next update carried on"
settings-plugin-settings-outcome = { $outcome ->
    [clean] Updated
    [partial] Partly updated
    [continues] Partly updated
    [running] Updating now
    [stopped] Stopped
    [bounded] Ran out of time
    [error] Couldn't update
   *[other] Ran
}
# kind=heading
settings-plugin-settings-brings = What it brings
# kind=status note="One kind of data while the plugin is not used, and why"
settings-plugin-settings-slot-state = { $state ->
    [approval] Not used until you approve it
   *[off] Not used while it's off
}
# kind=status note="What a followed company the plugin has not read shows for one kind of data, completing settings-plugin-settings-slot-gap"
settings-plugin-settings-slot-none = { $slot ->
    [pay_levels] no estimate
    [pay_observations] no compensation estimate
    [company_facts] no company size
    [company_benefits] no benefits
   *[other] none of it
}
# kind=sentence note="Under the read count: a followed company the plugin has not read yet shows nothing of this kind, not RoleBand's own. read = companies read, left = companies not read, none = settings-plugin-settings-slot-none"
settings-plugin-settings-slot-gap = { $read ->
    [0] Until it reads a company, that company shows { $none }.
   *[other] { $left ->
        [one] The other company shows { $none } until it's read.
       *[other] The other { $left } show { $none } until they're read.
    }
}
# kind=label note="In What it brings: how long the plugin takes to read the followed companies it has not"
settings-plugin-settings-left = Left to read
# kind=status note="Left to read, measured from the plugin's own updates. duration = e.g. 22 hr; pace = one company, e.g. 1 min"
settings-plugin-settings-left-value = About { $duration } of updates, at about { $pace } a company
# kind=label note="In What it brings: heads the numbers the plugin reports about its own data, such as how many followed companies its source does not list"
settings-plugin-settings-reports = The plugin says
# kind=status note="One number the plugin reported, then the plugin's own words for what it counts (third-party text, shown as written). value = the number, label = those words"
settings-plugin-settings-report = { $value } { $label }
# kind=status note="Under one reported number: when the plugin last reported it"
settings-plugin-settings-report-at = As of { $when }
# kind=status note="A plugin's settings, Site rules: whether it follows its sites' robots rules. hosts = sites that changed their rules, as a list; when = date allowed"
settings-plugin-settings-robots-state = { $state ->
    [lapsed] { $hosts } changed its rules since you allowed this; those pages are skipped until you review them
    [allowed] Reads past its sites' rules, as you allowed on { $when }
   *[follows] Follows each site's rules
}
# kind=button note="Opens the site rules dialog"
settings-plugin-settings-robots-review = Review
# kind=button note="Withdraws the consent: the plugin follows its sites' rules again"
settings-plugin-settings-robots-stop = Follow the rules
# kind=label
settings-plugin-settings-version = Version
# kind=heading
settings-plugin-settings-history = Recent updates
# kind=sentence
settings-plugin-settings-no-history = No updates yet.
# kind=status note="Rows one update published"
settings-plugin-settings-published = { $rows ->
    [one] { $rows } row
   *[other] { $rows } rows
}
# kind=heading
settings-plugin-settings-remove-heading = Remove
# kind=sentence
settings-plugin-settings-remove-note = { $what ->
    [rows] Removing its data deletes the { $kinds } it added; turn it off first.
   *[history] Removing its data deletes what was worked out from it; the { $kinds } it recorded stays as history.
} Uninstalling removes its code from this Mac and keeps its data, unread, until you remove it.
# kind=sentence note="Beside a held Remove data: the estimates still read the plugin's data"
settings-plugin-settings-remove-waiting = Estimates still read its data. Remove data waits until they're updated.
# kind=button
settings-plugin-settings-uninstall = Uninstall
# kind=heading
settings-plugin-settings-uninstall-title = Uninstall this plugin?
# kind=sentence
settings-plugin-settings-uninstall-lead = This turns it off and removes its code from this Mac. The data it added stays, unread, until you remove it. Installing it again needs your approval.
# kind=status
settings-plugin-settings-loading = Loading this plugin…
# kind=heading
settings-plugin-settings-load-failed = Couldn't load this plugin
# kind=sentence
settings-plugin-settings-refresh-failed = Couldn't update this plugin. Showing the last result.
