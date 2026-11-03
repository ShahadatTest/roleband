## companies: moved as it was found (wording=as-is)

## features/companies/AddMoreCompanies.tsx
# kind=heading wording=as-is
companies-add-more-companies-add-more-companies = Add more companies
# kind=button wording=as-is
companies-add-more-companies-add-by-link = Add by link
# kind=button wording=as-is
companies-add-more-companies-stop-scanning = Stop scanning
# kind=button wording=as-is
companies-add-more-companies-find-the-ones-hiring-for = Find the ones hiring for you
# kind=heading wording=as-is
companies-add-more-companies-add-a-company-by-link = Add a company by link
# kind=label wording=as-is
companies-add-more-companies-company-name = Company name
# kind=label wording=as-is
companies-add-more-companies-careers-page-link = Careers page link
# kind=button wording=as-is
companies-add-more-companies-cancel = Cancel
# kind=heading wording=as-is
companies-add-more-companies-a-specific-company = A specific company
# kind=label wording=as-is
companies-add-more-companies-added-by-its-careers-page = Added by its careers page
# kind=sentence wording=as-is
companies-add-more-companies-not-on-this-list-paste = Not on this list? Paste the link and you'll see whether it can be scanned.
# kind=label wording=as-is
companies-add-more-companies-the-wider-market = The wider market
# kind=aria wording=as-is
companies-add-more-companies-stop-scanning-the-wider-market = Stop scanning the wider market
# kind=heading wording=as-is
companies-add-more-companies-the-wider-market-heading = The wider market
# kind=label wording=as-is
companies-add-more-companies-about-companies-on-the-same = About { $about } companies on the same job sites
# kind=sentence
companies-add-more-companies-each-one-is-checked-daily = Each one is scanned daily, and only the ones hiring for roles on your radar join your list.
# kind=label wording=as-is note="$scan is paused while the computer runs on battery"
companies-add-more-companies-first-scan-state = { $scan ->
    [paused] About { $about } companies, first scan paused on battery
   *[running] About { $about } companies, first scan running
}
# kind=sentence wording=as-is
companies-add-more-companies-first-scan-note = { $scan ->
    [paused] It picks up where it stopped when you plug in. Matches so far are under Other companies.
   *[running] Matches appear under Other companies as they turn up. The scan continues if you leave this page.
}
# kind=label wording=as-is
companies-add-more-companies-scanned-of-about = scanned of about { $to_check }
# kind=label wording=as-is
companies-add-more-companies-hiring-for-you-so-far = hiring for you so far
# kind=label wording=as-is
companies-add-more-companies-companies-scanned = Companies scanned
# kind=status
companies-add-more-companies-about-companies-checked-daily = About { $about } companies, scanned daily
# kind=sentence
companies-add-more-companies-daily-check-note = { $scan ->
    [paused] Paused on battery. Daily scans resume when you plug in.
   *[running] Quiet ones are scanned again tomorrow.
}
# kind=label wording=as-is
companies-add-more-companies-hiring-for-you = hiring for you
# kind=label wording=as-is
companies-add-more-companies-quiet-today = quiet today
# kind=error wording=as-is
companies-add-more-companies-couldn-t-add-that-company = Couldn't add that company. { $caught }
# kind=error wording=as-is
companies-add-more-companies-try-again = Try again.
# kind=label wording=as-is
companies-add-more-companies-add-by-link-dialog = Add a company by link
# kind=label wording=as-is
companies-add-more-companies-acme = Acme
# kind=aria wording=as-is
companies-add-more-companies-careers-page-link-aria = Careers page link
# kind=label wording=as-is
companies-add-more-companies-add-company = { $state ->
    [adding] Adding…
   *[idle] Add company
}

