## insights: moved as it was found (wording=as-is)

## features/statistics/ClustersView.tsx
# kind=sentence
insights-clusters-view-semantic-groups-built-from-role = Roles grouped by what their descriptions say, and named by the skills they share. One kind of role can split into several groups.
# kind=label wording=as-is
insights-clusters-view-market-terrain = Market terrain
# kind=heading wording=as-is
insights-clusters-view-group-landscape = Group landscape
# kind=sentence
insights-clusters-view-area-encodes-active-role-volume = The bigger the box, the more open roles. Select one to see its roles.
# kind=label wording=as-is
insights-clusters-view-groups = { $count } groups
# kind=label wording=as-is
insights-clusters-view-roles = { $family_display } · { $size } roles
# kind=label wording=as-is
insights-clusters-view-clear = Clear
# kind=label wording=as-is
insights-clusters-view-and-more-companies = and { $n } more companies
# kind=label wording=as-is
insights-clusters-view-role-groups = { $count ->
    [one] { $count } role group
   *[other] { $count } role groups
}
# kind=label wording=as-is
insights-clusters-view-largest-group = Largest: { $label } · { $size } roles
# kind=label wording=as-is
insights-clusters-view-groups-are-built-from-role = Groups are built from role descriptions after a scan
# kind=label wording=as-is
insights-clusters-view-about-role-groups = About role groups
# kind=label wording=as-is
insights-clusters-view-groups-tile = Groups
# kind=label wording=as-is
insights-clusters-view-from-role-descriptions = from role descriptions
# kind=label wording=as-is
insights-clusters-view-roles-grouped = Roles grouped
# kind=label wording=as-is
insights-clusters-view-largest = Largest
# kind=label wording=as-is
insights-clusters-view-roles-in-one-group = roles in one group
# kind=label wording=as-is
insights-clusters-view-with-a-grouped-role = with a grouped role
# kind=label wording=as-is
insights-clusters-view-how-to-read-the-cluster = How to read the cluster landscape
# kind=status
insights-clusters-view-loading = Loading role groups…
# kind=heading
insights-clusters-view-load-failed = Couldn't load role groups
# kind=status
insights-clusters-view-group-loading = Loading this group…
# kind=heading
insights-clusters-view-group-load-failed = Couldn't load this group

## features/statistics/CompTrendChart.tsx
# kind=heading
insights-comp-trend-chart-compensation-over-time = Total compensation over time
# kind=heading note="$series is single when the chart draws one line, which shows its p25-p75 band"
insights-comp-trend-chart-median-total-pay = Median estimated total compensation{ $series ->
        [single] { " " }with p25–p75 spread
       *[several] { "" }
    } · { $period ->
        [all] all history
       *[days] last { $days }d
    }
# kind=sentence note="A reference change moved every estimate at once: a plugin turned on or off, or a new edition of RoleBand's data"
insights-comp-trend-chart-reference-changed = { $count ->
    [one] The dashed line marks when compensation estimates changed together: a change of data, not of the market.
   *[other] Dashed lines mark when compensation estimates changed together: a change of data, not of the market.
}
# kind=aria
insights-comp-trend-chart-reference-marker = Compensation estimates changed on { $date }
# kind=sentence
insights-comp-trend-chart-history-is-still-accruing-one = History is still accruing: one snapshot is recorded per scan, so the trend line stays flat until the nightly scan has run on several days.
# kind=sentence
insights-comp-trend-chart-no-comp-history-yet = No compensation history yet.
# kind=label wording=as-is same-as=insights-clusters-view-roles
insights-comp-trend-chart-roles = { $dim } · { $count } roles
# kind=label wording=as-is
insights-comp-trend-chart-by-family = By family
# kind=label wording=as-is
insights-comp-trend-chart-breakdown = Breakdown
# kind=aria
insights-comp-trend-chart-compensation-percentile-trend = Compensation percentile trend
# kind=status
insights-comp-trend-chart-loading = Loading the compensation trend…
# kind=heading
insights-comp-trend-chart-load-failed = Couldn't load the compensation trend

## features/statistics/CompensationPanel.tsx
# kind=heading wording=as-is
insights-compensation-panel-compensation = Compensation
# kind=sentence wording=as-is
insights-compensation-panel-no-open-roles-with-a = No open roles with a compensation estimate yet.
# kind=label wording=as-is
insights-compensation-panel-open-roles-now-coverage = { $with_comp } / { $total_open } open roles now · { $pct }% coverage
# kind=sentence wording=as-is
insights-compensation-panel-estimated-total-compensation-is-imputed = Estimated total compensation is imputed from a company + level + family lookup. Employers did not state these figures; treat them as a reference point, not an offer.
# kind=label
insights-compensation-panel-published-bands = Posted ranges
# kind=heading wording=as-is
insights-compensation-panel-what-employers-actually-print = What employers actually print
# kind=status
insights-compensation-panel-bands-from-employers = { $bands } ranges · { $employers ->
    [one] { $employers } employer
   *[other] { $employers } employers
}
# kind=heading
insights-compensation-panel-estimated-comp-distribution = Estimated total compensation distribution
# kind=heading
insights-compensation-panel-median-comp-by-level = Median estimated total compensation by level
# kind=label note="A bar's tooltip: the middle half of the group's estimates, then how many roles it rests on"
insights-compensation-panel-spread = p25–p75 { $low }–{ $high } · { $roles }
# kind=heading note="Roles RoleBand's data prices by their base alone, shown apart from total comp"
insights-compensation-panel-estimated-base-by-level = Estimated base salary by level
# kind=label note="Eyebrow over the base-only panel"
insights-compensation-panel-base-only = Base only
# kind=sentence note="Why these roles are apart: no total exists for them"
insights-compensation-panel-base-only-lead = { $count ->
    [one] { $count } more role has only an estimated base salary. Its bonus and equity aren't known yet, so it isn't in the figures above.
   *[other] { $count } more roles have only an estimated base salary. Their bonus and equity aren't known yet, so they aren't in the figures above.
}
# kind=heading wording=as-is
insights-compensation-panel-top-paying-companies = Top paying companies
# kind=heading
insights-compensation-panel-median-pay-by-discipline = Median estimated total compensation by discipline
# kind=heading wording=as-is
insights-compensation-panel-what-a-skill-adds-at = What a skill adds at the same level
# kind=sentence wording=as-is
insights-compensation-panel-roles-naming-the-skill-against = Roles naming the skill against every role at the same level in the same discipline. The estimate is looked up by company, level and discipline, so the difference says which employers ask for the skill, not what the skill itself is worth.
# kind=sentence wording=as-is
insights-compensation-panel-not-enough-priced-roles-per = Not enough priced roles per skill yet.
# kind=label wording=as-is
insights-compensation-panel-roles = { $count ->
    [one] { $count } role
   *[other] { $count } roles
}
# kind=label wording=as-is
insights-compensation-panel-groups-of-roles-or-more = Groups of { $min_roles } roles or more
# kind=sentence
insights-compensation-panel-base-salary-quoted-from-the = Base salary quoted from the posting, not the estimate above or total compensation. Each line is one posted range, however many open roles share it.
# kind=label wording=as-is
insights-compensation-panel-how-compensation-is-estimated = How compensation is estimated
# kind=label wording=as-is
insights-compensation-panel-coverage = Coverage
# kind=label wording=as-is
insights-compensation-panel-middle-50 = Middle 50%
# kind=label wording=as-is
insights-compensation-panel-top-decile = Top decile
# kind=label
insights-compensation-panel-range = Spread
# kind=label
insights-compensation-panel-about-published-salary-bands = About posted ranges
# kind=aria
insights-compensation-panel-how-a-skill-s-pay = How a skill's compensation difference is measured
# kind=label wording=as-is note="A skill row's tooltip: how many roles, then their median pay"
insights-compensation-panel-median = { $roles } · { $p50 } median

