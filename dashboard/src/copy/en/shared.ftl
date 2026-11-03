## Words shared by lazy screens, never by the shell: a file the shell imports
## ships every message in it (docs/copy.md section 3).

# kind=status note="A count of roles: 219 roles"
shared-count-role = { $count ->
    [one] { $count } { -role(num: "one") }
   *[other] { $count } { -role(num: "other") }
}
# kind=status note="A count of postings"
shared-count-posting = { $count ->
    [one] { $count } { -posting(num: "one") }
   *[other] { $count } { -posting(num: "other") }
}
# kind=status note="A count of companies"
shared-count-company = { $count ->
    [one] { $count } { -company(num: "one") }
   *[other] { $count } { -company(num: "other") }
}
# kind=label note="The companies a fresh install follows. Used inside sentences"
shared-curated-list = curated list
# kind=button note="The verb for sending a role away"
shared-not-for-me = Not for me
# kind=status note="A results count; $n is the styled number, $count selects the plural" same-as=shared-count-role
shared-results-role = { $count ->
    [one] { $n } { -role(num: "one") }
   *[other] { $n } { -role(num: "other") }
}
# kind=status note="A narrowed count: $n of $t; $total selects the plural"
shared-results-of-role = { $total ->
    [one] { $n } of { $t } { -role(num: "one") }
   *[other] { $n } of { $t } { -role(num: "other") }
}
# kind=status same-as=shared-count-company
shared-results-company = { $count ->
    [one] { $n } { -company(num: "one") }
   *[other] { $n } { -company(num: "other") }
}
# kind=status
shared-results-of-company = { $total ->
    [one] { $n } of { $t } { -company(num: "one") }
   *[other] { $n } of { $t } { -company(num: "other") }
}

## The filter opener (patterns/FilterSurface.tsx), on Radar and Notifications
# kind=button note="Opens the filter panel; also the panel's name"
shared-filters = Filters
# kind=button note="The opener while filters are on: Filters · 2"
shared-filters-count = Filters · { $count }

## A company chip and its hover card (patterns/companies/CompanyChip.tsx)
# kind=aria
shared-company-chip-aria = { $company }, view company profile
# kind=sentence note="A company the user does not follow; the radar shows followed companies only"
shared-company-not-followed = Not on your radar. Follow { $company } to see its roles.
# kind=status
shared-company-open-roles = { $count ->
    [one] { $count } open { -role(num: "one") }
   *[other] { $count } open { -role(num: "other") }
}
# kind=status
shared-company-no-open-roles = No open roles right now
# kind=link note="The hover card's foot; an arrow follows. Not 'Click', which a phone cannot do"
shared-company-view-profile = View profile

## patterns/Pager.tsx
# kind=button wording=as-is
shared-pager-prev = Prev
# kind=label wording=as-is
shared-pager-page-of = Page { $page } of { $pages }
# kind=button wording=as-is
shared-pager-next = Next

## ui/EChart.tsx
# kind=label wording=as-is
shared-echart-chart-unavailable = Chart unavailable. { $summary }

## ui/FilterRail.tsx
# kind=button wording=as-is
shared-filter-rail-clear = clear
# kind=button wording=as-is
shared-filter-rail-more = + { $hidden } more
# kind=button wording=as-is
shared-filter-rail-select-all = Select all
# kind=sentence wording=as-is
shared-filter-rail-no-options-match = No options match.
# kind=label wording=as-is
shared-filter-rail-search = Search { $title }
# kind=sentence wording=as-is
shared-filter-rail-search-2 = Search { $title }...
# kind=label wording=as-is
shared-filter-rail-show-all = Show all { $title }
# kind=label wording=as-is
shared-filter-rail-select-all-2 = Select all { $title }

## ui/FilterSelect.tsx
# kind=button wording=as-is
shared-filter-select-clear = Clear
# kind=label wording=as-is
shared-filter-select-filter-by = Filter by { $label }
# kind=label wording=as-is same-as=shared-filter-rail-search
shared-filter-select-search = Search { $label }
# kind=sentence wording=as-is same-as=shared-filter-rail-search-2
shared-filter-select-search-2 = Search { $label }...

## ui/InfoTip.tsx

## patterns/companies/CompanyChip.tsx
# kind=label wording=as-is
shared-company-chip-summary = { $display_name } summary

## ui/EChart.tsx

## ui/FilterSelect.tsx
# kind=label wording=as-is
shared-filter-select-filter = { $label } filter
# kind=label wording=as-is
shared-filter-select-options = { $label } options

## Fit bands by key (backend/tracker/search/fit.py FIT_BAND_EDGES): the AI screen's
## instrument and the notification digest say the same words.
# kind=label wording=as-is
shared-fit-band-strong = Strong
# kind=label wording=as-is
shared-fit-band-good = Good
# kind=label wording=as-is
shared-fit-band-some = Fair
# kind=label wording=as-is
shared-fit-band-weak = Weak

## Pay a posting shows when only its base is estimated
# kind=label note="A base-pay estimate where no total is known; range is a money range"
shared-pay-est-base = Est. base { $range }
# kind=tooltip
shared-pay-est-base-hint = Base salary only. Bonus and equity aren't known yet.
# kind=tooltip note="The full words behind a TC column or row label, for its hover and screen-reader name"
shared-tc-full = Total compensation
# kind=tooltip note="The full words behind an Est. TC column or row label, for its hover and screen-reader name"
shared-est-tc-full = Estimated total compensation
## The Base column of a role list: one figure, its source in the hover
# kind=tooltip note="The full words behind a Base column label, for its hover and screen-reader name"
shared-base-salary-full = Base salary
# kind=tooltip note="Where a row's base salary comes from: the range the posting states. low and high are money, unit is empty for yearly pay or a unit such as / hr"
shared-base-posted-hint = Posted range: { $low } to { $high }{ $unit }
# kind=tooltip note="Where a row's base salary comes from: the one figure the posting states. amount is money, unit is empty for yearly pay or a unit such as / hr"
shared-base-posted-point-hint = Posted base salary: { $amount }{ $unit }
# kind=tooltip note="Where a row's base salary comes from when the posting states none"
shared-base-estimate-hint = Our estimate for this level
# kind=aria note="Read out for a row's empty Base cell"
shared-base-unknown = Base salary not known
# kind=status note="A posting's pay while a plugin answers pay app-wide and has not read its company yet; plugin = the plugin's name"
shared-pay-not-covered = Not read by { $plugin } yet
# kind=tooltip note="Why a posting shows no pay while a plugin answers pay"
shared-pay-not-covered-hint = While { $plugin } supplies compensation, a company it hasn't read yet shows no estimate, not a built-in one.
# kind=link note="Opens Tiingo's page that shows a free price key after sign-up, in a new tab: on the profile's empty price chart and the Stock prices card"
shared-price-feed-get-key = Get a free key

## ui/AsyncBoundary.tsx: what it says when a caller names no whole message of its own
# kind=heading note="An empty state's title"
shared-empty = Nothing here yet
# kind=sentence note="Above the data a failed background refresh left on screen"
shared-refresh-failed = Couldn't update this. Showing the last result.