## features/companies/CompaniesData.tsx
# kind=label wording=as-is
companies-data-undo = Undo
# kind=error wording=as-is
companies-data-couldn-t-undo-that-change = Couldn't undo that change.
# kind=sentence wording=as-is
companies-data-change-undone = Change undone.
# kind=error wording=as-is note="$name is a company or a sector"
companies-data-follow-failed = { $direction ->
    [follow] Couldn't follow { $name }.
   *[unfollow] Couldn't unfollow { $name }.
}
# kind=sentence
companies-data-unfollowed = Stopped following { $display }.
# kind=sentence note="$coverage is covered when RoleBand can already read the company's careers page"
companies-data-followed = { $coverage ->
    [covered] Following { $company }.
   *[uncovered] Following { $company }. Scanning starts as soon as its careers page can be read.
}
# kind=toast note="Following or unfollowing every company shown in a sector; $paused counts the ones RoleBand cannot scan yet"
companies-data-sector-follow-result = { $direction ->
    [follow] Following every company shown in { $sector }.{ $paused ->
        [0] { "" }
        [one] { " " }{ $paused } isn't scanned yet.
       *[other] { " " }{ $paused } aren't scanned yet.
    }
   *[unfollow] Stopped following { $sector }.
}
# kind=sentence note="Scanning the wider market: waiting for power, scanning, or stopped; $added counts the companies the scan had added"
companies-data-wider-market-result = { $state ->
    [waiting] On battery: the scan of about { $size } more companies starts when you plug in.
    [scanning] Scanning about { $size } more companies, best-known first.
   *[stopped] Stopped scanning.{ $added ->
        [0] { "" }
        [one] { " " }The { $added } company it added is no longer followed.
       *[other] { " " }The { $added } companies it added are no longer followed.
    }
}
# kind=error wording=as-is
companies-data-wider-market-failed = { $direction ->
    [start] Couldn't start scanning the wider market.
   *[stop] Couldn't stop scanning the wider market.
}
# kind=error wording=as-is
companies-data-curated-follow-failed = { $direction ->
    [follow] Couldn't follow the { $count ->
        [one] company
       *[other] companies
    }.
   *[unfollow] Couldn't unfollow the { $count ->
        [one] company
       *[other] companies
    } outside your { $curatedList }.
}
# kind=sentence
companies-data-curated-follow-result = { $direction ->
    [follow] Following { $count } more { $count ->
        [one] company
       *[other] companies
    }.
   *[unfollow] Stopped following { $count } { $count ->
        [one] company
       *[other] companies
    } outside your { $curatedList }.
}
# kind=error wording=as-is note="$visibility is the state the write asked for"
companies-data-visibility-failed = { $visibility ->
    [shown] Couldn't put { $company } back on your radar.
   *[hidden] Couldn't hide { $company } from your radar.
}
# kind=sentence wording=as-is note="$visibility is the state the company now has"
companies-data-visibility-changed = { $visibility ->
    [hidden] { $company } hidden from your radar.
   *[shown] { $company } back on your radar.
}
# kind=sentence wording=as-is
companies-data-company-added-to-your-roster = Company added to your roster.

## features/companies/CompaniesIndex.tsx
# kind=label wording=as-is
companies-index-sectors = Sectors
# kind=label wording=as-is
companies-index-add-more-companies = Add more companies
# kind=aria wording=as-is
companies-index-sectors-aria = Sectors

## features/companies/CompaniesSection.tsx
# kind=label wording=as-is
companies-section-loading-companies = Loading companies…
# kind=label wording=as-is
companies-section-company = Company
# kind=label wording=as-is
companies-section-coverage = Coverage
# kind=label wording=as-is
companies-section-open = Open
# kind=aria wording=as-is
companies-section-companies = Companies
# kind=heading
companies-section-load-failed = Couldn't load companies
# kind=sentence
companies-section-refresh-failed = Couldn't update companies. Showing the last result.

