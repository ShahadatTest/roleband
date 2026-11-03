#!/usr/bin/env bash
# Restore a dump produced by deploy/backup_db.sh.
#
# Uses the pg_restore bundled with the embedded server, so the restore tool
# always matches the target. The connection, and the name of the live database,
# come from `scripts.db_uri`, the same seam the app uses, so a restore can
# never quietly target a different database than the one the app reads.
#
#   deploy/restore_db.sh --check                 # newest dump -> scratch DB, verify, drop it
#   deploy/restore_db.sh --check --into drill_a  # the same drill, into a named scratch DB
#   deploy/restore_db.sh --into roleband_drill   # newest dump -> named scratch DB, kept
#   deploy/restore_db.sh                         # newest dump -> live DB (prompts)
#   deploy/restore_db.sh data/backups/roleband_20260723_161422.dump
#
# EVERY mode restores into a scratch database and verifies it there. Nothing
# replaces live data until that verification passes. A live restore then swaps
# the verified database in by renaming it, and keeps the one it displaces as
# `<live>_before_<timestamp>` for you to drop once you are satisfied. So a dump
# that restores cleanly but verifies empty costs nothing, and a drill runs the
# same path as a live restore minus the swap: "drill passed" means this dump
# will apply.
#
# --check is the drill: it proves a backup is restorable without touching live
# data. A backup that has never been restored is a hypothesis, not a backup.
# --check and --into name a SCRATCH database; neither can name the live one.
# Success is reported only after the restored data is read back: pg_restore
# exited 0, the schema revision is there, and `jobs` and `job_observations`
# hold rows.
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="$ROOT/data/backups"
PY="$ROOT/backend/.venv/bin/python"
CHECK_DB="roleband_restore_check"

INTO=""
DUMP=""
ASSUME_YES=0
CHECK_MODE=0

# Flags are read in full before any of them takes effect, so no flag can skip
# the live-database prompt while a later one moves the target onto the live
# database (`--check --into roleband` must still refuse).
while [ $# -gt 0 ]; do
  case "$1" in
    --into)
      if [ $# -lt 2 ] || [ -z "$2" ]; then echo "restore_db: --into needs a database name" >&2; exit 2; fi
      INTO="$2"; shift 2 ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --check) CHECK_MODE=1; shift ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    -*) echo "restore_db: unknown flag $1" >&2; exit 2 ;;
    *) DUMP="$1"; shift ;;
  esac
done

# Default to the newest daily dump.
if [ -z "$DUMP" ]; then
  DUMP="$(ls -1t "$OUT_DIR"/roleband_*.dump 2>/dev/null | head -1 || true)"
  if [ -z "$DUMP" ]; then
    echo "restore_db: no dumps found in $OUT_DIR" >&2
    exit 1
  fi
fi
if [ ! -f "$DUMP" ]; then
  echo "restore_db: no such dump: $DUMP" >&2
  exit 1
fi

# Resolving the DSN starts the embedded server if it is not already up.
cd "$ROOT/backend"
DSN="$("$PY" -m scripts.db_uri dsn 2>/dev/null)" || {
  echo "restore_db: could not resolve the database" >&2; exit 1; }
LIVE_DB="$("$PY" -m scripts.db_uri database 2>/dev/null)" && [ -n "$LIVE_DB" ] || {
  echo "restore_db: could not name the live database" >&2; exit 1; }
BIN="$("$PY" -m scripts.db_uri bin-dir 2>/dev/null)" || {
  echo "restore_db: could not locate bundled Postgres client tools" >&2; exit 1; }
cd "$ROOT"

# Same server, different database: ask db_uri rather than rewriting the URL in
# shell (a libpq URI carries `?host=`, and `?` is a bash pattern metacharacter).
dsn_for() { (cd "$ROOT/backend" && "$PY" -m scripts.db_uri dsn --database "$1"); }

# Every CREATE, DROP and ALTER DATABASE below runs on the maintenance database,
# never on a database this script is about to rename or replace: you cannot
# rename the database your own session is connected to.
MAINT_DSN="$(dsn_for postgres)" || {
  echo "restore_db: could not reach the maintenance database" >&2; exit 1; }

