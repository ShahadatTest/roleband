### eager: the shell imports this file, so every message in it ships in the shell
### (docs/copy.md section 3). The compiler numbers its messages first.

## Navigation (src/navigation.ts NAV_TABS)
# kind=label
shell-nav-radar = Radar
# kind=label
shell-nav-saved = Saved
# kind=label
shell-nav-profile = Profile
# kind=label
shell-nav-insights = Insights
# kind=label
shell-nav-companies = Companies
# kind=label
shell-nav-duplicates = Duplicates
# kind=label
shell-nav-notifications = Notifications
# kind=label
shell-nav-settings = Settings

## Insights tabs (src/navTabs.ts STATISTICS_TABS)
# kind=label
shell-tab-insights-overview = Overview
# kind=label
shell-tab-insights-hiring = Hiring
# kind=label
shell-tab-insights-pace = Pace
# kind=label
shell-tab-insights-pay = Compensation
# kind=label
shell-tab-insights-levels = Levels
# kind=label
shell-tab-insights-stock = Stock
# kind=label
shell-tab-insights-skills = Skills
# kind=label
shell-tab-insights-trends = Trends
# kind=label
shell-tab-insights-overlap = Overlap
# kind=label
shell-tab-insights-groups = Groups

## Settings tabs (SETTINGS_TABS)
# kind=label
shell-tab-settings-companies = Followed companies
# kind=label
shell-tab-settings-ai = AI
# kind=label
shell-tab-settings-schedule = Schedule
# kind=label
shell-tab-settings-recipes = Recipes
# kind=label
shell-tab-settings-retention = Data retention
# kind=label
shell-tab-settings-plugins = Plugins

## Profile tabs (PROFILE_TABS)
# kind=label
shell-tab-profile-looking-for = Looking for
# kind=label
shell-tab-profile-experience = Your experience
# kind=label
shell-tab-settings-language = Language
# kind=label
shell-tab-settings-privacy = Privacy

## The top bar (App.tsx)
# kind=label note="The breadcrumb's first segment on a route outside the nav"
shell-route-welcome = Welcome
# kind=label
shell-route-compare = Compare
# kind=label
shell-route-dashboard = RoleBand
# kind=label
shell-skip-to-content = Skip to content
# kind=aria
shell-topbar-aria = Application navigation
# kind=aria
shell-breadcrumb-aria = Breadcrumb
# kind=aria
shell-palette-open-aria = Open command palette, ⌘ K
# kind=tooltip
shell-palette-open-title = Command palette (⌘K)
# kind=aria
shell-stats-aria = Mission telemetry
# kind=label note="A count no status has answered yet"
shell-stat-unknown = Unknown
# kind=label note="Beside the count of open roles"
shell-stat-open = open
# kind=aria note="$count is a number, or shell-stat-unknown"
shell-stat-open-aria = { $count ->
    [one] { $count } open role
   *[other] { $count } open roles
}
# kind=aria
shell-stat-open-aria-unknown = Open roles, not counted yet
# kind=tooltip
shell-stat-open-title = Show every open role
# kind=label note="Beside the count of roles posted in the last 2 days"
shell-stat-new = new
# kind=aria
shell-stat-new-aria = { $count } new in the last 2 days
# kind=tooltip
shell-stat-new-title = Show roles posted in the last 2 days
# kind=label note="Beside the count of roles reposted today"
shell-stat-reposted = reposted
# kind=aria
shell-stat-reposted-aria = { $count } reposted today
# kind=tooltip
shell-stat-reposted-title = Show today's reposted roles
# kind=label note="Beside the count of saved roles"
shell-stat-saved = saved
# kind=aria
shell-stat-saved-aria = { $count ->
    [one] { $count } saved role
   *[other] { $count } saved roles
}
# kind=aria
shell-stat-saved-aria-unknown = Saved roles, not counted yet
# kind=tooltip
shell-stat-saved-title = Saved roles
# kind=label
shell-loading-page = Loading this page…
# kind=heading
shell-load-page-failed = Couldn't load this page
# kind=label
shell-loading-role = Loading this role…
# kind=heading
shell-load-role-failed = Couldn't load this role

## The nav rail (shell/NavRail.tsx)
# kind=aria
shell-rail-aria = Primary
# kind=label same-as=shell-route-dashboard note="The product name; never translated"
shell-brand = RoleBand
# kind=label note="The brand line: opportunity lives here and nowhere else"
shell-brand-line = Opportunity radar
# kind=aria
shell-rail-collapse-aria = Collapse navigation
# kind=aria
shell-rail-expand-aria = Expand navigation
# kind=button
shell-rail-collapse = Collapse
# kind=button
shell-rail-expand = Expand
# kind=label
shell-rail-workspace = Workspace
# kind=aria
shell-theme-aria = Toggle theme
# kind=tooltip
shell-theme-title = Theme
# kind=button
shell-theme-light = Light mode
# kind=button
shell-theme-dark = Dark mode