## features/companies/CompanyRegisterRows.tsx
# kind=label wording=as-is note="$mark is a dot shown when the count leaves roles out, explained on hover"
companies-company-register-rows-open-count = { $count } open{ $mark }
# kind=label wording=as-is
companies-company-register-rows-aka = aka { $aliasHit }
# kind=label wording=as-is
companies-company-register-rows-limits-collection = limits collection
# kind=label wording=as-is
companies-company-register-rows-also = also { $name }
# kind=sentence wording=as-is
companies-company-register-rows-showing-of-matches-keep-typing = Showing { $shown } of { $matchCount } matches. Keep typing to narrow the list.
# kind=label wording=as-is
companies-company-register-rows-planned = Planned
# kind=label
companies-company-register-rows-waiting-to-scan = Waiting to scan
# kind=label wording=as-is note="Why a followed company's coverage needs attention, from the coverage cause"
companies-company-register-rows-coverage-problem = { $cause ->
    [empty_listing] Lists no roles
    [board_missing] Careers page gone
   *[other] Couldn't scan
}
# kind=label wording=as-is
companies-company-register-rows-blocked = Blocked
# kind=label wording=as-is
companies-company-register-rows-needs-consent = Needs consent
# kind=label wording=as-is note="$connector is the company's connector state; every state here but ready is live"
companies-company-register-rows-live-or-ready = { $connector ->
    [ready] Ready
   *[other] Live
}
# kind=sentence wording=as-is
companies-company-register-rows-scanned-ago = Scanned { $scanned } ago.
# kind=label wording=as-is
companies-company-register-rows-label-scanned-ago = { $label } · scanned { $scanned } ago
# kind=sentence
companies-company-register-rows-scanned-ago-roleband-scans-when = Scanned { $scanned } ago. { $display } is scanned when you choose Scan now.
# kind=status
companies-company-register-rows-not-counted-last-read-ago = { $label } · not counted, last scanned { $lastRead } ago
# kind=sentence
companies-company-register-rows-roleband-last-read-s-roles = { $display } was last scanned { $lastRead } ago, too long ago for your radar's count. Its next scan adds its roles back.
# kind=label wording=as-is
companies-company-register-rows-partly-counted = { $label } · partly counted
# kind=sentence
companies-company-register-rows-s-scans-have-not-read = { $display }'s scans have not read its whole careers page yet, so some roles aren't counted. Its next full scan adds them.
# kind=label wording=as-is
companies-company-register-rows-not-counted-yet = { $label } · not counted yet
# kind=sentence note="$reason is why the company's roles are not in the radar's count"
companies-company-register-rows-not-counted-why = { $reason ->
    [stale] { $company }'s roles were found by an older scan your radar's count can't use. Its next full scan adds them.
   *[other] { $company }'s roles aren't in your radar's count yet. Its next scan adds them.
}
# kind=label wording=as-is
companies-company-register-rows-following-not-scanned-yet = Following · not scanned yet
# kind=sentence
companies-company-register-rows-roleband-starts-scanning-as-soon = Scanning { $display } starts as soon as its careers page can be read.
# kind=tooltip wording=as-is
companies-company-register-rows-open-role-counts-are-unavailable = Open role counts are unavailable
# kind=label wording=as-is
companies-company-register-rows-open-roles-loading = Open roles loading
# kind=sentence
companies-company-register-rows-of-s-roles-name-a = { $unplaced } of { $display }'s roles name a place that isn't recognized, so they don't show for any place you choose.
# kind=sentence
companies-company-register-rows-of-s-roles-fit-no = { $unsorted } of { $display }'s roles fit no known discipline, so they don't show for any discipline you choose.
# kind=label wording=as-is
companies-company-register-rows-open-careers-page = Open { $display } careers page
# kind=tooltip wording=as-is
companies-company-register-rows-careers-page = Careers page
# kind=label wording=as-is note="The eye button: $visibility is the company's state now"
companies-company-register-rows-show-or-hide-on-radar = { $visibility ->
    [shown] Hide { $company } on your radar
   *[hidden] Show { $company } on your radar
}
# kind=label wording=as-is
companies-company-register-rows-radar-visibility = { $visibility ->
    [shown] On your radar
   *[hidden] Hidden from your radar
}
# kind=label wording=as-is
companies-company-register-rows-scan-now = Scan { $display } now
# kind=tooltip note="While a scan runs, the company joins it and is read next"
companies-company-register-rows-scan-now-hint = { $scan ->
    [running] Add to the running scan
    [waiting] A scan is already queued
   *[idle] Scan this company now
}
# kind=toast
companies-company-register-rows-scan-joined = { $display } is next in the running scan.
# kind=label wording=as-is
companies-company-register-rows-scanning = Scanning { $display }…
# kind=error wording=as-is
companies-company-register-rows-couldn-t-start-a-scan = Couldn't start a scan for { $display }.
# kind=label wording=as-is
companies-company-register-rows-followed = { $followed }/{ $total } followed
# kind=toast wording=as-is
companies-company-register-rows-covered-count = { $coverage ->
    [none] none covered
   *[some] { $covered } covered
}
# kind=toast wording=as-is
companies-company-register-rows-planned-hidden = { $hiddenPlanned } planned hidden
# kind=label wording=as-is
companies-company-register-rows-sector-follow-all = { $direction ->
    [unfollow] Unfollow all { $sector } companies
   *[follow] Follow all { $sector } companies
}
# kind=status note="Why a sector has nothing to follow: $coverage is none when RoleBand can scan none of its companies"
companies-company-register-rows-nothing-to-follow-why = { $coverage ->
    [none] No company in this sector can be scanned yet
   *[some] No company here matches your filters
}
# kind=label wording=as-is
companies-company-register-rows-sector-action = { $action ->
    [none] Nothing to follow
    [unfollow] Unfollow all
   *[follow] Follow all
}