# The live restore never writes into the live database. It builds a verified
# copy beside it and renames the two, so the only destructive step happens
# after the read-back below has passed.
STAMP="$(date -u +%Y%m%d_%H%M%S)"
SWAP=0
PREVIOUS_DB=""
if [ -n "$INTO" ]; then
  TARGET_DB="$INTO"
elif [ "$CHECK_MODE" -eq 1 ]; then
  TARGET_DB="$CHECK_DB"
else
  TARGET_DB="${LIVE_DB}_restore_${STAMP}"
  PREVIOUS_DB="${LIVE_DB}_before_${STAMP}"
  SWAP=1
fi

# A scratch target is dropped and recreated, so it must be a database nothing
# else needs, and a plain identifier: it is quoted into SQL below.
if [ -n "$INTO" ] || [ "$CHECK_MODE" -eq 1 ]; then
  case "$TARGET_DB" in
    "$LIVE_DB")
      echo "restore_db: refused: '$TARGET_DB' is the live database; --check and --into name a scratch one." >&2
      echo "restore_db: to restore over the live database, run without --check/--into (it asks first)." >&2
      exit 2 ;;
    postgres|template0|template1)
      echo "restore_db: refused: '$TARGET_DB' is a Postgres system database" >&2
      exit 2 ;;
    "${LIVE_DB}"_before_*)
      # Kept by a live restore, and the only way back from a wrong dump.
      echo "restore_db: refused: '$TARGET_DB' is a copy a live restore kept; drop it yourself once it is no longer needed." >&2
      exit 2 ;;
  esac
  if ! [[ "$TARGET_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "restore_db: refused: scratch database name '$TARGET_DB' must be letters, digits and _" >&2
    exit 2
  fi
fi

# Postgres truncates an identifier past 63 bytes, which would silently make the
# two swap names collide with each other or with a previous restore's.
if [ "$SWAP" -eq 1 ] && { [ "${#TARGET_DB}" -gt 63 ] || [ "${#PREVIOUS_DB}" -gt 63 ]; }; then
  echo "restore_db: refused: live database name '$LIVE_DB' is too long to swap safely" >&2
  exit 2
fi

if ! "$BIN/pg_isready" -d "$DSN" >/dev/null 2>&1; then
  echo "restore_db: Postgres not ready" >&2
  exit 1
fi

# A supervisor dispatching on the database being replaced would wreck a swap: a client
# that connects in the moment the live name holds nothing recreates it empty,
# and a running scan reconnects by name and writes into the restored copy.
# Maintenance mode stops its jobs and lets go of the database; until then it
# holds this session lock (`tracker/supervisor/singleton.py`, SUPERVISOR_LOCK_KEY).
SUPERVISOR_LOCK_KEY=91247
refuse_if_supervised() {
  local held
  held="$("$BIN/psql" -X "$DSN" -tAc "SELECT count(*) FROM pg_locks
      WHERE locktype = 'advisory' AND granted AND classid = 0 AND objsubid = 1
        AND objid = $SUPERVISOR_LOCK_KEY
        AND database = (SELECT oid FROM pg_database WHERE datname = current_database())" 2>/dev/null)" \
    || held="unknown"
  if [ "$held" != "0" ]; then
    if [ "$held" = "unknown" ]; then
      echo "restore_db: refused: could not tell whether the supervisor is using '$LIVE_DB'" >&2
    else
      echo "restore_db: refused: the supervisor is running jobs on '$LIVE_DB'" >&2
    fi
    echo "restore_db: pause it first, and resume it once the restore is done:" >&2
    echo "restore_db:   (cd backend && .venv/bin/python -m tracker.supervisor maintenance on)" >&2
    echo "restore_db:   (cd backend && .venv/bin/python -m tracker.supervisor maintenance off)" >&2
    exit 1
  fi
}
if [ "$SWAP" -eq 1 ]; then refuse_if_supervised; fi

# Restoring over the live database destroys whatever is currently in it. Never
# do that silently; only an explicit --yes skips the question.
if [ "$SWAP" -eq 1 ] && [ "$ASSUME_YES" -ne 1 ]; then
  echo "About to restore $(basename "$DUMP") over the LIVE database '$LIVE_DB'."
  echo "It is restored and verified beside the live one first, then swapped in;"
  echo "the database it replaces is kept as '$PREVIOUS_DB'."
  printf "Type the database name to confirm: "
  read -r reply || reply=""
  if [ "$reply" != "$LIVE_DB" ]; then
    echo "restore_db: aborted (no changes made)" >&2
    exit 1
  fi
fi

# A full template, not `-t prefix`: BSD mktemp reads -t as a prefix, GNU as a
# template that must end in X's and refuses this one outright.
RESTORE_ERR="$(mktemp "${TMPDIR:-/tmp}/roleband_restore_err.XXXXXX")"
SCRATCH_MADE=0
SWAPPED=0
#: --into is the one mode that hands its scratch database to the caller.
KEEP_SCRATCH=0
if [ -n "$INTO" ] && [ "$CHECK_MODE" -eq 0 ]; then KEEP_SCRATCH=1; fi

drop_scratch() {
  "$BIN/psql" -X "$MAINT_DSN" -tAq -c "SET client_min_messages = warning" \
    -c "DROP DATABASE IF EXISTS \"$1\" WITH (FORCE)" >/dev/null
}
# A drill leaves nothing behind, whether it passes, fails or is interrupted,
# and so does a live restore that never reached its swap: until then the
# scratch database holds nothing but a copy of the dump.
cleanup() {
  rm -f "$RESTORE_ERR"
  if [ "$SCRATCH_MADE" -eq 1 ] && [ "$KEEP_SCRATCH" -eq 0 ] && [ "$SWAPPED" -eq 0 ]; then
    drop_scratch "$TARGET_DB" 2>/dev/null \
      || echo "restore_db: could not drop scratch database $TARGET_DB" >&2
  fi
}
trap cleanup EXIT

# fail <what went wrong> [<what that means for the target>]
fail() {
  echo "restore_db: FAILED: $1" >&2
  if [ -s "$RESTORE_ERR" ]; then
    echo "restore_db: last errors:" >&2
    tail -5 "$RESTORE_ERR" >&2 || true
  fi
  if [ -n "${2:-}" ]; then echo "restore_db: $2" >&2; fi
  exit 1
}
# Every failure below happens before the swap, so on the live path they all
# mean the same thing. Only a failure between the two renames can leave the
# live name unpopulated, and that path puts it back itself.
LIVE_KEPT=""
if [ "$SWAP" -eq 1 ]; then
  LIVE_KEPT="nothing replaced the live database; it is as it was"
fi

# The target is created from empty in every mode, so the restore has no
# existing schema to clean out. That is what makes a drill tell the truth about
# a live restore: dropping a live schema a later migration has extended can
# fail on objects a dump older than that schema knows nothing about, and an
# empty scratch database would never show it.
drop_scratch "$TARGET_DB"
"$BIN/psql" -X "$MAINT_DSN" -tAc "CREATE DATABASE \"$TARGET_DB\"" >/dev/null
SCRATCH_MADE=1
TARGET_DSN="$(dsn_for "$TARGET_DB")"

echo "restore_db: restoring $(basename "$DUMP") -> $TARGET_DB"

# One transaction: a dump cut short in its data, or any statement that fails,
# rolls the whole restore back instead of leaving the target half-replaced. A clean
# dump restores with exit 0 and an empty stderr, so any other exit is a failure.
set +e
"$BIN/pg_restore" --dbname "$TARGET_DSN" --single-transaction \
  --no-owner --no-privileges "$DUMP" 2>"$RESTORE_ERR"
RC=$?
set -e
[ "$RC" -eq 0 ] || fail "pg_restore exited $RC" "$LIVE_KEPT"

# Proof, not vibes: read back what landed. A restore that "succeeded" into an
# empty database is the failure mode this whole system exists to catch.
FACTS="$("$BIN/psql" -X "$TARGET_DSN" -v ON_ERROR_STOP=1 -tA -F ' ' -c \
  "select coalesce((select string_agg(version_num, ',') from alembic_version), '-'),
          (select count(*) from jobs),
          (select count(*) from job_observations)" 2>"$RESTORE_ERR")" \
  || fail "could not read the restored data" "$LIVE_KEPT"
read -r REVISION JOBS OBSERVATIONS <<<"$FACTS"
[ "$REVISION" != "-" ] \
  || fail "no schema revision restored (alembic_version is empty)" "$LIVE_KEPT"
[ "${JOBS:-0}" -gt 0 ] \
  || fail "jobs is empty: this dump holds no postings to restore" "$LIVE_KEPT"
[ "${OBSERVATIONS:-0}" -gt 0 ] \
  || fail "job_observations is empty: this dump holds no history to restore" "$LIVE_KEPT"

echo "restore_db: $TARGET_DB verified: revision $REVISION; $JOBS jobs, $OBSERVATIONS observations"

if [ "$SWAP" -eq 1 ]; then
  # Again: the restore took minutes, and a supervisor may have started since.
  # Exiting here keeps the live database as it was; the trap drops the copy.
  refuse_if_supervised
  # Close the live database before terminating its backends: an agent that
  # reconnects between the kill and the rename would make the rename fail with
  # the database still in use. The flag travels with the rename, so the
  # displaced database stays closed and the restored one, created open, is not.
  if ! "$BIN/psql" -X "$MAINT_DSN" -v ON_ERROR_STOP=1 -tAq \
      -c "ALTER DATABASE \"$LIVE_DB\" WITH ALLOW_CONNECTIONS false" \
      -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
           WHERE datname = '$LIVE_DB' AND pid <> pg_backend_pid()" \
      -c "ALTER DATABASE \"$LIVE_DB\" RENAME TO \"$PREVIOUS_DB\"" >/dev/null 2>"$RESTORE_ERR"; then
    # The rename did not happen, so this is still the live database, and it
    # may already refuse connections: open it again before saying it is as it was.
    "$BIN/psql" -X "$MAINT_DSN" -tAq \
      -c "ALTER DATABASE \"$LIVE_DB\" WITH ALLOW_CONNECTIONS true" >/dev/null 2>&1 \
      || fail "could not set the live database aside, and could not open it to connections again" \
              "nothing replaced '$LIVE_DB', but it refuses connections; run: ALTER DATABASE \"$LIVE_DB\" WITH ALLOW_CONNECTIONS true"
    fail "could not set the live database aside" "$LIVE_KEPT"
  fi

  # The only window in which the live name holds nothing. Put the old database
  # back rather than leave it: a name that resolves to nothing stops the app,
  # where the data it had is still right here.
  if ! "$BIN/psql" -X "$MAINT_DSN" -v ON_ERROR_STOP=1 -tAq \
      -c "ALTER DATABASE \"$TARGET_DB\" RENAME TO \"$LIVE_DB\"" >/dev/null 2>"$RESTORE_ERR"; then
    "$BIN/psql" -X "$MAINT_DSN" -tAq \
      -c "ALTER DATABASE \"$PREVIOUS_DB\" RENAME TO \"$LIVE_DB\"" \
      -c "ALTER DATABASE \"$LIVE_DB\" WITH ALLOW_CONNECTIONS true" >/dev/null 2>&1 \
      || fail "the restored database could not be swapped in and '$PREVIOUS_DB' could not be put back" \
              "the live database is named '$PREVIOUS_DB' right now; rename it back to '$LIVE_DB'"
    fail "could not swap the restored database in" "$LIVE_KEPT"
  fi
  SWAPPED=1

  echo "restore_db: $LIVE_DB restored; revision $REVISION; $JOBS jobs, $OBSERVATIONS observations"
  # Never dropped here. A restore of the wrong dump is recoverable only while
  # the database it replaced still exists.
  echo "restore_db: the database it replaced is kept as $PREVIOUS_DB"
  echo "restore_db: drop it when you are satisfied:"
  echo "restore_db:   $BIN/psql '$MAINT_DSN' -c 'DROP DATABASE \"$PREVIOUS_DB\"'"
fi

if [ "$CHECK_MODE" -eq 1 ]; then
  drop_scratch "$TARGET_DB" || {
    echo "restore_db: the dump verified, but scratch database $TARGET_DB could not be dropped" >&2
    exit 1; }
  SCRATCH_MADE=0
  echo "restore_db: drill passed: scratch database dropped, live data untouched"
fi

exit 0
