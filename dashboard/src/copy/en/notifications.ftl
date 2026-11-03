## notifications: moved as it was found (wording=as-is)

## features/notifications/DigestPanel.tsx
# kind=sentence wording=as-is
notifications-digest-panel-more-roles-opened-today = { $count ->
    [one] { $hidden } more role opened today.
   *[other] { $hidden } more roles opened today.
}
# kind=sentence wording=as-is
notifications-digest-panel-unranked-set-an-intent-statement = { $choice ->
    [yes] Best fit first, against your current intent.
   *[no] Unranked - set an intent statement or save a few roles to rank these.
}

## features/notifications/NotificationFilters.tsx
# kind=heading wording=as-is
notifications-notification-filters-status = Status
# kind=label wording=as-is
notifications-notification-filters-read-status = Read status
# kind=label wording=as-is
notifications-notification-filters-all = All
# kind=label wording=as-is
notifications-notification-filters-unread = Unread
# kind=heading wording=as-is
notifications-notification-filters-priority = Priority
# kind=label wording=as-is
notifications-notification-filters-priority-2 = Priority
# kind=label wording=as-is
notifications-notification-filters-high = High
# kind=heading wording=as-is
notifications-notification-filters-scans = Scans
# kind=aria wording=as-is
notifications-notification-filters-filter-by-scan-event = Filter by scan event
# kind=heading wording=as-is
notifications-notification-filters-roles = Roles
# kind=aria wording=as-is
notifications-notification-filters-filter-by-role-event = Filter by role event

## features/notifications/NotificationRow.tsx
# kind=label wording=as-is
notifications-notification-row-unread = unread
# kind=label wording=as-is
notifications-notification-row-show-details = { $choice ->
    [yes] Hide details
   *[no] Show details
}
# kind=aria wording=as-is
notifications-notification-row-copy-notification-text = Copy notification text
# kind=label wording=as-is
notifications-notification-row-copy-notification-text-2 = { $choice ->
    [yes] Your browser blocked clipboard access
   *[no] Copy notification text
}
# kind=label wording=as-is
notifications-notification-row-mark-read = { $choice ->
    [yes] Mark unread
   *[no] Mark read
}
# kind=aria wording=as-is
notifications-notification-row-dismiss = Dismiss
# kind=heading wording=as-is
notifications-notification-row-dismiss-2 = Dismiss
# kind=label wording=as-is
notifications-notification-row-details-for = Details for { $title }
# kind=label wording=as-is
notifications-notification-row-copy-summary = Copy summary
# kind=label wording=as-is
notifications-notification-row-copy-full-details = Copy full details

## features/notifications/NotificationScreen.tsx
# kind=button wording=as-is
notifications-notification-screen-reset-all = Reset all
# kind=label wording=as-is
notifications-notification-screen-nothing-unread = Nothing unread
# kind=button wording=as-is
notifications-notification-screen-mark-all-read = Mark all read
# kind=label wording=as-is
notifications-notification-screen-nothing-here-yet = { $choice ->
    [yes] Nothing matches
   *[no] Nothing here yet
}
# kind=sentence
notifications-notification-screen-scans-new-roles-for-you = { $choice ->
    [yes] No notification matches these filters.
   *[no] Scans, new roles for you, posted range changes, and news about roles you saved land here.
}
# kind=label wording=as-is
notifications-notification-screen-search-notifications = Search notifications
# kind=label wording=as-is
notifications-notification-screen-find-a-role-company-or = Find a role, company or scan…
# kind=heading wording=as-is
notifications-notification-screen-clear-every-filter-and-lens = Clear every filter and lens
# kind=status
notifications-notification-screen-loading = Loading notifications…
# kind=heading
notifications-notification-screen-load-failed = Couldn't load notifications
# kind=sentence
notifications-notification-screen-refresh-failed = Couldn't update notifications. Showing the last result.