## features/statistics/Demand.tsx
# kind=heading wording=as-is
insights-demand-open-roles-by-company = Open roles by company
# kind=sentence
insights-demand-each-role-counts-once-however = Each role counts once, however many places it is listed at. New counts the last 2 days, closed counts today.
# kind=sentence wording=as-is
insights-demand-no-open-roles-at-these = No open roles at these companies.
# kind=sentence wording=as-is note="Under the company chart: the companies folded out of it. $share is none when this side has no open roles to take a share of"
insights-demand-more-hold = { $share ->
    [none] { $companies } more hold { $roles }.
   *[known] { $companies } more hold { $roles } ({ $percent }% of these roles).
}
# kind=button wording=as-is
insights-demand-show-all = Show all { $company }
# kind=heading wording=as-is
insights-demand-open-roles-by-region = Open roles by region
# kind=sentence wording=as-is
insights-demand-a-role-open-in-several = A role open in several regions counts in each. A role that names only a region, such as Remote EMEA, counts there as region-wide, never in each country.
# kind=sentence wording=as-is
insights-demand-no-open-roles-yet = No open roles yet.
# kind=label wording=as-is
insights-demand-all-of = All of { $region }
# kind=label wording=as-is
insights-demand-and-more-countries = { $more ->
    [one] and { $more } more country
   *[other] and { $more } more countries
}
# kind=sentence
insights-demand-name-no-place-we-can = { $role } name no specific place, such as Remote alone.
# kind=label wording=as-is
insights-demand-of = { $shown } of { $companies }
# kind=status
insights-demand-hiring-now-today-new-closed = { $company } hiring now · { $new_today } new in the last 2 days, { $closed_today } closed today
# kind=label wording=as-is
insights-demand-each-role-once = each role once
# kind=label wording=as-is
insights-demand-with-an-open-role = with an open role
# kind=label wording=as-is
insights-demand-how-companies-are-counted = How companies are counted
# kind=heading wording=as-is
insights-demand-longest-open-roles = Longest-open roles
# kind=tooltip wording=as-is
insights-demand-potential-hard-to-fill-signal = Potential hard-to-fill signal.
# kind=sentence wording=as-is
insights-demand-no-data-yet = No data yet.
# kind=sentence wording=as-is
insights-demand-listed-over-a-year-are = { $role } listed over a year are left out: their dates read as stale.
# kind=heading wording=as-is
insights-demand-reposted-roles = Reposted roles
# kind=tooltip wording=as-is
insights-demand-closed-then-reappeared-a-repeated = Closed, then reappeared: a repeated hiring-pressure signal.
# kind=sentence wording=as-is
insights-demand-none-detected-yet = None detected yet.
# kind=label wording=as-is
insights-demand-reposted = { $company } · reposted ×{ $repost_count }
# kind=heading wording=as-is
insights-demand-updated-but-never-closed = Updated but never closed
# kind=tooltip wording=as-is
insights-demand-changed-repeatedly-without-a-closure = Changed repeatedly without a closure event.
# kind=label wording=as-is
insights-demand-updated-times = Updated { $update_count } times
# kind=label wording=as-is
insights-demand-about = About { $title }
# kind=label wording=as-is
insights-demand-how-regions-are-counted = How regions are counted
# kind=label wording=as-is
insights-demand-all-companies-hiring = All companies hiring
# kind=label wording=as-is
insights-demand-find-a-company = Find a company

## features/statistics/DisclosurePanel.tsx
# kind=sentence
insights-disclosure-panel-of-open-roles-have-not = { $pending } of { $open } open roles have not been checked for a posted range yet. They are left out of the rate rather than counted as employers posting nothing.
# kind=label wording=as-is
insights-disclosure-panel-pay-transparency = Pay transparency
# kind=heading
insights-disclosure-panel-who-states-pay = Who posts a range
# kind=sentence
insights-disclosure-panel-the-share-of-open-roles = The share of open roles that post a range, counted against the roles checked so far, not against every open role. Any range counts, whether it is base salary, total compensation or not stated; what the range is worth is a separate question from whether one was posted.
# kind=status
insights-disclosure-panel-of-checked-roles-state-pay = { $rate } of { $checked } checked roles post a range
# kind=sentence
insights-disclosure-panel-no-open-roles-have-been = No open roles have been checked for a posted range yet.
# kind=sentence
insights-disclosure-panel-history-is-still-accruing-one = History is still accruing: one snapshot is recorded per scan, so the line stays flat until the nightly scan has run on several days.
# kind=label wording=as-is
insights-disclosure-panel-over-time = Over time
# kind=heading wording=as-is
insights-disclosure-panel-pay-transparency-trend = Pay transparency trend
# kind=status
insights-disclosure-panel-share-of-checked-open-roles = Share of checked open roles that post a range · { $window }
# kind=sentence wording=as-is
insights-disclosure-panel-no-pay-transparency-history-yet = No pay-transparency history yet.
# kind=sentence note="$since is the day the Same companies set was read"
insights-disclosure-panel-the-market-line-moves-when = The market line moves when companies are added, and added companies post a range less often. Same companies follows only the { $companies } read on { $since }.
# kind=heading
insights-disclosure-panel-published-band-trend = Posted range trend
# kind=sentence
insights-disclosure-panel-the-median-floor-and-ceiling = The median floor and ceiling employers post, counted once per distinct posted range rather than once per role: one range covers many open roles, so per-role counting would track reposting, not compensation. Base salary only; a range that never says whether it includes bonus or equity cannot share this axis.
# kind=status note="$basis names the pay the bands state (vocab-pay-basis-*)"
insights-disclosure-panel-median-published-band = Median posted { $basis } range · { $window }
# kind=sentence
insights-disclosure-panel-no-published-base-salary-band = No posted base salary range recorded yet.
# kind=sentence wording=as-is
insights-disclosure-panel-pay-transparency-over-time-covers = Pay transparency over time covers every discipline: its history is kept per company and level.
# kind=label wording=as-is
insights-disclosure-panel-by-employer = By employer
# kind=label wording=as-is
insights-disclosure-panel-how-the-disclosure-rate-is = How the disclosure rate is measured
# kind=label wording=as-is
insights-disclosure-panel-disclosure-breakdown = Disclosure breakdown
# kind=status
insights-disclosure-panel-share-of-open-roles-stating = { $group ->
    [company] Share of open roles that post a range, by employer
   *[level] Share of open roles that post a range, by level
}
# kind=label wording=as-is
insights-disclosure-panel-trend-breakdown = Trend breakdown
# kind=aria
insights-disclosure-panel-share-of-open-roles-stating-over-time = Share of open roles that post a range over time
# kind=aria
insights-disclosure-panel-about-the-published-band-trend = About the posted range trend
# kind=aria
insights-disclosure-panel-median-published-base-salary-band = Median posted base salary range over time
# kind=status
insights-disclosure-panel-trend-loading = Loading the pay transparency trend…
# kind=heading
insights-disclosure-panel-trend-load-failed = Couldn't load the pay transparency trend
# kind=status
insights-disclosure-panel-band-trend-loading = Loading the posted range trend…
# kind=heading
insights-disclosure-panel-band-trend-load-failed = Couldn't load the posted range trend