## features/companies/CuratedList.tsx
# kind=label wording=as-is
companies-curated-list-confirm = Confirm

## features/companies/RegisterChrome.tsx
# kind=label wording=as-is
companies-register-chrome-followed-companies-wait-for-your = { $count ->
    [one] { $count } followed company waits for your consent
   *[other] { $count } followed companies wait for your consent
}
# kind=sentence
companies-register-chrome-roleband-doesn-t-scan-them = { $count ->
    [one] It isn't scanned until you answer.
   *[other] They aren't scanned until you answer.
}
# kind=button wording=as-is
companies-register-chrome-review = Review { $display }
# kind=label wording=as-is
companies-register-chrome-companies-failed-the-last-scan = { $count ->
    [one] { $count } company failed the last scan
   *[other] { $count } companies failed the last scan
}
# kind=button wording=as-is
companies-register-chrome-rescan = Rescan { $count }
# kind=label wording=as-is note="The toolbar's counts: $followed, $openRoles, $live and $ready are the figures, $sep the dot between them"
companies-register-chrome-toolbar-stats = { $followed } of { $total } followed { $sep } { $openRoles } open roles { $sep } { $live } live { $sep } { $ready } ready
# kind=label wording=as-is
companies-register-chrome-following-only = Following only
# kind=label wording=as-is
companies-register-chrome-show-planned = Show planned
# kind=button wording=as-is
companies-register-chrome-follow-all = Follow all
# kind=button wording=as-is
companies-register-chrome-curated-list-only = Curated list only
# kind=sentence wording=as-is note="$showAll is the Show all companies button; $search is query when a search also holds rows back"
companies-register-chrome-show-all-to-see = { $showAll } to see the { $released } { $search ->
        [query] { $released ->
            [one] match
           *[other] matches
        } you don't follow
       *[none] companies
    }.
# kind=button wording=as-is
companies-register-chrome-show-all-companies = Show all companies
# kind=sentence wording=as-is note="$showPlanned is the Show planned button"
companies-register-chrome-show-planned-to-see = { $showPlanned } to see { $released } more.
# kind=button wording=as-is
companies-register-chrome-show-planned-button = Show planned
# kind=sentence wording=as-is note="$clearSearch is the Clear the search button"
companies-register-chrome-clear-search-to-see = { $clearSearch } to see all { $catalogTotal }.
# kind=button wording=as-is
companies-register-chrome-clear-the-search = Clear the search
# kind=label wording=as-is
companies-register-chrome-more = { $names } +{ $more } more
# kind=label wording=as-is
companies-register-chrome-followed-companies-are-blocked = { $count ->
    [one] { $count } followed company is blocked
   *[other] { $count } followed companies are blocked
}
# kind=label wording=as-is
companies-register-chrome-followed-companies-are-not-scanned = { $count ->
    [one] { $count } followed company is not scanned yet
   *[other] { $count } followed companies are not scanned yet
}
# kind=label wording=as-is
companies-register-chrome-followed-companies-are-hidden-from = { $count ->
    [one] { $count } followed company is hidden from your radar
   *[other] { $count } followed companies are hidden from your radar
}
# kind=aria wording=as-is
companies-register-chrome-companies-needing-attention = Companies needing attention
# kind=label wording=as-is
companies-register-chrome-a-scan-is-already-running = A scan is already running
# kind=label wording=as-is
companies-register-chrome-rescanning-companies = { $count ->
    [one] Rescanning { $count } company…
   *[other] Rescanning { $count } companies…
}
# kind=error wording=as-is
companies-register-chrome-couldn-t-start-that-rescan = Couldn't start that rescan.
# kind=label wording=as-is
companies-register-chrome-search-companies = Search companies
# kind=label wording=as-is
companies-register-chrome-find-a-company-alias-or = Find a company, alias or sector
# kind=label wording=as-is
companies-register-chrome-a-search-shows-planned-companies = A search shows planned companies too
# kind=sentence wording=as-is note="The empty register's title, by the filters holding rows back: a search, Following only, hidden planned companies, or none"
companies-register-chrome-register-empty = { $blamed ->
    [search-following] No company you follow matches “{ $search }”.
    [search] No company matches “{ $search }”.
    [following-planned] You aren't following any covered company yet.
    [following] You aren't following any company yet.
    [planned] Every company here is planned, not covered yet.
   *[none] No companies yet.
}