## features/notifications/diagnostics/NotifDiagnostics.tsx
# kind=label wording=as-is
notifications-notif-diagnostics-run = Run
# kind=label wording=as-is
notifications-notif-diagnostics-status = Status
# kind=label wording=as-is
notifications-notif-diagnostics-duration = Duration
# kind=label wording=as-is
notifications-notif-diagnostics-sources-ok = Sources OK
# kind=heading wording=as-is
notifications-notif-diagnostics-errors = Errors ({ $length })
# kind=heading wording=as-is
notifications-notif-diagnostics-drift-alerts = Drift alerts ({ $length })
# kind=heading wording=as-is
notifications-notif-diagnostics-per-source = Per-source
# kind=label wording=as-is
notifications-notif-diagnostics-source = Source
# kind=label wording=as-is
notifications-notif-diagnostics-scanned = Scanned
# kind=label wording=as-is
notifications-notif-diagnostics-kept = Kept
# kind=label wording=as-is
notifications-notif-diagnostics-new = New
# kind=label wording=as-is
notifications-notif-diagnostics-closed = Closed
# kind=label wording=as-is
notifications-notif-diagnostics-took = Took
# kind=label wording=as-is
notifications-notif-diagnostics-error = error
# kind=label wording=as-is
notifications-notif-diagnostics-drift = { $drift_count } drift
# kind=label wording=as-is
notifications-notif-diagnostics-ok = ok
# kind=label wording=as-is
notifications-notif-diagnostics-drift-recorded = drift recorded
# kind=label wording=as-is
notifications-notif-diagnostics-unknown-error = unknown error
# kind=toast wording=as-is
notifications-notif-diagnostics-run-started-took = Run #{ $value } ({ $value2 }) · started { $value3 } · took { $duration_seconds }
# kind=toast wording=as-is
notifications-notif-diagnostics-errors-2 = Errors ({ $length }):
# kind=toast wording=as-is
notifications-notif-diagnostics-drift-alerts-2 = Drift alerts ({ $length }):
# kind=toast wording=as-is
notifications-notif-diagnostics-per-source-2 = Per-source:
# kind=toast wording=as-is
notifications-notif-diagnostics-source-scanned-kept-new-closed = source | scanned | kept | new | closed | took | status
# kind=toast wording=as-is
notifications-notif-diagnostics-notes = Notes: { $notes }
# kind=label wording=as-is
notifications-notif-diagnostics-copy-blocked = { $choice ->
    [yes] Copied
   *[no] Copy blocked
}
# kind=label wording=as-is
notifications-notif-diagnostics-your-browser-blocked-clipboard-access = Your browser blocked clipboard access
# kind=label wording=as-is
notifications-notif-diagnostics-text = { $choice ->
    [v1] Copied to clipboard
    [v2] Clipboard blocked by browser
   *[v3] { "" }
}

## features/notifications/moved-page/MovedPagePanel.tsx
# kind=button wording=as-is
notifications-moved-page-panel-stop-following = Stop following
# kind=button wording=as-is
notifications-moved-page-panel-find-new-careers-page = Find new careers page
# kind=label wording=as-is
notifications-moved-page-panel-looking-for-s-new-careers = Looking for { $display }'s new careers page…
# kind=button wording=as-is
notifications-moved-page-panel-not-this-one = Not this one
# kind=label wording=as-is
notifications-moved-page-panel-careers-page-link = Careers page link
# kind=button wording=as-is
notifications-moved-page-panel-check = Check
# kind=sentence
notifications-moved-page-panel-roleband-couldn-t-find-it = { $choice ->
    [yes] That link isn't a careers page that can be read.
   *[no] Couldn't find it. Paste the link to { $display }'s new careers page.
}
# kind=sentence wording=as-is
notifications-moved-page-panel-couldn-t-look-just-now = Couldn't look just now. Try again, or paste its link.
# kind=label wording=as-is
notifications-moved-page-panel-s-careers-page = { $display }'s careers page
# kind=label wording=as-is
notifications-moved-page-panel-use-this-careers-page = { $choice ->
    [yes] Switching…
   *[no] Use this careers page
}
# kind=sentence wording=as-is
notifications-moved-page-panel-paste-the-link-to-s = Paste the link to { $display }'s new careers page.

## features/notifications/moved-page/model.ts
# kind=label wording=as-is
notifications-model-roles = { $count ->
    [one] { $count2 } role
   *[other] { $count2 } roles
}
# kind=sentence wording=as-is
notifications-model-that-page-lists = { $choice ->
    [yes] That page answers.
   *[no] That page lists { $roles }.
}
# kind=sentence wording=as-is
notifications-model-s-own-careers-page-links = { $choice ->
    [yes] { $display }'s own careers page links to it.
   *[no] { $display2 }'s own careers page links to it: { $roles }.
}
# kind=sentence
notifications-model-found-it-roleband-saw-at = Found it: { $shared } seen at { $display } before.
# kind=label wording=as-is
notifications-model-of-them-roles = { $count ->
    [one] 1 of them a role
   *[other] { $shared } of them roles
}
# kind=sentence
notifications-model-found-it-roleband-saw-at-2 = Found it: { $roles }, { $seen } seen at { $display } before.