## features/statistics/OverlapPanel.tsx
# kind=heading wording=as-is
insights-overlap-panel-how-alike-their-roles-are = How alike their roles are
# kind=sentence wording=as-is
insights-overlap-panel-not-enough-companies-with-skills = Not enough companies with skills to compare. Pick two or more.
# kind=label wording=as-is
insights-overlap-panel-shared-vocabulary = Shared vocabulary
# kind=sentence wording=as-is
insights-overlap-panel-each-company-is-its-open = Each company is its open roles' skills, a skill weighing more the fewer of these companies name it, so skills every company asks for count for little. Companies sit next to the ones most like them. Skills named by at least { $min_jobs } roles per company; what every role is expected to do is left out.
# kind=label wording=as-is
insights-overlap-panel-comparison = { $companies } × { $companies } comparison
# kind=label wording=as-is
insights-overlap-panel-exact-matrix = Exact matrix
# kind=sentence wording=as-is
insights-overlap-panel-cells-show-how-alike-two = Cells show how alike two companies are, ×100; the diagonal shows each company's distinct-skill count. Hover a cell for shared skills.
# kind=label wording=as-is note="The company picker: how many companies are picked, or the default set"
insights-overlap-panel-companies-picked = { $picker ->
    [default] Most open roles
   *[chosen] { $picked } companies
}
# kind=label wording=as-is
insights-overlap-panel-pair-names = { $a } and { $b }
# kind=label wording=as-is
insights-overlap-panel-no-shared-skills-yet = No shared skills yet
# kind=label wording=as-is note="Follows the two names of the closest pair"
insights-overlap-panel-most-alike-of = are the most alike of { $companies } companies on the skills that set companies apart ({ $similarity })
# kind=label wording=as-is
insights-overlap-panel-companies-compared = { $companies } companies compared
# kind=label wording=as-is
insights-overlap-panel-closest-pair = Closest pair
# kind=label wording=as-is
insights-overlap-panel-median-pair = Median pair
# kind=label wording=as-is
insights-overlap-panel-furthest-pair = Furthest pair
# kind=label wording=as-is
insights-overlap-panel-how-skill-overlap-is-calculated = How skill overlap is calculated
# kind=aria wording=as-is
insights-overlap-panel-cross-company-skill-overlap-matrix = Cross-company skill overlap matrix
# kind=label wording=as-is
insights-overlap-panel-skills-open = { $company } · { $skill_count } skills · { $open } open
# kind=label wording=as-is note="$listed is some when shared skills are named after the colon"
insights-overlap-panel-pair-alike = { $listed ->
    [none] { $a } and { $b }: { $percent }% alike, { $shared } of { $union } skills shared
   *[some] { $a } and { $b }: { $percent }% alike, { $shared } of { $union } skills shared: { $skills }
}
# kind=label wording=as-is
insights-overlap-panel-no-shared-skills = { $a } & { $b }: no shared skills

## features/statistics/OverviewPanel.tsx
# kind=label wording=as-is
insights-overview-panel-most-named-skills = Most named skills
# kind=heading wording=as-is
insights-overview-panel-what-is-pulling-the-market = What is pulling the market
# kind=sentence wording=as-is
insights-overview-panel-the-skills-open-roles-name = The skills open roles name most, by how many roles name each.
# kind=label wording=as-is
insights-overview-panel-leads-roles = { $display } leads · { $job_count } roles
# kind=heading wording=as-is
insights-overview-panel-largest-groups = Largest groups
# kind=sentence wording=as-is
insights-overview-panel-no-groups-built-yet = No groups built yet.
# kind=heading wording=as-is
insights-overview-panel-open-the-longest = Open the longest
# kind=sentence wording=as-is
insights-overview-panel-the-roles-advertised-longest-that = The roles advertised longest that are still up. They may be hard to fill, or simply left posted: a careers page does not say which. A listing date over a year old is left out as a stale date.
# kind=sentence wording=as-is
insights-overview-panel-no-open-roles = No open roles.
# kind=label wording=as-is
insights-overview-panel-opened-closed = { $new_count } opened · { $closed_count } closed
# kind=label wording=as-is
insights-overview-panel-about-the-demand-field = About the demand field
# kind=label wording=as-is
insights-overview-panel-what-open-the-longest-means = What open the longest means

## features/statistics/PayBands.tsx
# kind=sentence
insights-pay-bands-each-line-is-one-published = Each line is one posted range. The outlined span is the level's median range.
# kind=label wording=as-is
insights-pay-bands-any-employer = Any employer
# kind=aria
insights-pay-bands-published-base-salary-bands-by = Posted base salary ranges by level
# kind=status
insights-pay-bands-bands-from-employers = { $bands ->
    [one] { $bands } range
   *[other] { $bands } ranges
} · { $employers ->
    [one] { $employers } employer
   *[other] { $employers } employers
}
# kind=label note="The bands the picked employer publishes at a level, or none"
insights-pay-bands-employer-bands = { $published ->
    [none] No range
   *[some] { $range } · { $bands } ranges
}

