#!/usr/bin/env bash
# Is the working tree safe to run UNATTENDED?
#
# Exit 0 = go. Non-zero = do not start a scrape.
#
# Background collection reads the working tree. The supervisor waits for an
# unchanged dirty tree to pass this gate; a clean tree needs no local suite.
# Proof is keyed to the scoped source fingerprint; edits in that scope invalidate it.
#
# The pipeline's database advisory lock serializes collection across checkouts.
# Filesystem locks and proof files belong to each checkout's data directory.
# This gate certifies source in the checkout whose jobs will run.
#
# Scope is the code that runs unattended: `backend/`, the robots matcher and the
# plugin SDK it loads, and the `deploy/` wrappers. The scrape never executes
# dashboard code, and blocking a run over a CSS edit would be the same
# over-refusal in a new hat.
#
# Modes:
#   (none)            verify, running the suite if the tree needs it
#   --status          print the fingerprint and say whether this exact tree is
#                     proven; never runs the suite. Exit 0 proven, 3 not yet.
#   --expect <sha>    verify only the tree with this fingerprint: exit 76 if the
#                     tree differs before the suite starts or changed while it ran,
#                     and certify nothing in either case.
#   --clear-residue   stop the clusters and drop the scratch databases a killed
#                     suite left behind; runs no suite.
#
# Exit codes: 0 proven, 3 not yet proven (--status), 75 refused (the suite
# failed or could not run), 76 the tree moved, 77 another preflight is running.
#
# Escape hatches:
#   ROLEBAND_SKIP_PREFLIGHT=1   run anyway (operator override)
#   ROLEBAND_PREFLIGHT_TIMEOUT  seconds before a hung suite is abandoned (default 300)
#   ROLEBAND_PREFLIGHT_PYTHON   the interpreter that runs the suite (default the
#                               checkout's venv; a worktree has none)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ROLEBAND_PREFLIGHT_PYTHON:-$ROOT/backend/.venv/bin/python}"
TIMEOUT_SECS="${ROLEBAND_PREFLIGHT_TIMEOUT:-300}"
SCOPE=(backend robots sdk/python deploy)

# A killed suite leaves its throwaway clusters running (each detaches from the
# suite) and its scratch databases in the server. The suite's temp root is ours
# alone, so whatever runs under it is a leftover of this script: cleared before
# the suite, after it, and on a stop. A SIGKILL skips the last; the next run's
# first clearing, or the supervisor's `--clear-residue` after the stop, catches
# it. Outside the checkout, which tests may not write into, and one per
# checkout, so the next run here finds what this one left.
BASETEMP="${TMPDIR:-/tmp}"
BASETEMP="${BASETEMP%/}/roleband-preflight-$(printf '%s' "$ROOT" | shasum -a 256 | cut -c1-12)/pytest"
clear_residue() { (cd "$ROOT/backend" && "$PY" -m tracker.supervisor.residue "$BASETEMP") || true; }

MODE=verify
EXPECT=""
case "${1:-}" in
  --status) MODE=status ;;
  --clear-residue) clear_residue; exit 0 ;;
  --expect) MODE=verify; EXPECT="${2:?--expect needs a fingerprint}" ;;
  "") ;;
  *) echo "roleband/preflight: unknown argument $1" >&2; exit 2 ;;
esac

say() { echo "roleband/preflight: $*"; }
fail() { echo "roleband/preflight: $*" >&2; }

if [ "${ROLEBAND_SKIP_PREFLIGHT:-0}" = "1" ]; then
  say "skipped (ROLEBAND_SKIP_PREFLIGHT=1)"
  [ "$MODE" = status ] && echo "skipped"
  exit 0
fi

# No git, or not a checkout: nothing to compare against, so nothing to withhold.
if ! command -v git >/dev/null 2>&1 || ! git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  say "not a git checkout — no tree check possible, proceeding"
  [ "$MODE" = status ] && echo "unversioned"
  exit 0
fi

# `--porcelain` includes untracked files: a new, unimported-yet module is still
# a half-finished edit, and `tracker.blueprint`-style registries do import by
# discovery.
DIRT="$(git -C "$ROOT" status --porcelain -- "${SCOPE[@]}" 2>/dev/null || true)"
HEAD_REF="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"

if [ -z "$DIRT" ]; then
  say "clean at $HEAD_REF — no preflight needed"
  [ "$MODE" = status ] && echo "clean"
  exit 0
fi

