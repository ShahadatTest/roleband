"""The relationship lock, in a module of its own so every relationship writer
can take it without importing another writer (`detect` reads the place-set rule,
and `place_sets` takes this lock)."""

#: Serializes relationship decisions and projection rebuilds: a verdict command
#: holds it from before its first read until its commit, and the rebuild takes it
#: before reading links.
LINEAGE_LOCK_KEY = 91243