## features/statistics/SkillsView.tsx
# kind=sentence wording=as-is
insights-skills-view-a-narrowed-view-ranks-skills = A narrowed view ranks skills by how much more often its roles name them than the rest of the market does, with small samples pulled toward the market. The whole market ranks by how many roles name each skill. What every role is expected to do is listed apart.
# kind=sentence wording=as-is
insights-skills-view-no-skills-extracted-for-this = No skills extracted for this selection yet.
# kind=heading wording=as-is
insights-skills-view-expected-of-the-role = Expected of the role
# kind=sentence wording=as-is
insights-skills-view-process-leadership-and-collaboration-asks = Process, leadership and collaboration asks. Most roles name them, so they say what the job is, not what sets these roles apart.
# kind=label wording=as-is
insights-skills-view-against-the-market = Against the market
# kind=heading wording=as-is
insights-skills-view-what-sets-these-roles-apart = What sets these roles apart
# kind=label wording=as-is
insights-skills-view-above-the-line-named-more = Above the line: named more than the market does
# kind=sentence wording=as-is
insights-skills-view-pick-a-company-a-discipline = Pick a company, a discipline or a side to see what sets those roles apart from the market.
# kind=label wording=as-is
insights-skills-view-skill = Skill
# kind=label wording=as-is
insights-skills-view-category = Category
# kind=label wording=as-is
insights-skills-view-share-of-roles = Share of roles
# kind=label wording=as-is
insights-skills-view-lift = Lift
# kind=label wording=as-is note="$view is narrowed when a company, discipline or side is picked"
insights-skills-view-lead-skill = { $view ->
    [narrowed] { $skill } sets these roles apart
   *[market] { $skill } leads
}
# kind=label wording=as-is
insights-skills-view-of-roles-name-it = { $view ->
    [narrowed] { $share } of these roles name it, against { $market_share } of the market
   *[market] { $share } of roles name it
}
# kind=label wording=as-is
insights-skills-view-how-skills-are-ranked = How skills are ranked
# kind=label wording=as-is
insights-skills-view-roles = Roles
# kind=label wording=as-is
insights-skills-view-naming-a-skill = naming a skill
# kind=label wording=as-is
insights-skills-view-share-or-lift = { $view ->
    [narrowed] Lift
   *[market] Share
}
# kind=label wording=as-is
insights-skills-view-ranked-here = ranked here
# kind=label wording=as-is
insights-skills-view-expected = Expected
# kind=label wording=as-is
insights-skills-view-of-every-role = of every role
# kind=label wording=as-is
insights-skills-view-any-company = Any company
# kind=label wording=as-is
insights-skills-view-what-expected-of-the-role = What expected of the role means
# kind=label wording=as-is
insights-skills-view-skills-order = { $view ->
    [narrowed] Skills, most characteristic first
   *[market] Skills, most named first
}
# kind=status
insights-skills-view-loading = Loading skills…
# kind=heading
insights-skills-view-load-failed = Couldn't load skills

## features/statistics/StatisticsView.tsx
# kind=label wording=as-is
insights-statistics-view-window = Window
# kind=label wording=as-is
insights-statistics-view-all-time = All-time
# kind=label wording=as-is
insights-statistics-view-statistics-sections = Statistics sections
# kind=label wording=as-is
insights-statistics-view-discipline = Discipline
# kind=label wording=as-is
insights-statistics-view-time-range = Time range
# kind=label
insights-statistics-view-advanced-view = Advanced view
# kind=heading
insights-statistics-view-advanced-warning-title = Fair warning
# kind=sentence note="Shown once, the first time the person turns the advanced view on; a light joke, not a warning about risk"
insights-statistics-view-advanced-warning-body = Advanced view is for people who read footnotes for fun: percentiles, heatmaps, flow charts and every number behind them. You can switch back any time.
# kind=button
insights-statistics-view-show-me-everything = Show me everything
# kind=button
insights-statistics-view-keep-it-simple = Keep it simple
# kind=sentence note="Above a tab the basic view does not list, opened from a link"
insights-statistics-view-part-of-advanced-view = This tab is part of the advanced view.
# kind=button
insights-statistics-view-show-advanced-view = Show advanced view

