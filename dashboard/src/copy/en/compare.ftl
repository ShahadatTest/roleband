## compare: moved as it was found (wording=as-is)

## features/compare/CompareScreen.tsx
# kind=button wording=as-is
compare-screen-back = Back
# kind=button wording=as-is
compare-screen-clear = Clear
# kind=button
compare-screen-add-another = Add another
# kind=heading wording=as-is
compare-screen-compare = Compare
# kind=sentence wording=as-is note="$radar and $saved are links, $icon the Compare button's icon"
compare-screen-on-your-or-in-use = On your { $radar } or in { $saved }, use the { $icon } button on a row to add it here.
# kind=link wording=as-is
compare-screen-radar = Radar
# kind=link wording=as-is
compare-screen-saved = Saved
# kind=label wording=as-is
compare-screen-same = Same
# kind=label wording=as-is
compare-screen-fields = fields
# kind=label wording=as-is
compare-screen-descriptions = Descriptions
# kind=sentence wording=as-is
compare-screen-no-description-for-this-role = No description for this role.
# kind=label wording=as-is
compare-screen-shared-passages-hidden = { $count ->
    [one] { $hidden } shared passage hidden
   *[other] { $hidden } shared passages hidden
}
# kind=label wording=as-is note="The frame line while fewer than two roles are picked: $picked is how many; $needed is pair when none is picked yet, another when one is"
compare-screen-picking = { $needed ->
    [pair] { $picked } in compare · pick two
   *[another] { $picked } in compare · pick one more
}
# kind=label wording=as-is note="The frame line: $capacity is full when no more roles fit"
compare-screen-comparing = { $capacity ->
    [full] Comparing { $count } roles · full
   *[open] Comparing { $count } roles
}
# kind=aria wording=as-is
compare-screen-back-aria = Back
# kind=label wording=as-is
compare-screen-comparison = Comparison
# kind=heading wording=as-is
compare-screen-pick-at-least-two = Pick at least two
# kind=label wording=as-is
compare-screen-not-for-me = Not for me: { $title }
# kind=heading
compare-screen-not-for-me-hide-this = Not for me
# kind=label
compare-screen-remove-from-comparison = Remove { $title }
# kind=heading
compare-screen-remove = Remove
# kind=label wording=as-is
compare-screen-show-or-hide-matching-fields = { $fields ->
    [open] Hide { $count } matching fields
   *[folded] Show { $count } matching fields
}
# kind=label wording=as-is
compare-screen-show-or-hide = { $fields ->
    [open] Hide
   *[folded] Show
}
# kind=sentence wording=as-is
compare-screen-passages-legend = { $passages ->
    [shared] Amber passages are not in every posting.
   *[none] These postings share no passages.
}
# kind=label wording=as-is
compare-screen-description-view = { $view ->
    [differences] Show full descriptions
   *[full] Show differences only
}
# kind=status
compare-screen-loading = Loading the comparison…
# kind=heading
compare-screen-load-failed = Couldn't load the comparison

## features/compare/attributes.tsx
# kind=label wording=as-is
compare-attributes-level = Level
# kind=label
compare-attributes-est-comp = Est. TC
# kind=label wording=as-is
compare-attributes-locations = Locations
# kind=label wording=as-is
compare-attributes-regions = Regions
# kind=label wording=as-is
compare-attributes-workplace = Workplace
# kind=label wording=as-is
compare-attributes-listed-for = Listed for
# kind=label wording=as-is
compare-attributes-status = Status
# kind=label wording=as-is
compare-attributes-reposts = Reposts

## features/compare/useCompareController.ts
# kind=label wording=as-is
compare-use-compare-controller-removed-from-compare = Removed { $title } from compare
# kind=label wording=as-is
compare-use-compare-controller-undo = Undo
# kind=toast note="Saving a role, or removing it from Saved, failed; $title is the role's title"
compare-use-compare-controller-could-not-unsave = { $direction ->
    [save] Couldn't save { $title }
   *[unsave] Couldn't remove { $title } from Saved
}
# kind=label wording=as-is
compare-use-compare-controller-couldn-t-restore = Couldn't restore { $title }
# kind=toast
compare-use-compare-controller-not-for-me = Not for me · { $title }
# kind=toast
compare-use-compare-controller-could-not-hide = Couldn't mark { $title } Not for me

## features/compare/CompareScreen.tsx
