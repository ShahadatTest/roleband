## Radar

## Toolbar (features/opportunities/BoardToolbar.tsx)
# kind=label
radar-sort-best-fit = Best fit
# kind=label note="Best fit with nothing to rank by yet: the list is newest first"
radar-sort-best-fit-unranked = Best fit: newest first
# kind=sentence
radar-sort-best-fit-unranked-why = Best fit ranks roles by the ones you save and by your aim. Until you have either, they are newest first.
# kind=label
radar-sort-newest = Newest
# kind=label
radar-field-location = Location
# kind=label note="The base salary a row shows: posted, else estimated"
radar-field-pay = Base
# kind=tooltip note="The full words behind Base, for its hover and screen-reader name, and the sort menu's option, where a hover never shows"
radar-field-pay-full = Base salary
# kind=label
radar-sort-age = Age
# kind=label
radar-field-level = Level
# kind=label
radar-field-company = Company
# kind=label
radar-field-title = Title
# kind=aria
radar-search-label = Search titles and descriptions
# kind=tooltip note="The search field's placeholder"
radar-search-placeholder = Search titles and descriptions…
# kind=status note="Follows the count in the Not-for-me lens: 3 roles you marked not for me. A fragment until ResultsSummary takes whole sentences"
radar-count-not-for-me = you marked Not for me
# kind=status
radar-total-failed = Couldn't count the total
# kind=aria
radar-total-retry-aria = Count the total again
# kind=tooltip
radar-show-all-title = Back to the roles you have not marked
# kind=button
radar-show-all = Show all
# kind=tooltip
radar-reset-title = Clear every filter
# kind=button
radar-reset = Reset all
# kind=tooltip
radar-new-today-clear = Clear new
# kind=button note="New is the fixed wording: the roles posted in the last 2 days"
radar-new-today = New
# kind=tooltip
radar-reposted-today-clear = Clear reposted today
# kind=button
radar-reposted-today = Reposted today
# kind=label
radar-sort = Sort
# kind=aria
radar-order-reverse = Reverse order
# kind=aria
radar-sort-by = Sort by

## Search interpretation (SearchInterpretation.tsx); field names above
# kind=label note="A family, named Discipline"
radar-field-discipline = Discipline
# kind=label
radar-field-workplace = Workplace
# kind=label note="A base salary range read from the search"
radar-interp-pay-range = { $min }–{ $max }
# kind=label
radar-interp-pay-min = { $min }+
# kind=label
radar-interp-pay-max = < { $max }
# kind=aria
radar-interp-aria = Interpreted filters
# kind=label
radar-interp-label = Interpreted as

## Modes (filters.ts)
# kind=label
radar-mode-open = Open
# kind=label
radar-mode-closed = Closed

## Board actions (useBoardController.ts)
# kind=toast note="$title is the role's own title"
radar-save-failed = Couldn't save { $title }. Try again.
# kind=toast
radar-unsave-failed = Couldn't remove { $title } from Saved. Try again.
# kind=toast
radar-restore-failed = Couldn't restore { $title }. Try again.
# kind=toast note="$value is the employer's own team or department name"
radar-exclude-done = { $count ->
    [one] { $count } role with “{ $value }” left your radar. Change this in Profile › Looking for.
   *[other] { $count } roles with “{ $value }” left your radar. Change this in Profile › Looking for.
}
# kind=toast
radar-exclude-failed = Couldn't save that for “{ $value }”. Try again.