## features/notifications/sync-progress/SyncContribution.tsx
# kind=label
notifications-sync-contribution-what-has-landed = Finished companies
# kind=label same-as=notifications-model-roles
notifications-sync-contribution-opportunities = { $count ->
    [one] { $total } role
   *[other] { $total } roles
}
# kind=label
notifications-sync-contribution-landed = finished
# kind=label
notifications-sync-contribution-scraping = scanning
# kind=button
notifications-sync-contribution-queued = waiting
# kind=label wording=as-is
notifications-sync-contribution-failed = failed
# kind=label wording=as-is
notifications-sync-contribution-blocked = blocked
# kind=label wording=as-is
notifications-sync-contribution-failed-2 = Failed: { $failed }
# kind=status
notifications-sync-contribution-blocked-the-source-is-refusing = Blocked by their careers page: { $blocked }
# kind=status
notifications-sync-contribution-paused-while-this-computer = Paused while this computer slept or was offline: { $suspended }
# kind=label
notifications-sync-contribution-partial = Partly scanned: { $degraded }
# kind=status
notifications-sync-contribution-scanned-nothing-in-scope = Scanned, no roles for you: { $emptyButFine }
# kind=label wording=as-is
notifications-sync-contribution-more = +{ $length } more
# kind=label
notifications-sync-contribution-opportunities-2 = { $label } · { $count ->
    [one] { $value } role
   *[other] { $value } roles
}
# kind=aria
notifications-sync-contribution-roles-found-per-company = Roles per finished company
# kind=aria
notifications-sync-contribution-opportunities-3 = { $label }: { $value ->
    [one] { $value } role
   *[other] { $value } roles
}
# kind=label wording=as-is
notifications-sync-contribution-more-2 = { $join } +{ $value } more

## features/notifications/sync-progress/SyncProgressPanel.tsx
# kind=sentence
notifications-sync-progress-panel-sources-failed-see-the-run = { $count ->
    [one] { $companiesFailed } company failed. See the scan summary when this finishes.
   *[other] { $companiesFailed } companies failed. See the scan summary when this finishes.
}
# kind=sentence
notifications-sync-progress-panel-nothing-is-written-to-the = Roles reach your radar as each company is scanned.
# kind=label wording=as-is
notifications-sync-progress-panel-scan-progress = Scan progress: { $pHASE_LABEL }
# kind=label wording=as-is
notifications-sync-progress-panel-companies-scanned = Companies scanned
# kind=label
notifications-sync-progress-panel-still-scraping = Still scanning
# kind=label wording=as-is
notifications-sync-progress-panel-roles-found = Roles found
# kind=label
notifications-sync-progress-panel-recorded = From finished companies

## features/notifications/sync-progress/SyncStream.tsx
# kind=label
notifications-sync-stream-scraping-now = Scanning now
# kind=label same-as=notifications-sync-progress-panel-still-scraping note="Under the big number in the scan box: roles found at companies whose scan has not ended. Most are already on the radar"
notifications-sync-stream-held = Still scanning
# kind=label note="Floor of the scan box: roles from companies whose scan has ended. The box is narrow: keep it to two words"
notifications-sync-stream-on-disk = { $written } finished
# kind=label same-as=notifications-sync-progress-panel-roles-found note="Caption under the scan box, naming what it holds: every role this scan found"
notifications-sync-stream-in-memory = Roles found
# kind=sentence
notifications-sync-stream-no-update-for-this-run = No update for { $staleMs }. This scan may have stopped.
# kind=label
notifications-sync-stream-every-source-recorded = Scan finished
# kind=label
notifications-sync-stream-writing-collected-sources-to-the = Adding the last roles
# kind=label
notifications-sync-stream-running-post-passes = Finishing up
# kind=status
notifications-sync-stream-waiting-on-the-first-source = { $choice ->
    [yes] Waiting for the first company · { $companiesQueued } waiting
   *[no] Waiting for the first company
}
# kind=sentence
notifications-sync-stream-opportunities-held-in-memory-written = { $choice ->
    [yes] Scanning now: { $join }. { $written ->
        [one] { $written } role from finished companies
       *[other] { $written } roles from finished companies
    }, { $held } from companies still scanning.
   *[no] { $progress }. { $written ->
        [one] { $written } role from finished companies
       *[other] { $written } roles from finished companies
    }, { $held } from companies still scanning.
}
# kind=label wording=as-is
notifications-sync-stream-path = path("{ $path }")