## Freshness (shell/FreshnessBadge.tsx)
# kind=label
shell-freshness-label = Last scan
# kind=label
shell-freshness-offline = Last scan unknown
# kind=aria
shell-freshness-offline-aria = Last scan: status offline
# kind=tooltip
shell-freshness-offline-title = Status unavailable
# kind=tooltip note="$when is a formatted date and time"
shell-freshness-oldest = Oldest scan: { $when }
# kind=tooltip
shell-freshness-never = Not scanned yet
# kind=status note="$age is the time since the newest scan finished"
shell-freshness-checked = Last scan · { $age }
# kind=status note="$age is the time since the newest scan finished; $count is how many companies were not read in full lately"
shell-freshness-behind = Last scan · { $age } · { $count ->
    [one] { $count } company behind
   *[other] { $count } companies behind
}
# kind=tooltip note="$companies is a list of company names"
shell-freshness-waiting = Waiting for a full scan: { $companies }
# kind=aria note="$state is the badge's own words"
shell-freshness-aria = Last scan: { $state }
# kind=aria
shell-freshness-loading-aria = Last scan: loading

## The scan button (shell/SyncButton.tsx)
# kind=toast note="After a scan ends: how many new roles it found"
shell-scan-result-new = +{ $count } new
# kind=toast
shell-scan-result-none = Up to date
# kind=status note="$time is a formatted time of day"
shell-scan-queued-until = { $count } queued · waiting until { $time }
# kind=status note="$reason is the provider's state code"
shell-scan-queued-blocked = { $count } queued · { $reason ->
    [paused] paused
    [policy_denied] not scanned on a timer
    [backoff] waiting to retry
   *[other] waiting
}
# kind=status
shell-scan-queued = { $count } queued
# kind=status note="A queued scan the background service holds. $reason is its code: preflight_running (the code is being tested first), preflight_failed (the code failed its tests), waiting_for_wake (the computer is asleep), waiting_for_mains (on battery), schema_pending and dependencies_pending (an update is half installed), supervisor_stale (the background service is not running), busy_external (another scan holds the lock)"
shell-scan-waiting = { $count } queued · { $reason ->
    [preflight_running] checking the code first
    [preflight_failed] held: the code failed its checks
    [waiting_for_wake] waiting for the computer to wake
    [waiting_for_mains] waiting for power
    [schema_pending] waiting for an update to finish
    [dependencies_pending] waiting for an update to finish
    [supervisor_stale] the background service isn't running
    [busy_external] another scan is running
   *[other] waiting
}
# kind=button
shell-scan-stopping = Stopping…
# kind=button
shell-scan-stop = Stop scan
# kind=button
shell-scan-scanning = Scanning…
# kind=button
shell-scan-queued-label = Queued
# kind=button note="The scan has ended; the stored pay estimates are being recomputed"
shell-scan-updating-estimates = Updating estimates…
# kind=label note="Accessible name of the scan control while estimates are recomputed"
shell-scan-updating-estimates-aria = Updating estimates
# kind=button
shell-scan-now = Scan now
# kind=aria
shell-scan-stop-queued-aria = Stop queued scan
# kind=aria
shell-scan-in-progress-aria = Scan in progress
# kind=aria
shell-scan-queued-aria = Scan queued
# kind=toast
shell-scan-stopped = Stopped
# kind=toast
shell-scan-could-not-start = Couldn't start
# kind=toast
shell-scan-could-not-stop = Couldn't stop
# kind=tooltip
shell-scan-stop-title = Stop the scan
# kind=tooltip
shell-scan-running-title = Looking for new roles at every company you follow…
# kind=tooltip
shell-scan-requested-title = Requested; waiting for the scheduler to pick it up
# kind=tooltip
shell-scan-idle-title = Look for new roles at every company you follow
# kind=status note="How many companies the running scan covers"
shell-scan-company-count = { $count ->
    [one] { $count } company
   *[other] { $count } companies
}
# kind=status note="Roles found so far in the running scan"
shell-scan-found = { $count } found
# kind=aria
shell-scan-choose-aria = Choose companies to scan
# kind=tooltip
shell-scan-some-title = Scan some companies
# kind=tooltip
shell-scan-add-title = Add companies to this scan

