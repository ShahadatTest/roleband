## Role rows and their controls (src/patterns/jobs/), shared by Radar, Saved and Compare

## Career tracks (fixed product names)
# kind=name
jobs-track-management = Management
# kind=name
jobs-track-product-program = Product & Program
# kind=name
jobs-track-technical = Technical IC
# kind=name
jobs-track-business-customer = Business & Customer

## How a search result matched (never Related: that is a Duplicates verdict)
# kind=label
jobs-match-exact = Exact match
# kind=tooltip
jobs-match-exact-title = The title, link or requisition ID you searched for
# kind=label
jobs-match-close = Close match
# kind=tooltip
jobs-match-close-title = A similar title and the same kind of work
# kind=label
jobs-match-partial = Partial match
# kind=tooltip
jobs-match-partial-title = Similar work, with a different title or focus
# kind=label
jobs-via-keyword = Keyword
# kind=label
jobs-via-fuzzy = Fuzzy
# kind=label note="Inline form, inside jobs-matched-via"
jobs-via-keyword-inline = keyword
# kind=label note="Inline form, inside jobs-matched-via"
jobs-via-fuzzy-inline = fuzzy match
# kind=tooltip note="$sources is a list of the inline forms"
jobs-matched-via = Matched via { $sources }

## Facts on the row
# kind=tooltip
jobs-level-not-stated-title = The posting names no level
# kind=tooltip
jobs-level-not-mapped-title = The title names a level in this company's own terms, not yet mapped to the shared levels
# kind=label
jobs-level-unconfirmed = level unconfirmed
# kind=tooltip
jobs-level-unconfirmed-title = Level implied by the title
# kind=tooltip
jobs-career-track = Career track
# kind=tooltip
jobs-why-world-title = Why this ranks for you: the world this role serves
# kind=aria note="Screen-reader only: the receded row is the visual signal"
jobs-viewed = viewed
# kind=tooltip
jobs-stack-title = This role has been posted more than once
# kind=label
jobs-reposted = reposted
# kind=tooltip
jobs-related-title = Separate, closely related roles
# kind=label note="Other roles at the company with closely related work; never twin"
jobs-related = { $count } related
# kind=tooltip
jobs-places-title = The same role, listed once per place with the same description
# kind=label
jobs-places = { $count ->
    [one] Listed in { $count } place
   *[other] Listed in { $count } places
}
# kind=tooltip
jobs-place-set-title = The same role, listed again at the same place with the same description
# kind=label
jobs-place-set = Listed { $count } times
# kind=label
jobs-standing-badge = May be always open
# kind=label
jobs-unfollowed-badge = No longer scanned
# kind=aria note="After +N on a row with several cities: more: Austin, Denver"
jobs-loc-more = more: { $places }
# kind=tooltip note="$date is a formatted date"
jobs-listed-since-employer = Listed since { $date }, the employer's date
# kind=tooltip
jobs-listed-since-seen = Listed since at least { $date }

## The standing-posting verdict; the reference voice for a hedged verdict
# kind=heading
jobs-standing-title = May be an always-open posting
# kind=sentence note="Follows the title after a colon in Job detail. Pinned wording (pinned.en.json)"
jobs-standing-hedge = patterns in how it is listed, not a verdict on the company. It may still be hiring.
# kind=tooltip note="$signs is a list of the inline sign forms"
jobs-standing-card-title = May be an always-open posting: { $signs }. Patterns in how it is listed, not a verdict on the company. It may still be hiring.
# kind=status
jobs-sign-long-open = Listed for a long time
# kind=status same-as=jobs-place-set note="The same words as a place set's count, a different fact: listed again over time"
jobs-sign-relisted = Listed { $count } times
# kind=status
jobs-sign-date-moved = Its date moved later while it stayed listed
# kind=status note="Inline form, inside jobs-standing-card-title"
jobs-sign-long-open-inline = listed for a long time
# kind=status note="Inline form"
jobs-sign-relisted-inline = listed { $count } times
# kind=status note="Inline form"
jobs-sign-date-moved-inline = its date moved later while it stayed listed

## Row actions
# kind=button
jobs-restore = Restore
# kind=tooltip
jobs-restore-title = Restore to your radar
# kind=aria note="aria-pressed carries whether the role is in compare"
jobs-compare = Compare
# kind=tooltip note="$key is the keyboard shortcut"
jobs-compare-title = Compare ({ $key })
# kind=tooltip
jobs-compare-full = Compare is full
# kind=tooltip
jobs-compare-full-cap = Compare is full: { $cap } at most
# kind=aria note="aria-pressed carries whether the role is saved"
jobs-save = Save
# kind=tooltip
jobs-save-title = Save ({ $key })
# kind=tooltip
jobs-saved-title = Saved ({ $key })
# kind=tooltip
jobs-saved = Saved

## The list's head (JobList.tsx)
# kind=label note="The title column's heading: the product's word for a job, never Title"
jobs-head-role = Role
# kind=label
jobs-head-location = Location
# kind=label
jobs-head-pay = Base
# kind=status note="Before a pay range on a small role card: est. $250K to $300K"
jobs-est-short = est.
# kind=aria note="A sort button's label when its column shows a short form: the short form a voice user says, then the full words"
jobs-sort-label-abbr = { $short } ({ $full })
# kind=aria
jobs-sort-by = Sort by { $label }
# kind=aria
jobs-sort-by-ascending = Sort by { $label }, ascending
# kind=aria
jobs-sort-by-descending = Sort by { $label }, descending

## Beacons in the margin (DismissBeacon.tsx, CompareBeacon.tsx)
# kind=aria note="The way-back pill undoes the dismissal"
jobs-dismissed-aria = Marked { $title } Not for me. Undo
# kind=status
jobs-not-for-me-just-now = Not for me · just now
# kind=aria
jobs-compare-beacon-aria = { $count } in compare. Compare { $count } roles
# kind=aria
jobs-compare-beacon-aria-full = { $count } in compare, full. Compare { $count } roles
# kind=label
jobs-compare-full-pill = full
# kind=label
jobs-in-compare = In compare
# kind=status
jobs-in-compare-count = In compare · { $count } of { $cap }
# kind=status
jobs-compare-not-saved = Not saved. This selection may not survive a reload.
# kind=aria
jobs-compare-remove = Remove { $title } from compare
# kind=button
jobs-clear = Clear

## patterns/jobs/descriptionPassages.ts
# kind=tooltip wording=as-is
jobs-description-passages-description = Description

## patterns/jobs/unfollowed.ts
# kind=sentence
jobs-unfollowed-you-don-t-follow-so = You don't follow { $company }, so this role is no longer scanned. Last seen { $last_seen }.