## The list (BoardScreen.tsx)
# kind=label
radar-loading = Loading your radar…
# kind=heading
radar-load-failed = Couldn't load your radar
# kind=heading
radar-filters-load-failed = Couldn't load the filters
# kind=status note="A scan ended while the Board was open; the list waits for the reader"
radar-board-fresh-more = { $count ->
    [one] { $count } more { -role(num: "one") } matches since this list loaded.
   *[other] { $count } more { -role(num: "other") } match since this list loaded.
}
# kind=status note="A scan ended and changed the list without adding to it"
radar-board-fresh-changed = This list has changed since it loaded.
# kind=button
radar-board-fresh-show = Show the update
# kind=heading
radar-empty-not-for-me-title = Nothing marked “Not for me”
# kind=empty
radar-empty-not-for-me = Anything you mark Not for me waits here, in case you change your mind.
# kind=heading
radar-empty-closed-title = Nothing has closed yet
# kind=empty
radar-empty-closed = A role lands here when it is no longer on its careers page.
# kind=heading note="The board's own filters leave nothing, after every company has been read once"
radar-empty-filtered-title = No roles match these filters
# kind=button
radar-empty-filtered-clear = Clear every filter
# kind=heading note="Every followed company read once and no role fits, while the person follows only some companies; $count is how many they follow"
radar-empty-few-title = { $count ->
    [one] No roles fit yet at the { $count } company you follow
   *[other] No roles fit yet at the { $count } companies you follow
}
# kind=empty note="counted: $more is how many more companies can be scanned, rounded; other: that number is not known"
radar-empty-few = { $choice ->
    [counted] About { $more } more companies can be scanned. Following more of them finds more roles that fit.
   *[other] Following more companies finds more roles that fit.
}
# kind=link note="Opens the companies the person follows"
radar-empty-follow-more = Follow more companies
# kind=link note="Opens Profile, Looking for"
radar-empty-change-looking-for = Change what you're looking for
# kind=heading note="The person follows every company and no role fits"
radar-empty-fit-title = Nothing fits what you're looking for yet
# kind=empty note="checking: the companies beyond the list are still being checked, $checked of $total so far; done: every company the person follows has been read"
radar-empty-fit = { $choice ->
    [checking] Checking the other companies, { $checked } of { $total } so far. Roles that fit appear here as they're found.
   *[done] Every company you follow was read, and none has an open role that fits. Each is checked again every few hours.
}

## The first scan: until every followed company has been read once
# kind=heading note="Before the first scan starts, or while it is lined up"
radar-first-scan-starting-title = Your first scan is about to start
# kind=empty
radar-first-scan-starting = It starts within a few minutes. New roles appear here as they're found.
# kind=heading note="Animated dots follow it on screen"
radar-first-scan-running-title = Your first scan is running
# kind=empty note="$read of the $total followed companies have been read at least once"
radar-first-scan-progress = { $read } of { $total } companies read. New roles appear here as they're found.
# kind=empty note="The scan is running and the count is not known yet"
radar-first-scan-progress-unknown = New roles appear here as they're found.
# kind=empty note="A third of the companies read and still no role fits; $link is the link text 'what you're looking for', opening Profile"
radar-first-scan-nothing-yet = { $read } of { $total } companies read, none with a role that fits { $link } so far.
# kind=link note="Inside radar-first-scan-nothing-yet; opens Profile, Looking for"
radar-first-scan-looking-for = what you're looking for
# kind=empty note="When to look again. soon: before the pace is known; hour: over sixty minutes; almost: under a minute"
radar-first-scan-back = { $when ->
    [hour] Check back in an hour or so.
    [almost] Almost done.
   *[soon] Check back in a few minutes.
}
# kind=empty note="When to look again, from the pace of the scan so far"
radar-first-scan-back-minutes = { $minutes ->
    [one] Check back in about { $minutes } minute.
   *[other] Check back in about { $minutes } minutes.
}
# kind=heading
radar-first-scan-held-title = Your first scan is on hold
# kind=empty note="$read of the $total followed companies read at least once; the hold's reason follows"
radar-first-scan-held-count = { $read } of { $total } companies read.
# kind=empty note="Why the scan waits. $reason is a code: waiting_for_mains (on battery), waiting_for_wake (the computer is asleep), schema_pending and dependencies_pending (an update is half installed), busy_external (another scan holds the lock), supervisor_stale (the background service is not running), backoff (a job site asked to slow down), paused (a job site is paused), preflight_running and preflight_failed (the code is checked first)"
radar-first-scan-held = { $reason ->
    [waiting_for_mains] Your Mac is on battery. The scan continues when you plug in.
    [waiting_for_wake] The scan continues when your Mac wakes.
    [schema_pending] An update is finishing. The scan continues right after.
    [dependencies_pending] An update is finishing. The scan continues right after.
    [busy_external] Another scan is running. Yours starts right after.
    [supervisor_stale] The background service isn't running. Restart the app to continue.
    [backoff] Some job sites asked to slow down. The scan continues on its own.
    [preflight_failed] The scan is held until its checks pass.
   *[other] The scan continues on its own once this clears.
}
# kind=empty note="A job site asked to slow down; $time is a formatted time of day"
radar-first-scan-held-until = Some job sites asked to slow down. The scan continues at { $time }.
# kind=heading note="Stopped by the person, or by an error"
radar-first-scan-stopped-title = Your first scan is stopped
# kind=empty note="$read of the $total followed companies read at least once"
radar-first-scan-stopped = { $read } of { $total } companies read. Scanning again picks up where it stopped.
# kind=button
radar-first-scan-scan-now = Scan now
# kind=heading note="No followed company is scanned on its own"
radar-first-scan-none-title = No companies to scan yet
# kind=empty
radar-first-scan-none = Follow a few companies and your first scan starts.
# kind=link note="Opens the companies the person follows"
radar-first-scan-follow = Follow companies
# kind=status note="During the first scan, while the board has no role because of its own filters"
radar-first-scan-filtered = Some filters are on, so fewer roles show here.
# kind=status note="Above the list while the first scan runs; $dots is three animated dots, hidden from screen readers"
radar-first-scan-line = Still reading companies{ $dots } { $read } of { $total } read. More roles appear as they're found.
# kind=sentence note="Under the last page while the first scan is still reading; $count companies are left"
radar-end-scanning = { $count ->
    [one] That's everything so far. { $count } more company to read.
   *[other] That's everything so far. { $count } more companies to read.
}
# kind=sentence note="Under the last page, every followed company read once, no board filter on, while the person follows only some companies; $follow is the link 'Follow more companies', $change the link 'change what you're looking for'"
radar-end-few = That's every role that fits at the companies you follow. Something missing? { $follow }, or { $change }.
# kind=link note="Inside radar-end-few, after a comma; opens Profile, Looking for"
radar-end-change-looking-for = change what you're looking for
# kind=sentence note="Under the last page when the person follows every company and no board filter is on; $change is the link 'Change what you're looking for'"
radar-end-fit = That's every role that fits at the companies you follow. Something missing? { $change }.
# kind=sentence note="Under the last page with a board filter on; $clear is the button 'Clear every filter'"
radar-end-filtered = That's everything that matches these filters. { $clear } to see more.
# kind=link note="Under the empty board of an install that left setup for later; opens setup"
radar-empty-first-scan-finish = Finish setting up
# kind=heading
radar-exact-head = Exact match ({ $count })
# kind=link
radar-show-other = { $count ->
    [one] Show { $count } other match
   *[other] Show { $count } other matches
}
# kind=heading note="Roles that match the search less closely; never Related, a Duplicates verdict"
radar-other-head = Other matches ({ $count })
# kind=sentence
radar-truncated-other = Other matches shows the best { $shown } of { $matched }. Narrow the filters to see the rest.
# kind=sentence
radar-truncated = Showing the best { $shown } of { $matched } matching roles, best fit first. Sort by Newest or narrow the filters to see the rest.
# kind=sentence
radar-level-not-placed-note = The posting names no level, or one in the company's own terms that isn't matched yet.
# kind=link note="$value is the employer's own team or department name"
radar-exclude-offer = Not for me: all of “{ $value }”