# Scheduler ticks every ten minutes. Re-running the whole suite on every tick
# would itself be an availability problem, so cache success for the exact
# backend state: HEAD + staged/unstaged binary diffs + every untracked path and
# content hash. Any byte change yields a different fingerprint and re-runs the
# suite. A reverted tree may reuse its prior proof, which is exactly valid.
CACHE_FILE="$ROOT/data/preflight-passed.sha256"
mkdir -p "$ROOT/data"
fingerprint() {
  {
    git -C "$ROOT" rev-parse HEAD
    git -C "$ROOT" diff --binary -- "${SCOPE[@]}"
    git -C "$ROOT" diff --cached --binary -- "${SCOPE[@]}"
    while IFS= read -r path; do
      printf '%s\\0' "$path"
      shasum -a 256 "$ROOT/$path"
    done < <(git -C "$ROOT" ls-files --others --exclude-standard -- "${SCOPE[@]}" | LC_ALL=C sort)
  } | shasum -a 256 | awk '{print $1}'
}
FINGERPRINT="$(fingerprint)"
CACHED="$(test -f "$CACHE_FILE" && tr -d '[:space:]' < "$CACHE_FILE" || true)"
if [ "$CACHED" = "$FINGERPRINT" ]; then
  say "dirty at $HEAD_REF but exact tree already passed — using cached proof"
  [ "$MODE" = status ] && echo "$FINGERPRINT"
  exit 0
fi

if [ "$MODE" = status ]; then
  echo "$FINGERPRINT"
  exit 3
fi

if [ -n "$EXPECT" ] && [ "$EXPECT" != "$FINGERPRINT" ]; then
  fail "the tree is not the one asked for (expected $EXPECT, found $FINGERPRINT); checking nothing"
  exit 76
fi

say "DIRTY at $HEAD_REF — verifying before an unattended run:"
echo "$DIRT" | sed 's/^/roleband\/preflight:   /'

if [ ! -x "$PY" ]; then
  fail "no venv at $PY — cannot verify a dirty tree, refusing"
  exit 75
fi

# One suite at a time. Two suites on one machine each run past the cap, so
# neither ever records a pass. A run that finds the lock taken exits 77 (busy,
# never a verdict on the tree); a later run reuses the proof the holder records.
# The lock is a symlink naming the holder's pid, which `ln -s` creates
# atomically. A holder killed before its trap runs leaves it behind, so a lock
# whose pid is gone is taken over.
LOCK="$ROOT/data/preflight.lock"
if ! ln -s "$$" "$LOCK" 2>/dev/null; then
  HOLDER="$(readlink "$LOCK" 2>/dev/null || true)"
  if [ -n "$HOLDER" ] && kill -0 "$HOLDER" 2>/dev/null; then
    fail "another preflight (pid $HOLDER) is verifying the tree, skipping this run"
    exit 77
  fi
  rm -f "$LOCK"
  if ! ln -s "$$" "$LOCK" 2>/dev/null; then
    fail "another preflight took the lock, skipping this run"
    exit 77
  fi
fi
trap 'rm -f "$LOCK"' EXIT

# Use `timeout` only if present (older macOS has none; coreutils' gtimeout counts).
TIMEOUT_BIN=""
command -v timeout >/dev/null 2>&1 && TIMEOUT_BIN="timeout"
command -v gtimeout >/dev/null 2>&1 && TIMEOUT_BIN="gtimeout"

say "running the backend suite (-x, first failure stops it)"
# Unattended, on a machine someone may be using: four workers, not the budget
# `-n auto` sizes for an interactive run.
export PYTEST_XDIST_AUTO_NUM_WORKERS=4
# From backend/, where pytest.ini sets the paths and the parallel workers: the
# caller's directory is not to be trusted.
cd "$ROOT/backend" || { fail "no backend directory at $ROOT/backend"; exit 75; }

clear_residue
mkdir -p "$(dirname "$BASETEMP")"
trap 'clear_residue; exit 75' TERM INT HUP
# `--foreground` keeps the suite in this script's process group: without it
# `timeout` gives the suite a group of its own, which a stop sent to the
# script's group (the supervisor's, launchd's) never reaches.
if [ -n "$TIMEOUT_BIN" ]; then
  "$TIMEOUT_BIN" --foreground "$TIMEOUT_SECS" "$PY" -m pytest -q -x --no-header -p no:cacheprovider --basetemp "$BASETEMP"
else
  "$PY" -m pytest -q -x --no-header -p no:cacheprovider --basetemp "$BASETEMP"
fi
rc=$?
trap - TERM INT HUP
clear_residue

if [ "$rc" -eq 124 ]; then
  fail "suite exceeded ${TIMEOUT_SECS}s — treating as unsafe, skipping this run"
  exit 75
fi
if [ "$rc" -ne 0 ]; then
  fail "SUITE FAILED (exit $rc) — refusing to scrape a broken working tree."
  fail "No ScrapeRun was opened, so nothing is left half-written or stuck 'running'."
  fail "The supervisor checks the changed tree again before collection can resume."
  fail "Override with ROLEBAND_SKIP_PREFLIGHT=1 if you know better."
  exit 75
fi

# The suite proved the tree it started on. An edit during the run makes that a
# different tree, which this pass has not proven.
AFTER="$(fingerprint)"
if [ "$AFTER" != "$FINGERPRINT" ]; then
  fail "the tree changed while the suite ran (now $AFTER); certifying nothing"
  exit 76
fi

TMP_CACHE="$CACHE_FILE.$$"
printf '%s\n' "$FINGERPRINT" > "$TMP_CACHE"
mv "$TMP_CACHE" "$CACHE_FILE"
say "suite passed — dirty tree is self-consistent, proceeding"
exit 0