## features/statistics/StockTrajectoryPanel.tsx
# kind=heading wording=as-is
insights-stock-trajectory-panel-stock-trajectory = Stock trajectory
# kind=sentence
insights-stock-trajectory-panel-no-open-roles-at-public = No open roles at public companies with a compensation estimate yet, so there is no equity to project against a stock price.
# kind=status note="$split is where the package's base, bonus and equity split comes from"
insights-stock-trajectory-panel-typical-package = { $split ->
    [measured] Typical public-company compensation · measured splits
    [mixed] Typical public-company compensation · mixed split evidence
   *[heuristic] Typical public-company compensation · estimated splits
}
# kind=sentence
insights-stock-trajectory-panel-stock-moves-re-price-equity = { $split ->
    [measured] Stock moves re-price equity; base and bonus stay fixed. Splits are measured per company and level. Reference figures, not offers.
    [mixed] Stock moves re-price equity; base and bonus stay fixed. Splits are measured where available and estimated elsewhere. Reference figures, not offers.
   *[heuristic] Stock moves re-price equity; base and bonus stay fixed. Splits are estimated using a { $bonus_pct } bonus assumption and seniority-based equity. Reference figures, not offers.
}
# kind=label wording=as-is
insights-stock-trajectory-panel-stock-price-change = Stock price change
# kind=button wording=as-is
insights-stock-trajectory-panel-reset-to-today = Reset to today
# kind=label wording=as-is
insights-stock-trajectory-panel-equity-shockwave = Equity shockwave
# kind=heading wording=as-is
insights-stock-trajectory-panel-who-moves-when-the-stock = Who moves when the stock moves
# kind=heading wording=as-is note="$move is the stock scenario's direction: up, down or flat"
insights-stock-trajectory-panel-public-companies = { $move ->
    [up] Public companies · +{ $pct }%
   *[other] Public companies · { $pct }%
}
# kind=sentence wording=as-is
insights-stock-trajectory-panel-sorted-by-equity-exposure-only = Sorted by equity exposure. Only the equity slice moves.
# kind=sentence wording=as-is
insights-stock-trajectory-panel-no-open-roles-at-public-yet = No open roles at public companies yet.
# kind=label wording=as-is
insights-stock-trajectory-panel-ticker = Ticker
# kind=label wording=as-is
insights-stock-trajectory-panel-equity = Equity
# kind=label wording=as-is
insights-stock-trajectory-panel-equity-share = Equity share
# kind=label wording=as-is
insights-stock-trajectory-panel-today = Today
# kind=label wording=as-is
insights-stock-trajectory-panel-projected = Projected
# kind=label wording=as-is
insights-stock-trajectory-panel-change = Change
# kind=label wording=as-is
insights-stock-trajectory-panel-no-exposure = no exposure
# kind=heading wording=as-is
insights-stock-trajectory-panel-private-companies = Private companies
# kind=sentence wording=as-is
insights-stock-trajectory-panel-pre-ipo-equity-is-illiquid = Pre-IPO equity is illiquid with no daily stock price, so this scenario does not change total compensation here.
# kind=label wording=as-is
insights-stock-trajectory-panel-median-tc = Median TC
# kind=tooltip note="The full words behind the Median TC column, for its hover and screen-reader name"
insights-stock-trajectory-panel-median-tc-full = Median total compensation
# kind=label wording=as-is
insights-stock-trajectory-panel-options = Options
# kind=label wording=as-is
insights-stock-trajectory-panel-no-equity = No equity
# kind=label wording=as-is
insights-stock-trajectory-panel-cash-election = Cash election
# kind=label wording=as-is
insights-stock-trajectory-panel-split-source = { $split ->
    [measured] Measured
    [mixed] Part measured
   *[heuristic] Estimated
}
# kind=status
insights-stock-trajectory-panel-split-source-explained = { $split ->
    [measured] Real base/bonus/equity split from this company's levels
    [mixed] Some levels have a real split; the rest are estimated
   *[heuristic] No observed split for this company, so the seniority heuristic is used
}
# kind=label wording=as-is
insights-stock-trajectory-panel-projected-tc = { $projected } projected TC
# kind=tooltip note="The full words behind the projected TC figure, for its hover and screen-reader name"
insights-stock-trajectory-panel-projected-tc-full = { $projected } projected total compensation
# kind=heading note="The Stock tab's figure while the price is unchanged: $share is equity's percent of total compensation, such as 45%"
insights-stock-trajectory-panel-equity-figure = { $share } of total compensation is equity
# kind=label wording=as-is
insights-stock-trajectory-panel-how-stock-trajectory-is-projected = How stock trajectory is projected
# kind=label wording=as-is
insights-stock-trajectory-panel-median-tc-tile = median TC
# kind=tooltip note="The full words behind the median TC tile, for its hover and screen-reader name"
insights-stock-trajectory-panel-median-tc-tile-full = median total compensation
# kind=label wording=as-is
insights-stock-trajectory-panel-at-price-change = { $move ->
    [up] at +{ $pct }%
   *[other] at { $pct }%
}
# kind=label wording=as-is
insights-stock-trajectory-panel-vs-today = vs today
# kind=label wording=as-is
insights-stock-trajectory-panel-of-tc-at-risk = of TC (at risk)
# kind=tooltip note="The full words behind the TC at risk tile, for its hover and screen-reader name"
insights-stock-trajectory-panel-of-tc-at-risk-full = of total compensation (at risk)
# kind=aria wording=as-is
insights-stock-trajectory-panel-stock-price-change-percent = Stock price change percent
# kind=label wording=as-is
insights-stock-trajectory-panel-how-to-read-equity-sensitivity = How to read equity sensitivity
# kind=sentence wording=as-is
insights-stock-trajectory-panel-sensitivity-explained = { $move ->
    [flat] At today's price, each bar is what a 10% rise in the stock adds to typical total compensation. Move the slider for a scenario.
   *[other] Shows the dollar change to typical total compensation under this scenario.
}
# kind=label wording=as-is
insights-stock-trajectory-panel-scenario = { $move ->
    [flat] Per 10% stock move · adjust above for a scenario
    [up] +{ $pct }% scenario
   *[down] { $pct }% scenario
}
# kind=label wording=as-is
insights-stock-trajectory-panel-about-public-company-projections = About public-company projections
# kind=tooltip
insights-stock-trajectory-panel-paid-in-cash-unaffected-by = Paid in cash, unaffected by the stock price
# kind=label wording=as-is
insights-stock-trajectory-panel-why-private-companies-do-not = Why private companies do not move
# kind=status
insights-stock-trajectory-panel-loading = Loading the stock trajectory…
# kind=heading
insights-stock-trajectory-panel-load-failed = Couldn't load the stock trajectory
# kind=label note="An equity vehicle: restricted stock units"
insights-stock-trajectory-panel-rsus = RSUs

## features/statistics/TrendsPanel.tsx
# kind=label wording=as-is
insights-trends-panel-demand-history = Demand history
# kind=heading wording=as-is
insights-trends-panel-skill-demand-over-time = Skill demand over time
# kind=label wording=as-is
insights-trends-panel-each-skill-s-share-of = Each skill's share of the day's skill mentions · { $window }
# kind=label wording=as-is
insights-trends-panel-top-plotted-in-ledger = Top { $plotted } plotted · { $total } in ledger
# kind=sentence wording=as-is
insights-trends-panel-history-is-still-accruing-one = History is still accruing: one snapshot is recorded per scan, so trend lines stay flat until the nightly scan has run on several days.
# kind=sentence wording=as-is
insights-trends-panel-no-skill-history-yet = No skill history yet.
# kind=sentence wording=as-is
insights-trends-panel-what-is-measured-changed-on = What is measured changed on { $dates } (a set of companies arriving, or skills read again), so shares are drawn, not counts.
# kind=label wording=as-is
insights-trends-panel-current-ledger = Current ledger
# kind=label wording=as-is
insights-trends-panel-now = Now
# kind=label wording=as-is
insights-trends-panel-skill-leads = { $skill } leads
# kind=label wording=as-is
insights-trends-panel-nothing-to-plot-yet = Nothing to plot yet
# kind=label wording=as-is
insights-trends-panel-leader-share-line = { $current_share } of skill mentions on the latest day · { $days } days of history · { $window }
# kind=label wording=as-is
insights-trends-panel-history-accrues-one-day-per = History accrues one day per scan · { $window }
# kind=label wording=as-is
insights-trends-panel-leader-s-share = Leader's share
# kind=label wording=as-is
insights-trends-panel-of-skill-mentions = of skill mentions
# kind=label wording=as-is
insights-trends-panel-in-the-ledger = in the ledger
# kind=label wording=as-is
insights-trends-panel-history = History
# kind=label wording=as-is
insights-trends-panel-days = { $count ->
    [one] day
   *[other] days
}
# kind=label wording=as-is
insights-trends-panel-latest-day = Latest day
# kind=label wording=as-is
insights-trends-panel-none-yet = None yet
# kind=label wording=as-is
insights-trends-panel-of-the-series = of the series
# kind=label wording=as-is
insights-trends-panel-of-skill-mentions-open-roles = { $current_share } of skill mentions, { $current } open roles
# kind=label wording=as-is
insights-trends-panel-change-points = change { $share_delta } points
# kind=status
insights-trends-panel-loading = Loading skill trends…
# kind=heading
insights-trends-panel-load-failed = Couldn't load skill trends