## features/companies/companiesModel.ts
# kind=tooltip
companies-model-ready-to-enable = Ready: follow it to start scanning
# kind=label wording=as-is
companies-model-your-additions = Your additions
# kind=label wording=as-is
companies-model-other-companies = Other companies

## features/companies/followCopy.ts
# kind=label wording=as-is
companies-follow-copy-thousands-of-roles = thousands of roles
# kind=label wording=as-is
companies-follow-copy-hundreds-of-roles = hundreds of roles
# kind=label wording=as-is
companies-follow-copy-more-roles = more roles
# kind=sentence
companies-follow-copy-following-all-will-likely-bring = More companies bring more roles, and each scan takes longer.
# kind=heading
companies-follow-copy-follow-more = Follow the whole list?
# kind=sentence
companies-follow-copy-roleband-starts-you-with-a = Your radar starts with a { $curatedList } of well-known companies, so your first roles come from employers you know.
# kind=consent note="Shown in the Follow the whole list dialog only when some of the companies limit automated collection. The whole dialog's text is the consent the server stores for them."
companies-follow-copy-some-of-these-companies-limit = Some of these companies limit automated collection on their careers sites. By following them, you choose to collect their public postings.
# kind=sentence
companies-follow-copy-you-can-unfollow-any-company = You can unfollow any company in Settings › Followed companies.
# kind=label wording=as-is
companies-follow-copy-keep = Keep { $curatedList }
# kind=label wording=as-is
companies-follow-copy-follow-all = Follow all { $count }
# kind=tooltip wording=as-is
companies-follow-copy-unfollow-outside-your = Unfollow { $count } { $count ->
        [one] company
       *[other] companies
    } outside your { $curatedList }?
# kind=sentence
companies-follow-copy-roleband-stops-scanning-them-your = { $count ->
    [one] Scanning it stops. Your { $curatedList }, and any company you added yourself, stays followed.
   *[other] Scanning them stops. Your { $curatedList }, and any company you added yourself, stays followed.
}
# kind=label wording=as-is
companies-follow-copy-keep-following = Keep following
# kind=label wording=as-is
companies-follow-copy-unfollow = Unfollow { $count }
# kind=tooltip wording=as-is
companies-follow-copy-follow-all-in = Follow all { $count } { $count ->
        [one] company
       *[other] companies
    } in { $sector }?
# kind=sentence wording=as-is
companies-follow-copy-this-will-likely-add-to = This will likely add { $estimate } to your radar and make each scan longer. You can unfollow any company later.
# kind=label wording=as-is
companies-follow-copy-cancel = Cancel
# kind=tooltip wording=as-is
companies-follow-copy-follow = Follow { $display }?
# kind=sentence wording=as-is
companies-follow-copy-by-following-you-choose-to = By following, you choose to collect { $display }'s public job listings. You can unfollow at any time, and collection stops.
# kind=label wording=as-is
companies-follow-copy-follow-company = Follow { $display }
# kind=tooltip wording=as-is
companies-follow-copy-scan-about-more-companies = Scan about { $about } more companies?
# kind=sentence wording=as-is
companies-follow-copy-only-companies-hiring-for-roles = Only companies hiring for roles on your radar join your followed list. The rest stay out of sight.
# kind=sentence
companies-follow-copy-roleband-scans-the-best-known = The first scan takes a few hours, best-known companies first. Then each is scanned daily, so a role that fits shows up the day it's posted.
# kind=sentence wording=as-is
companies-follow-copy-you-can-stop-at-any = You can stop at any time.
# kind=label wording=as-is
companies-follow-copy-start-scanning = Start scanning
# kind=tooltip
companies-follow-copy-follow-every-company-question = Follow the other companies too?
# kind=sentence
companies-follow-copy-your-radar-covers-the-whole = Your radar adds the other companies to the ones on the list.
# kind=consent note="Shown only when some of the companies limit automated collection. The whole dialog's text is the consent the server stores for them."
companies-follow-copy-some-of-these-companies-careers = Some of these companies' careers sites limit automated collection. By picking this, you choose to collect their public postings.
# kind=sentence
companies-follow-copy-with-more-companies-scans-take = With more companies, scans take longer.
# kind=sentence
companies-follow-copy-change-it-any-time-in = Change it any time in Settings.
# kind=label
companies-follow-copy-follow-every-company = Follow them
# kind=tooltip wording=as-is
companies-follow-copy-unfollow-company-question = Unfollow { $display }?
# kind=sentence wording=as-is
companies-follow-copy-s-job-listings-stop-being = { $display }'s job listings stop being collected. You can follow it again at any time.
# kind=label wording=as-is same-as=companies-follow-copy-unfollow
companies-follow-copy-unfollow-company = Unfollow { $display }