## features/notifications/sync-progress/model.ts
# kind=label wording=as-is
notifications-model-scanning-companies = Scanning companies
# kind=label same-as=notifications-sync-stream-writing-collected-sources-to-the note="The short step after scanning that finishes the companies the live scan did not"
notifications-model-recording-roles = Adding the last roles
# kind=label wording=as-is same-as=notifications-sync-stream-running-post-passes
notifications-model-finishing-up = Finishing up
# kind=label
notifications-model-sources = { $companiesCollected }/{ $companiesTotal } companies
# kind=status
notifications-model-scanned-found = { $companies } scanned · { $opportunitiesDetected ->
    [one] { $opportunitiesDetected } role found
   *[other] { $opportunitiesDetected } roles found
}

## features/notifications/useNotificationsController.ts
# kind=label
notifications-use-notifications-controller-could-not = Couldn't { $what }
# kind=label wording=as-is
notifications-use-notifications-controller-mark-it-read = mark it read
# kind=label wording=as-is
notifications-use-notifications-controller-mark-it-unread = { $choice ->
    [yes] mark it read
   *[no] mark it unread
}
# kind=label wording=as-is
notifications-use-notifications-controller-dismiss-that-notification = dismiss that notification
# kind=label wording=as-is
notifications-use-notifications-controller-removed-from-your-notifications = “{ $title }” removed from your notifications
# kind=label wording=as-is
notifications-use-notifications-controller-undo = Undo
# kind=label wording=as-is
notifications-use-notifications-controller-undo-that = undo that
# kind=label wording=as-is
notifications-use-notifications-controller-use-that-careers-page = use that careers page
# kind=status
notifications-use-notifications-controller-roleband-now-reads-s-new = Now reading { $display }'s new careers page
# kind=label wording=as-is
notifications-use-notifications-controller-stop-following = stop following { $display }
# kind=label wording=as-is
notifications-use-notifications-controller-stopped-following = Stopped following { $display }
# kind=label wording=as-is
notifications-use-notifications-controller-mark-them-read = mark them read
# kind=label wording=as-is
notifications-use-notifications-controller-marked-notifications-read = { $count ->
    [one] Marked { $updated } notification read
   *[other] Marked { $updated } notifications read
}

## features/notifications/filters.ts (by hand)
# kind=label wording=as-is
notifications-category-scanning = Scanning
# kind=label wording=as-is
notifications-category-scan-problems = Scan problems
# kind=label wording=as-is
notifications-category-ran-out-of-time = Ran out of time
# kind=label wording=as-is
notifications-category-scan-failed = Scan failed
# kind=label wording=as-is
notifications-category-coverage = Coverage
# kind=label wording=as-is
notifications-category-for-you = For you
# kind=label wording=as-is
notifications-category-reminders = Reminders
# kind=label wording=as-is
notifications-category-saved = Saved
# kind=label
notifications-category-pay-up = Posted range up
# kind=label
notifications-category-pay-down = Posted range down
# kind=label wording=as-is
notifications-category-reposted = Reposted
# kind=label wording=as-is
notifications-category-long-open = Long-open
# kind=label wording=as-is
notifications-category-changed = Changed
# kind=label wording=as-is same-as=notifications-notif-diagnostics-closed
notifications-category-closed = Closed

## features/notifications/diagnostics/NotifDiagnostics.tsx

## features/notifications/sync-progress/SyncProgressPanel.tsx
# kind=label wording=as-is
notifications-sync-progress-panel-of = of { $companiesTotal }
# kind=label
notifications-sync-progress-panel-pending = { $opportunitiesPending } still scanning

## Server notifications: the keys the backend writes in `meta.say` (backend/tracker/notifications/say.py),
## frozen with their parameters in backend/tests/fixtures/notification_keys.json. A rewording keeps
## the key. `notificationText.ts` says them. Moved from the Python as it was found: the samples contract
## (`notificationText.test.ts`) proves each renders the server's stored English byte for byte. A sentence
## Python composed from pieces cannot be proven against the as-found snapshot, so it carries no
## wording=as-is and passes the full rules instead.