## The command palette (shell/CommandPalette.tsx)
# kind=label
shell-palette-navigate = Navigate
# kind=label
shell-palette-actions = Actions
# kind=label note="A jump to one tab of a section: Insights: Pace"
shell-palette-subtab = { $section }: { $tab }
# kind=label
shell-palette-theme-light = Switch to light theme
# kind=label
shell-palette-theme-dark = Switch to dark theme
# kind=label
shell-palette-shortcuts = Keyboard shortcuts
# kind=label
shell-palette-compare = { $count ->
    [one] Compare { $count } role
   *[other] Compare { $count } roles
}
# kind=label
shell-palette-clear-compare = Clear compare selection ({ $count })
# kind=label note="$query is what the person typed"
shell-palette-search = Search roles for “{ $query }”
# kind=aria
shell-palette-aria = Command palette
# kind=tooltip note="The input's placeholder"
shell-palette-placeholder = Search roles or jump anywhere…
# kind=aria
shell-palette-query-aria = Command query
# kind=aria
shell-palette-list-aria = Commands
# kind=label
shell-palette-empty = No matching commands

## The notification bell and categories (features/notifications/NotificationBell.tsx, notifIcons.tsx)
# kind=label
shell-notif-digest = New roles for you
# kind=label
shell-notif-reminder = Reminder
# kind=label
shell-notif-saved-listed = Saved role listed
# kind=label
shell-notif-pay-up = Posted range went up
# kind=label
shell-notif-pay-down = Posted range went down
# kind=label
shell-notif-reposted = Saved role reposted
# kind=heading
shell-notif-long-open = Long-open saved role updated
# kind=label
shell-notif-changed = Saved role changed
# kind=label
shell-notif-closed = Saved role closed
# kind=label
shell-notif-scanning = Scanning
# kind=heading
shell-notif-scan-problems = Scan finished with problems
# kind=heading
shell-notif-scan-unfinished = Scan ran out of time
# kind=label
shell-notif-scan-failed = Scan failed
# kind=heading
shell-notif-coverage = Coverage problem at a company you follow
# kind=label
shell-notif-scan-stopped = Scan stopped
# kind=label note="A category this version does not know yet"
shell-notif-other = Notification
# kind=toast
shell-notif-mark-read-failed = Couldn't mark it read. Try again.
# kind=aria note="$badge is how many, as the badge says it"
shell-bell-aria-count = Notifications, { $badge }
# kind=label
shell-bell-unread = { $count } unread
# kind=label note="Said to assistive tech on an unread row in the bell's list"
shell-bell-row-unread = unread
# kind=empty
shell-bell-empty = No notifications yet.
# kind=error
shell-bell-load-failed = Couldn't load notifications. Try again.
# kind=button
shell-bell-view-all = View all

## Compare in the top bar (shell/CompareChip.tsx, CompareSaveAlert.tsx, patterns/compare/useClearCompare.ts)
# kind=label note="Beside the count of roles in compare"
shell-compare-chip = in compare
# kind=aria
shell-compare-chip-aria = { $count ->
    [one] { $count } role in compare
   *[other] { $count } roles in compare
}
# kind=tooltip
shell-compare-chip-title = Open the comparison
# kind=label note="Under the AI mark in the top bar while the ranking model's weights download ($phase downloading) or the roles move onto it ($phase converting)"
shell-model-switch = { $phase ->
    [downloading] getting model
   *[converting] switching model
}
# kind=aria
shell-model-switch-aria = { $phase ->
    [downloading] Downloading the ranking model. Open Settings, AI to follow it
   *[converting] Switching the ranking model. Open Settings, AI to follow it
}
# kind=tooltip
shell-model-switch-title = Follow it in Settings › AI. Ranking keeps working meanwhile.
# kind=toast
shell-compare-save-failed = Couldn't save what you're comparing. It may be gone after a reload.
# kind=toast
shell-compare-cleared = { $count ->
    [one] Cleared { $count } role from compare
   *[other] Cleared { $count } roles from compare
}
# kind=status note="A rail badge's count, spoken: Duplicates, 342 pending"
shell-rail-pending = { $count } pending
# kind=aria note="A rail item named with its badge: Notifications, 7 unread"
shell-rail-item-count = { $label }, { $badge }

## src/shell/CommandPalette.tsx (by hand)
# kind=label wording=as-is
shell-palette-hint-navigate = navigate
# kind=label wording=as-is
shell-palette-hint-select = select
# kind=label wording=as-is
shell-palette-hint-close = close
