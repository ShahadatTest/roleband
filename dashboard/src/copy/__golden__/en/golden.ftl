## The compiler's golden catalog: one case per construct the subset allows.

-thing = { $num ->
    [one] posting
   *[other] postings
}

# kind=label
plain = Saved
# kind=sentence
exact-before-category = { $count ->
    [0] Nothing yet
    [one] One { -thing(num: "one") }
   *[other] { $count } { -thing(num: "other") }
}
# kind=sentence
by-string = { $stage ->
    [applied] You applied
    [interviewing] You are interviewing
   *[other] You are considering it
}
# kind=sentence
two-values = { $company } has { $count } open
# kind=label
with-attributes = Search
    .placeholder = Search titles and descriptions
    .aria-label = Search roles
# kind=sentence
escaped = Braces stay literal: {"{"}name{"}"} and “quotes”.