# kind=notification wording=as-is
notif-companies = { $count ->
    [one] { $count } company
   *[other] { $count } companies
}
# kind=notification wording=as-is
notif-duration-unknown = unknown duration
# kind=notification wording=as-is
notif-duration-seconds = { $s }s
# kind=notification wording=as-is
notif-duration-minutes = { $m }m { $s }s
# kind=notification wording=as-is
notif-duration-hours = { $h }h { $m }m
# kind=notification
notif-sources-all = every company you follow
# kind=notification
notif-sources-more = { $names } and { $more } more
# kind=notification wording=as-is
notif-affected-none = no single company; see the scan's notes
# kind=notification wording=as-is
notif-closed = { $company } closed a role you saved
# kind=notification
notif-reposted = { $company } reposted a role you saved
# kind=notification
notif-listed-again = { $company } listed again a role you saved
# kind=notification wording=as-is
notif-listed = { $company } listed a role you saved
# kind=notification
notif-saved-elsewhere = { $places ->
    [one] { $company } still lists a role you saved in another place
   *[other] { $company } still lists a role you saved in { $places } other places
}
# kind=notification wording=as-is
notif-saved-elsewhere-body = { $more ->
    [yes] { $title }. The posting you saved closed; the role is still listed in { $places } and more.
   *[no] { $title }. The posting you saved closed; the role is still listed in { $places }.
}
# kind=notification
notif-pay-raised = { $company } raised the posted range on a role you saved
# kind=notification
notif-pay-lowered = { $company } lowered the posted range on a role you saved
# kind=notification wording=as-is
notif-pay-change = { $title }: { $before } -> { $after }
# kind=notification wording=as-is
notif-updated-long-open = { $company } updated a role you saved, listed for a long time
# kind=notification wording=as-is
notif-changed = { $company } changed a role you saved
# kind=notification
notif-digest = { $count ->
    [one] { $count } new role for you today
   *[other] { $count } new roles for you today
}
# kind=notification wording=as-is
notif-digest-lead = { $title } at { $company }
# kind=notification wording=as-is
notif-digest-fit = { $band } fit: { $lead }
# kind=notification wording=as-is
notif-digest-more = { $lead } - and { $more } more
# kind=notification wording=as-is
notif-follow-up = Follow up with { $company } · { $when }
# kind=notification wording=as-is
notif-due-today = due today
# kind=notification wording=as-is
notif-overdue = { $days }d overdue
# kind=notification wording=as-is
notif-follow-up-body = { $action } - { $title } ({ $stage })
# kind=notification wording=as-is
notif-no-next-action = No next action set
# kind=notification
notif-gone-quiet = No news from { $company } in { $days } days
# kind=notification
notif-gone-quiet-body = { $title } ({ $stage }): time to follow up, or set a date
# kind=notification wording=as-is
notif-coverage-unreachable = Its careers page isn't answering.
# kind=notification
notif-coverage-unreadable = Its careers page answered with nothing readable.
# kind=notification wording=as-is
notif-coverage-partial = Scans read only part of its careers page.
# kind=notification wording=as-is
notif-coverage-unknown = No scan has reached its careers page.
# kind=notification
notif-coverage-waiting-title = Waiting to scan { $company }
# kind=notification
notif-coverage-waiting-outage = Waiting to scan { $count } companies
# kind=notification wording=as-is
notif-coverage-empty-listing = Its careers page answered with an empty list.
# kind=notification
notif-coverage-board-missing = Its careers page is no longer at its last address.
# kind=notification wording=as-is
notif-coverage-scan-title = { $days ->
    [0] Couldn't scan { $company }
    [one] Couldn't scan { $company } · { $days } day
   *[other] Couldn't scan { $company } · { $days } days
}
# kind=notification
notif-coverage-not-scanned-since = It hasn't had a full scan since { $day }, so new roles from { $company } may be missing. This clears on its next full scan.
# kind=notification
notif-coverage-not-scanned = It hasn't had a full scan yet, so new roles from { $company } may be missing. This clears on its next full scan.
# kind=notification wording=as-is
notif-coverage-empty-title = { $days ->
    [0] { $company } lists no roles
    [one] { $company } lists no roles · { $days } day
   *[other] { $company } lists no roles · { $days } days
}
# kind=notification wording=as-is
notif-coverage-empty-moved = If { $company } is still hiring, its roles may have moved to a new careers page.
# kind=notification
notif-coverage-held-until-listed = { $held ->
    [one] { $held } role stays as last seen until it lists roles again.
   *[other] { $held } roles stay as last seen until it lists roles again.
}
# kind=notification wording=as-is
notif-coverage-gone-title = { $days ->
    [0] { $company }'s careers page is gone
    [one] { $company }'s careers page is gone · { $days } day
   *[other] { $company }'s careers page is gone · { $days } days
}
# kind=notification wording=as-is
notif-coverage-gone-moved = { $company } has likely moved its roles to a new careers page. Find its new careers page, or stop following { $company }.
# kind=notification
notif-coverage-held-until-then = { $held ->
    [one] { $held } role stays as last seen until then.
   *[other] { $held } roles stay as last seen until then.
}
# kind=notification wording=as-is
notif-coverage-outage = { $days ->
    [0] Couldn't scan { $count } companies
    [one] Couldn't scan { $count } companies · { $days } day
   *[other] Couldn't scan { $count } companies · { $days } days
}
# kind=notification
notif-coverage-outage-since = None of them has had a full scan since { $day }, so new roles may be missing. This clears as scans get through.
# kind=notification wording=as-is
notif-coverage-outage-body = None of them has had a full scan, so new roles may be missing. This clears as scans get through.
# kind=notification wording=as-is
notif-scan-started = Scan started
# kind=notification
notif-scan-started-body = Scanning { $count ->
    [one] { $count } company
   *[other] { $count } companies
}: { $sources }.
# kind=notification
notif-scan-started-all-body = Scanning { $sources }.
# kind=notification wording=as-is
notif-scan-summary = { $found } found / { $created } created / { $updated } updated
# kind=notification wording=as-is
notif-scan-summary-skipped = { $found } found / { $created } created / { $updated } updated / { $skipped } skipped or unchanged
# kind=notification wording=as-is
notif-finished-at = Finished at { $at } after { $duration }.
# kind=notification wording=as-is
notif-failed-at = Failed at { $at } after { $duration }.
# kind=notification wording=as-is
notif-scan-stopped = Scan stopped
# kind=notification
notif-stopped-before-any = You stopped it before it scanned any company.
# kind=notification
notif-stopped-after = You stopped it after it scanned { $companies }.
# kind=notification wording=as-is
notif-problems-at = Problems at: { $affected }.
# kind=notification
notif-read-saved = What it found is saved.
# kind=notification wording=as-is
notif-scan-failed = Couldn't scan, nothing was updated
# kind=notification
notif-run-failed = scan failed
# kind=notification wording=as-is
notif-scan-derivation-failed = Scan collected, but a derivation failed
# kind=notification
notif-post-pass-unfinished = A step after the scan did not finish: { $failure }.
# kind=notification
notif-every-source-delivered = Every company in this scan was read, but a step after the scan did not finish: { $failure }.
# kind=notification
notif-data-saved = What the scan found is saved.
# kind=notification wording=as-is
notif-scan-problems = Scan finished with problems
# kind=notification wording=as-is
notif-asleep = This machine was asleep for { $duration } during the scan, which cuts a company's listing short.
# kind=notification wording=as-is
notif-unreached = { $count ->
    [one] Not reached before the scan ran out of time: { $sources }. It is still due, so the next scan picks it up.
   *[other] Not reached before the scan ran out of time: { $sources }. They are still due, so the next scan picks them up.
}
# kind=notification
notif-offline = { $count ->
    [one] This machine had no internet connection while scanning: { $sources }. What was found is saved, and it is still due, so the next scan picks it up.
   *[other] This machine had no internet connection while scanning: { $sources }. What was found is saved, and they are still due, so the next scan picks them up.
}
# kind=notification
notif-cut-short = Stopped at the scan's time limit: { $sources }. What was found is saved, and postings there stay as last seen.
# kind=notification
notif-unfinished-u = Scan ran out of time before { $unreached }
# kind=notification
notif-unfinished-o = Scan lost its internet connection at { $offline }
# kind=notification
notif-unfinished-c = Scan covered { $cut } only in part
# kind=notification
notif-unfinished-uo = Scan ran out of time before { $unreached } and lost its internet connection at { $offline }
# kind=notification
notif-unfinished-uc = Scan ran out of time before { $unreached } and covered { $cut } only in part
# kind=notification
notif-unfinished-oc = Scan lost its internet connection at { $offline } and covered { $cut } only in part
# kind=notification
notif-unfinished-uoc = Scan ran out of time before { $unreached }, lost its internet connection at { $offline } and covered { $cut } only in part

## A notification's priority code on its badge.
# kind=label wording=as-is
notifications-priority-high = high
# kind=label wording=as-is
notifications-priority-normal = normal
# kind=label wording=as-is
notifications-priority-low = low
