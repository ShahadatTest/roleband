## scan: moved as it was found (wording=as-is)

## features/sync/SyncScopePopover.tsx
# kind=sentence
scan-sync-scope-popover-roleband-can-t-scan-any = No company can be scanned yet. Follow one under Settings › Followed companies first.
# kind=status note="Beside the box that selects every company the filter shows: how many it shows, and of how many when the filter hides some"
scan-sync-scope-popover-all-shown = { $choice ->
    [yes] All shown ({ $shown } of { $total })
   *[no] All shown ({ $shown })
}
# kind=sentence wording=as-is
scan-sync-scope-popover-no-company-matches-that-filter = No company matches that filter.
# kind=button wording=as-is
scan-sync-scope-popover-stale = Stale ({ $length })
# kind=button
scan-sync-scope-popover-failed-last-run = Couldn't scan ({ $length })
# kind=sentence
scan-sync-scope-popover-a-targeted-sync-refreshes-only = Scanning a few companies updates only the ones you pick. Everything else keeps the time of its own last scan.
# kind=label wording=as-is
scan-sync-scope-popover-cut-short = cut short
# kind=label wording=as-is
scan-sync-scope-popover-not-reached = not reached
# kind=label wording=as-is
scan-sync-scope-popover-lists-no-roles = lists no roles
# kind=label note="A company's last scan failed"
scan-sync-scope-popover-failed = failed
# kind=label note="The careers site refused the last scan"
scan-sync-scope-popover-blocked = blocked
# kind=label note="The last scan read part of the board, with errors"
scan-sync-scope-popover-partial = partial
# kind=label note="The last scan read the board except a few postings it could not read"
scan-sync-scope-popover-a-few-rows-unread = a few rows unread
# kind=label note="The last scan stopped at a posting limit set for the run"
scan-sync-scope-popover-capped = capped
# kind=label note="The last scan stopped because this computer slept or went offline"
scan-sync-scope-popover-paused = paused
# kind=label wording=as-is
scan-sync-scope-popover-companies = { $count ->
    [one] company
   *[other] companies
}
# kind=label wording=as-is
scan-sync-scope-popover-scan = { $choice ->
    [yes] Scan all companies
   *[no] Scan { $count } { $value }
}
# kind=label wording=as-is
scan-sync-scope-popover-filter-companies-to-scan = Filter companies to scan
# kind=label wording=as-is
scan-sync-scope-popover-filter-companies = Filter companies…
# kind=aria wording=as-is
scan-sync-scope-popover-select-all-shown-companies = Select all shown companies
# kind=aria wording=as-is
scan-sync-scope-popover-companies-to-scan-2 = Companies to scan
# kind=label wording=as-is
scan-sync-scope-popover-select-companies = Select companies
# kind=label wording=as-is
scan-sync-scope-popover-choose-companies-to-scan = Choose companies to scan

## features/sync/SyncScopePopover.tsx
# kind=status
scan-sync-scope-popover-loading = Loading companies to scan…
# kind=heading
scan-sync-scope-popover-load-failed = Couldn't load companies to scan
# kind=sentence
scan-sync-scope-popover-joins-running = The running scan reads them next.
# kind=toast
scan-sync-scope-popover-joined = { $count ->
    [one] { $count } { -company(num: "one") } is next in the running scan.
   *[other] { $count } { -company(num: "other") } are next in the running scan.
}