## features/statistics/VelocityPanel.tsx
# kind=label wording=as-is
insights-velocity-panel-market-current = Market current
# kind=heading wording=as-is
insights-velocity-panel-hiring-flow = Hiring flow
# kind=sentence wording=as-is
insights-velocity-panel-closures-pull-left-openings-push = Closures pull left, openings push right; diamonds mark update pressure.
# kind=label wording=as-is note="$direction is up when as many roles opened as closed, or more"
insights-velocity-panel-net = { $direction ->
    [up] Net +{ $net } { $window }
   *[down] Net { $net } { $window }
}
# kind=heading wording=as-is
insights-velocity-panel-companies = Companies · { $window }
# kind=label wording=as-is
insights-velocity-panel-open = Open
# kind=label wording=as-is
insights-velocity-panel-opened = Opened
# kind=label wording=as-is
insights-velocity-panel-time-posted = Time posted
# kind=sentence wording=as-is
insights-velocity-panel-from-the-first-scan-that = From the first scan that saw a posting to the scan that found it gone. Employers take postings down for many reasons (filled, paused, expired, re-posted), so this is how long the role was advertised, never how long it took to hire.
# kind=heading wording=as-is
insights-velocity-panel-age-of-open-roles = Age of open roles
# kind=heading wording=as-is
insights-velocity-panel-how-long-postings-stay-up = How long postings stay up
# kind=sentence wording=as-is
insights-velocity-panel-this-builds-up-as-roles = This builds up as roles close: only { $closed_sample } have so far. It fills in once more postings have come down.
# kind=label wording=as-is
insights-velocity-panel-median-age = { $median_days_open } median age
# kind=label wording=as-is
insights-velocity-panel-median-time-posted = { $median_observed_listing_duration_days } median time posted
# kind=label wording=as-is
insights-velocity-panel-more-already-listed-when-their = { $first_scan } more already listed when their company was first scanned
# kind=label wording=as-is
insights-velocity-panel-net-flow = Net flow
# kind=label wording=as-is
insights-velocity-panel-opened-closed = opened − closed
# kind=label wording=as-is
insights-velocity-panel-how-to-read-hiring-flow = How to read hiring flow
# kind=label wording=as-is
insights-velocity-panel-what-time-posted-measures = What time posted measures

## features/statistics/ageCopy.ts
# kind=label wording=as-is
insights-age-copy-listed-today = Listed today
# kind=label wording=as-is
insights-age-copy-listed-for = Listed for { $days }
# kind=label wording=as-is
insights-age-copy-dated-by-the-employer = { $percent }% dated by the employer
# kind=label wording=as-is
insights-age-copy-counted-from-when-each-role = Counted from when each role was first listed · { $dated }

## features/statistics/charts/StatisticsCharts.tsx
# kind=label wording=as-is note="A skill's tooltip: its open roles, then its category"
insights-statistics-charts-skill-open-roles = { $job_count } open roles · { $category }
# kind=aria wording=as-is
insights-statistics-charts-market-demand-field = Market demand field
# kind=label wording=as-is
insights-statistics-charts-company-open-roles = { $open } open roles
# kind=tooltip note="A company's new roles (last 2 days) and closings (today), on its chart tooltip. $new_roles is the new ones ('+3 new') and $closed_roles the closings ('−2 closed'), each in its own colour"
insights-statistics-charts-new-closed-today = { $new_roles } in the last 2 days · { $closed_roles } today
# kind=tooltip note="Roles new at a company in the last 2 days, a part of the line 'new in the last 2 days · closed today'"
insights-statistics-charts-new-count = +{ $fresh } new
# kind=tooltip note="Roles a company closed today, a part of the line 'new · closed today'"
insights-statistics-charts-closed-count = −{ $closed } closed
# kind=aria wording=as-is
insights-statistics-charts-open-roles-by-company = Open roles by company
# kind=label wording=as-is
insights-statistics-charts-open-new-closed = { $label }: { $open } open, { $fresh } new, { $closed } closed
# kind=label wording=as-is
insights-statistics-charts-closed = Closed ←
# kind=label wording=as-is
insights-statistics-charts-opened = → Opened
# kind=aria wording=as-is
insights-statistics-charts-hiring-flow-by-company = Hiring flow by company
# kind=label wording=as-is
insights-statistics-charts-opened-closed-updated = { $company }: { $opened } opened, { $closed } closed, { $updated } updated
# kind=label wording=as-is note="A company's change in equity under the stock scenario: $amount is the size of the change, $direction its sign"
insights-statistics-charts-equity-change = { $direction ->
    [flat] $0 change
    [down] −{ $amount }
   *[up] +{ $amount }
}
# kind=label wording=as-is
insights-statistics-charts-no-change = No change
# kind=aria wording=as-is
insights-statistics-charts-equity-shockwave-by-company = Equity shockwave by company
# kind=label wording=as-is
insights-statistics-charts-share-against-market = { $share }% of these roles · { $market_share }% of the market
# kind=tooltip note="How many times the market's rate a skill is named at, under its share of these roles"
insights-statistics-charts-lift-the-market-s-rate = ×{ $lift } the market's rate
# kind=label wording=as-is
insights-statistics-charts-share-of-these-roles = share of these roles →
# kind=label wording=as-is
insights-statistics-charts-the-market-s-rate = × the market's rate →
# kind=aria wording=as-is
insights-statistics-charts-what-sets-these-roles-apart = What sets these roles apart
# kind=label wording=as-is
insights-statistics-charts-of-these-roles-the-market = { $skill }: { $share }% of these roles, ×{ $lift } the market
# kind=label wording=as-is
insights-statistics-charts-set-changed = set changed
# kind=aria wording=as-is
insights-statistics-charts-skill-demand-trends = Skill demand trends
# kind=label wording=as-is note="$points is the change in the skill's share, in percentage points"
insights-statistics-charts-skill-mentions-change = { $direction ->
    [up] { $skill }: { $share }% of mentions, +{ $points } points
   *[down] { $skill }: { $share }% of mentions, { $points } points
}
# kind=label note="A skill's share of the latest day's skill mentions, with no change stated because what was measured changed within the window"
insights-statistics-charts-skill-mentions-share = { $skill }: { $share }% of mentions
# kind=label wording=as-is
insights-statistics-charts-pair-alike = { $similarity }% alike · { $shared } shared skills
# kind=tooltip note="Two companies compared on the skill overlap chart, its tooltip's title"
insights-statistics-charts-pair = { $a } × { $b }
# kind=label wording=as-is
insights-statistics-charts-more-alike = more alike
# kind=label note="The low end of the overlap scale, opposite more alike"
insights-statistics-charts-less-alike = less
# kind=aria wording=as-is
insights-statistics-charts-cross-company-skill-overlap-heatmap = Cross-company skill overlap heatmap
# kind=label wording=as-is
insights-statistics-charts-pair-similarity = { $a } and { $b }: { $percent }%
# kind=label wording=as-is
insights-statistics-charts-cluster-roles = { $size } roles · { $family }
# kind=aria wording=as-is
insights-statistics-charts-role-cluster-landscape = Role cluster landscape
# kind=label wording=as-is
insights-statistics-charts-roles = { $label }: { $size } roles

