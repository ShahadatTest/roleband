### eager: the shell imports this file, so every message in it ships in the shell
### (docs/copy.md section 3). The compiler numbers its messages first.

## Words the formatting helpers write (src/format.ts)

# kind=label
format-days-today = today
# kind=label
format-days = { $count ->
    [one] { $count } day
   *[other] { $count } days
}
# kind=label
format-age-never = never
# kind=label
format-age-just-now = just now
# kind=label note="Minutes, abbreviated: 15m ago"
format-age-minutes = { $count }m ago
# kind=label note="Hours, abbreviated: 3h ago"
format-age-hours = { $count }h ago
# kind=label note="Days, abbreviated: 3d ago"
format-age-days = { $count }d ago
# kind=label
format-fresh = Fresh
# kind=label
format-stale = Stale
# kind=label note="The freshness badge: the word, then how old"
format-freshness = { $word } · { $age }