## features/companies/CompaniesIndex.tsx
# kind=label wording=as-is note="A sector's count in the index while searching: its rows that match"
companies-index-match-count = { $count } match
# kind=label wording=as-is note="A sector's count in the index: followed of all"
companies-index-followed-of = { $followed }/{ $total }

## features/companies/CompanyRegisterRows.tsx
# kind=toast wording=as-is
companies-company-register-rows-sector-open = { $openRoles } open

## A company's connector, said from its state and, when parked, why (states from
## backend/tracker/company_discovery.py). `ready`
## is companies-model-ready-to-enable.
# kind=tooltip
companies-connector-live = Scanned automatically
# kind=tooltip
companies-connector-family = Ready: its careers page can be read
# kind=tooltip
companies-connector-active = Added by you and scanned
# kind=tooltip
companies-connector-planned = Support planned
# kind=tooltip
companies-connector-parked = Its site refuses scans
# kind=tooltip
companies-parked-bot-protected = Its careers page blocks automated reading
# kind=tooltip
companies-parked-robots-disallow = { $company } asks not to have its careers page read automatically
# kind=tooltip
companies-parked-prohibits-collection = Its careers page forbids automated collection
# kind=status note="A pending company whose careers page named a known board family: the family, and why it waits"
companies-company-register-rows-board-found = { $reason ->
    [policy_refused] Uses { $family }; collecting from it is off
   *[board_silent] Uses { $family }, which didn't answer
}
# kind=status note="A board family's own name, a brand: not translated, not sentence-cased"
companies-company-register-rows-board-family = { $family ->
    [jibe] Jibe
    [radancy] Radancy TalentBrew
    [avature] Avature
   *[other] { $family }
}

## First-run setup: which companies the radar scans (features/companies/SetupCompanies.tsx)

# kind=label
companies-setup-followed-now = Followed now
# kind=status note="After a list of company names: and 27 more"
companies-setup-and-more = and { $count } more
# kind=label
companies-setup-well-known = Well-known companies
# kind=status
companies-setup-well-known-detail = { $count ->
    [one] { $count } { -company(num: "one") }, first roles in minutes
   *[other] { $count } { -company(num: "other") }, first roles in minutes
}
# kind=label
companies-setup-every-listed = Every listed company
# kind=status
companies-setup-every-listed-detail = { $count ->
    [one] { $count } { -company(num: "one") } across many sectors
   *[other] { $count } { -company(num: "other") } across many sectors
}
# kind=label note="The listed companies and the other companies beyond the list"
companies-setup-everything = Plus other companies
# kind=status note="$about is a rounded count: About 12,500 more"
companies-setup-everything-detail = About { $about } more; the first scan takes a few hours
# kind=aria
companies-setup-choice-aria = Which companies are scanned
# kind=sentence
companies-setup-later = Follow or unfollow single companies at any time in Settings > Followed companies.
# kind=status
companies-setup-load-failed = Couldn't load the company list. The well-known companies stay followed.
# kind=button
companies-setup-back = Back
# kind=button
companies-setup-start = { $choice ->
    [yes] Starting…
   *[no] Start the radar
}