## features/statistics/charts/compBands.ts
# kind=sentence
insights-comp-bands-level-summary = { $label }: { $bands } { $bands ->
        [one] range
       *[other] ranges
    } from { $employers } { $employers ->
        [one] employer
       *[other] employers
    }, median { $low } to { $high }.
# kind=toast
insights-comp-bands-1-more-role-states-a = 1 more role posts a range but never says whether it includes bonus or equity, so it is not shown.
# kind=toast
insights-comp-bands-more-roles-state-a-range = { $unclear } more roles post a range but never say whether it includes bonus or equity, so they are not shown.
# kind=toast
insights-comp-bands-1-more-role-states-base = 1 more role posts its base salary in another currency or per hour or month, so it is not on this yearly dollar scale.
# kind=toast
insights-comp-bands-more-roles-state-base-pay = { $elsewhere } more roles post their base salary in another currency or per hour or month, so they are not on this yearly dollar scale.

## features/statistics/charts/disclosure.ts
# kind=label wording=as-is
insights-disclosure-unclassified = Unclassified
# kind=sentence same-as=insights-disclosure-panel-no-open-roles-have-been
insights-disclosure-no-open-roles-have-been = No open roles have been checked for a posted range yet.
# kind=sentence note="$rates lists each group's rate; $unrated counts the groups with nothing checked yet"
insights-disclosure-share-of-checked-open-roles = Share of checked open roles that post a range. { $rates }.{ $unrated ->
        [0] { "" }
        [one] { " " }{ $unrated } more group has no role checked yet, so no rate can be stated for them.
       *[other] { " " }{ $unrated } more groups have no role checked yet, so no rate can be stated for them.
    }
# kind=label wording=as-is
insights-disclosure-of-roles = { $label }: { $rate }, { $disclosed } of { $checked } roles
# kind=label
insights-disclosure-rate-states-pay = { $rate } post a range
# kind=tooltip note="Under a company's share of roles stating pay: the roles that state it, of the open roles checked"
insights-disclosure-of-checked-open-roles = { $disclosed } of { $checked } checked open roles
# kind=sentence wording=as-is
insights-disclosure-no-pay-transparency-history-recorded = No pay-transparency history recorded yet.
# kind=label wording=as-is
insights-disclosure-no-roles-checked-yet = { $dim }: no roles checked yet
# kind=status note="One line of the trend summary: $readings is several when more than one day has a rate; $from is the first day's"
insights-disclosure-of-checked-roles-state-pay = { $series }: { $pct } of { $checked } checked roles post a range{ $readings ->
        [single] { "" }
       *[several] { " " }(from { $from })
    }
# kind=sentence note="The trend chart's summary: $dim is how the lines are grouped, $span whether the chart covers one day or a range, $lines one line per series"
insights-disclosure-share-of-open-roles-stating = Share of open roles that post a range, by { $dim ->
        [company] company
        [level] level
       *[overall] the market
    }, { $span ->
        [day] on { $first }
       *[range] from { $first } to { $last }
    }. { $lines }.
# kind=label wording=as-is
insights-disclosure-not-checked = not checked
# kind=label wording=as-is
insights-disclosure-rate-percent = { $rate }%
# kind=sentence
insights-disclosure-no-published-pay-band-has = No posted range has been recorded yet.
# kind=sentence note="$basis names the pay the bands state (vocab-pay-basis-*): base salary. $readings is several when more than one day has a band; $start_low and $start_high are the first day's"
insights-disclosure-median-published-salary-band-across = Median posted { $basis } range across { $bands } distinct ranges covering { $roles } open roles: { $low_p50 } to { $high_p50 }.{ $readings ->
        [single] { "" }
       *[several] { " " }Started at { $start_low } to { $start_high }.
    } One reading per distinct range, not per role.
# kind=label wording=as-is
insights-disclosure-median-ceiling = Median ceiling
# kind=label wording=as-is
insights-disclosure-median-floor = Median floor
# kind=label
insights-disclosure-no-band-posted = no range posted

## features/statistics/charts/StatisticsCharts.tsx (by hand)
# kind=label wording=as-is
insights-statistics-charts-more-signals = +{ $count } signals
# kind=label wording=as-is
insights-statistics-charts-cluster-size = { $size } roles

## features/statistics/CompensationPanel.tsx
# kind=label wording=as-is
insights-compensation-panel-median-pay = { $p50 } median
# kind=label wording=as-is same-as=insights-statistics-charts-cluster-size
insights-compensation-panel-priced-roles = { $with_comp } roles
# kind=status
insights-compensation-panel-loading = Loading compensation…
# kind=heading
insights-compensation-panel-load-failed = Couldn't load compensation
# kind=label note="Under a pay range: lowest to highest"
insights-compensation-panel-min-max = min–max

## features/statistics/Demand.tsx
# kind=label wording=as-is
insights-demand-open = { $role } open
# kind=status
insights-demand-loading = Loading hiring activity…
# kind=heading
insights-demand-load-failed = Couldn't load hiring activity
# kind=label note="Under a count of roles closed: 3 closed today"
insights-demand-today = today
# kind=label note="Under a count of new roles: 3 new in the last 2 days"
insights-demand-last-2-days = last 2 days

## features/statistics/OverlapPanel.tsx
# kind=label wording=as-is
insights-overlap-panel-skills = { $skill_count } skills
# kind=status
insights-overlap-panel-loading = Loading skill overlap…
# kind=heading
insights-overlap-panel-load-failed = Couldn't load skill overlap
# kind=label note="Under a count of companies: 12 compared"
insights-overlap-panel-compared = compared
# kind=label note="Under a pair's similarity: 82% alike"
insights-overlap-panel-alike = alike

## features/statistics/OverviewPanel.tsx
# kind=label wording=as-is
insights-overview-panel-companies = { $companies } companies
# kind=status
insights-overview-panel-loading = Loading the overview…
# kind=heading
insights-overview-panel-load-failed = Couldn't load the overview

## features/statistics/VelocityPanel.tsx
# kind=label wording=as-is
insights-velocity-panel-opened-count = { $opened } opened
# kind=label wording=as-is same-as=insights-demand-open
insights-velocity-panel-open-count = { $open_total } open
# kind=status
insights-velocity-panel-loading = Loading the hiring pace…
# kind=heading
insights-velocity-panel-load-failed = Couldn't load the hiring pace

## features/statistics/charts/compBands.ts
# kind=label wording=as-is
insights-comp-bands-to = { $low } to { $high }
# kind=sentence note="A level's summary when an employer is picked: $summary is the level's own sentence, $published whether the employer publishes a band at this level, $ranges lists them"
insights-comp-bands-employer-at-level = { $published ->
    [none] { $summary } { $employer } posts no range at this level.
   *[some] { $summary } { $employer }: { $ranges }.
}

