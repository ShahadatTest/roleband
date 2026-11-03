#!/usr/bin/env bash
# Build the dashboard beside the one the API serves, then swap it in.
#
# The API serves dashboard/dist by path, so a build written over it would serve
# half old and half new files while it runs, and a failed build would leave a
# broken dashboard. Built into dist.next instead, the served dist changes only
# when a whole build exists, by two renames, and a failed build changes nothing.
#
# dist/.roleband-tree names the tree it was built from (`git rev-parse
# HEAD:dashboard`, read before the build starts), so the supervisor can tell a
# served dashboard that is behind the checkout. That tree does not hold
# uncommitted edits, so a build from a dashboard with any also writes
# dist/.roleband-dirty: packaging reads it and never labels such an app clean.
# The supervisor compares trees only, so a dirty build never looks stale to it.
#
# `build:serve` type-checks and builds; it skips the bundle-size gate that
# `npm run build` adds for contributors and CI. A size change nobody recorded
# is a review question, not a reason to keep serving the old dashboard and
# hold the restart that waits for this build.
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/dashboard"

NEXT="dist.next"
TREE="$(git -C "$ROOT" rev-parse HEAD:dashboard 2>/dev/null || true)"
DIRTY="$(git -C "$ROOT" status --porcelain --untracked-files=normal -- dashboard 2>/dev/null || true)"

rm -rf "$NEXT"
if ! ROLEBAND_DIST_OUT="$NEXT" npm run build:serve; then
  rm -rf "$NEXT"
  echo "roleband/build: the dashboard build failed; the served dashboard is unchanged" >&2
  exit 1
fi
[ -f "$NEXT/index.html" ] || {
  rm -rf "$NEXT"
  echo "roleband/build: the build wrote no index.html; the served dashboard is unchanged" >&2
  exit 1
}
printf '%s\n' "$TREE" > "$NEXT/.roleband-tree"
if [ -n "$DIRTY" ]; then : > "$NEXT/.roleband-dirty"; fi

rm -rf dist.previous
if [ -d dist ]; then mv dist dist.previous; fi
mv "$NEXT" dist
rm -rf dist.previous
echo "roleband/build: dashboard built from ${TREE:-an unversioned tree} and served"
