## Compiler test cases, not wired to a screen (docs/copy.md).

# kind=label
spike-role-count = { $count ->
    [one] { $count } { -role(num: "one") }
   *[other] { $count } { -role(num: "other") }
}
# kind=notification
spike-saved-closed = { $company } closed a role you saved
# kind=notification
spike-saved-closed-count = { $count ->
    [one] { $company } closed { $count } { -role(num: "one") } you saved
   *[other] { $company } closed { $count } { -role(num: "other") } you saved
}
# kind=consent pinned=site-wall note="Must equal followCopy.ts SITE_WALL_SENTENCE: the stored consent"
spike-consent-wall = Its careers site limits automated collection.