## The filter register (BoardFilters.tsx); group titles are the field names above
# kind=label
radar-field-career-track = Career track
# kind=label
radar-field-world = World
# kind=aria
radar-filter-company-aria = Filter by company
# kind=aria
radar-filter-location-aria = Filter by location
# kind=aria
radar-filter-level-aria = Filter by level
# kind=aria
radar-filter-discipline-aria = Filter by discipline
# kind=aria
radar-filter-track-aria = Filter by career track
# kind=aria
radar-filter-workplace-aria = Filter by workplace
# kind=aria
radar-filter-world-aria = Filter by world
# kind=empty
radar-filter-no-companies = No companies match.
# kind=empty
radar-filter-no-locations = No locations match.
# kind=label
radar-filter-more = More filters
# kind=label note="Filters by the role's age clock, not a posted date"
radar-filter-listed-within = Listed within
# kind=label
radar-filter-any = Any
# kind=label note="A number of days, abbreviated: 7d"
radar-filter-days = { $count }d
# kind=label
radar-filter-discloses-pay = Posts a range
# kind=label
radar-filter-pay-from = Base from
# kind=tooltip note="The full words behind the Base from filter's title"
radar-filter-pay-from-full = Base salary from
# kind=label
radar-filter-pay-up-to = Base up to
# kind=tooltip note="The full words behind the Base up to filter's title"
radar-filter-pay-up-to-full = Base salary up to
# kind=tooltip note="Placeholder of the lower bound"
radar-filter-min = Min
# kind=tooltip note="Placeholder of the upper bound"
radar-filter-max = Max
# kind=aria
radar-filter-pay-min-aria = Lowest base salary
# kind=aria
radar-filter-pay-max-aria = Highest base salary
# kind=label
radar-filter-showing = Showing
# kind=label
radar-filter-unread-only = Unread only