## features/statistics/charts/disclosure.ts

## features/statistics/charts/StatisticsCharts.tsx
# kind=label wording=as-is note="A cell of the overlap heatmap: a company against itself shows its skill count, a pair its similarity, a pair with none shows nothing"
insights-statistics-charts-overlap-cell = { $cell ->
    [self] { $skillCount }{ "\u000A" }skills
    [pair] { $similarity }%
   *[empty] { "" }
}

## The two sides of Insights' company split (docs/copy.md)
# kind=label
insights-your-companies = Your companies
# kind=label
insights-other-companies = Other companies
# kind=label note="A period lens: 7d, 30d, 90d"
insights-period-days = { $days }d

## Words several Insights panels share
# kind=label wording=as-is
insights-common-companies = Companies
# kind=label wording=as-is
insights-common-company = Company
# kind=label wording=as-is
insights-common-open-roles = Open roles
# kind=label wording=as-is
insights-common-open-roles-unit = open roles
# kind=label wording=as-is
insights-common-new = New
# kind=label wording=as-is
insights-common-closed = Closed
# kind=label wording=as-is
insights-common-updated = Updated
# kind=label wording=as-is
insights-common-skills = Skills
# kind=label wording=as-is
insights-common-market = Market
# kind=label wording=as-is
insights-common-by-level = By level
# kind=label wording=as-is
insights-common-by-company = By company
# kind=label wording=as-is
insights-common-all-companies = All companies
# kind=label wording=as-is
insights-common-distinct-skills = { $count } distinct skills
# kind=label wording=as-is note="The period a figure covers: all-time, or last 30d"
insights-common-last-days-or-all-time = { $period ->
    [all] all-time
   *[days] last { $days }d
}
# kind=label wording=as-is note="The period a chart covers: all history, or last 30d"
insights-common-last-days-or-all-history = { $period ->
    [all] all history
   *[days] last { $days }d
}

## Skill categories (backend/tracker/skills/catalog.yaml), from copy/skills.ts
# kind=name note="Skill category; slug language"
insights-skill-language = Language
# kind=name note="Skill category; slug framework"
insights-skill-framework = Framework
# kind=name note="Skill category; slug cloud"
insights-skill-cloud = Cloud
# kind=name note="Skill category; slug data"
insights-skill-data = Data
# kind=name note="Skill category; slug ml_ai"
insights-skill-ml-ai = ML / AI
# kind=name note="Skill category; slug infra"
insights-skill-infra = Infra
# kind=name note="Skill category; slug security"
insights-skill-security = Security
# kind=name note="Skill category; slug process"
insights-skill-process = Process
# kind=name note="Skill category; slug leadership"
insights-skill-leadership = Leadership
# kind=name note="Skill category; slug collaboration"
insights-skill-collaboration = Collaboration
# kind=name note="Skill category; slug industry"
insights-skill-industry = Industry

## Statistics names said from codes the server sends: a cluster with
## no terms or family, the cohort series, and the fixed age bands
## (backend/tracker/analytics/velocity.py AGING_BANDS, by `lo`).
# kind=label wording=as-is
insights-cluster-unlabeled = Unlabeled cluster
# kind=label wording=as-is
insights-series-same-companies = Same companies
# kind=label wording=as-is
insights-aging-from-0-days = < 1 week
# kind=label wording=as-is
insights-aging-from-7-days = 1–2 weeks
# kind=label wording=as-is
insights-aging-from-14-days = 2–4 weeks
# kind=label wording=as-is
insights-aging-from-30-days = 1–2 months
# kind=label wording=as-is
insights-aging-from-60-days = 2–3 months
# kind=label wording=as-is
insights-aging-from-90-days = 3 months+

## The Overview's one-line brief, said from the facts the server sends. Each
## sentence is said only when its fact is there; the brief joins them with a space.
# kind=sentence wording=as-is
insights-brief-open = { $open } open roles across { $companies } companies.
# kind=sentence
insights-brief-opened = { $allTime ->
    [yes] { $opened } opened all-time, { $closed } closed.
   *[no] { $opened } opened in { $days }d, { $closed } closed.
}
# kind=sentence wording=as-is
insights-brief-top-skill = Top skill: { $skill } ({ $count } roles).
# kind=sentence wording=as-is
insights-brief-largest-group = Largest group: { $group } ({ $size }).

## features/statistics/LevelsPanel.tsx
# kind=status
insights-levels-loading = Loading the level guide…
# kind=heading
insights-levels-load-failed = Couldn't load the level guide
# kind=heading
insights-levels-figure = How each company names its levels
# kind=heading
insights-levels-figure-translating = { $company } { $code } is { $level }
# kind=sentence
insights-levels-line = Pick any level to see what each company with a level guide calls it.
# kind=sentence
insights-levels-line-translating = The lit column is the same level at every other company.
# kind=label
insights-levels-kpi-guided = With a level guide
# kind=label
insights-levels-kpi-flat = Titles without levels
# kind=label
insights-levels-kpi-flat-sub = Level never stated
# kind=label
insights-levels-kpi-skipped = No { $level } level
# kind=label
insights-levels-kpi-skipped-sub = Nearest level stands in
# kind=label
insights-levels-search = Company or level
# kind=label note="A search placeholder: a company and a level code"
insights-levels-search-example = Google or ICT4
# kind=label
insights-levels-sector = Sector
# kind=label
insights-levels-your-level = { $level }, your level
# kind=label
insights-levels-your-aim = { $level }, your aim
# kind=label
insights-levels-translating-column = { $level }, translating
# kind=aria
insights-levels-translate-from = Translate from { $company } { $code }
# kind=status
insights-levels-translating = Translating { $company } { $code } ({ $level }) across every company
# kind=button
insights-levels-clear = Clear
# kind=sentence
insights-levels-ambiguous = { $count ->
    [one] { $code } is a level at { $count } company. Pick it to translate from.
   *[other] { $code } is a different level at { $count } companies. Pick one to translate from.
}
# kind=label
insights-levels-engineering = Engineering levels
# kind=tooltip
insights-levels-engineering-title = This company lists levels for engineers only
# kind=status
insights-levels-flat = Titles state no level here
# kind=tooltip
insights-levels-flat-title = This company's job titles don't state a level beyond these
# kind=aria
insights-levels-skipped = { $company } has no { $level } level
# kind=status
insights-levels-skipped-closest = No { $level } level. Closest: { $code }
# kind=sentence
insights-levels-no-guide = No level guide for { $company } yet.
# kind=sentence
insights-levels-same-as = Shares the levels of { $company }.
# kind=sentence
insights-levels-followed-without-guide = { $count ->
    [one] { $count } company you follow has no level guide yet.
   *[other] { $count } companies you follow have no level guide yet.
}
# kind=heading
insights-levels-empty = No company or level matches
# kind=button
insights-levels-reset = Reset all
