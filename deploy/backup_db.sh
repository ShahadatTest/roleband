#!/usr/bin/env bash
# Dump Postgres to data/backups/ — deliberately apart from the cluster's own
# storage (~/.roleband/db), so losing or recreating the cluster cannot take the
# backups with it.
#
# Uses the pg_dump bundled with the embedded server, so the dump tool always
# matches the server version. Custom format (-Fc): compressed and selectively
# restorable.
#
# The connection is resolved by `scripts.db_uri`, the same seam the app uses —
# never rebuilt from settings here. A backup script pointed at a stale database
# would keep producing perfectly fresh dumps of the wrong data, and the
# backup_max_age_hours watchdog check cannot detect that.
#
#   Restore / drill: deploy/restore_db.sh --check
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="$ROOT/data/backups"
KEEP_DAILY=14
PY="$ROOT/backend/.venv/bin/python"

# A dump is the whole database: pursuits, notes, and the API keys kept in
# settings, sealed (their key file, ~/.roleband/secret.key, is not in the dump).
# Nothing here is for anyone but the owner, and the umask has to be
# set before the first thing this script creates, which is the directory below.
# It carries into pg_dump and cp, so the archives inherit it too.
umask 077

mkdir -p "$OUT_DIR" "$OUT_DIR/monthly"
# Dumps are kept for good and monthly copies forever, so a directory or an
# archive written under a laxer umask stays readable until something tightens
# it. Every run does, rather than only the run that creates one.
find "$OUT_DIR" -type d -exec chmod 700 {} +
find "$OUT_DIR" -type f -exec chmod 600 {} +

# Every exit path below is a night with no new backup, so it has to be visible.
# A backup that fails quietly is indistinguishable from one that never ran,
# and that blind spot is what makes a data loss unrecoverable. The exit code is
# the report: the supervisor records the run as failed, and its health job
# raises the backup alert from that record. The reason goes to stderr, which is
# the job's log.
fail() {
  echo "backup_db: $1" >&2
  exit 1
}

# Resolve the live database and the matching client tools. This starts the
# embedded server if it is not already running, which is also the readiness
# check: if it cannot start, there is nothing to back up.
cd "$ROOT/backend"
DSN="$("$PY" -m scripts.db_uri dsn 2>/dev/null)" \
  || fail "could not resolve the database (embedded server failed to start?)"
BIN="$("$PY" -m scripts.db_uri bin-dir 2>/dev/null)" \
  || fail "could not locate bundled Postgres client tools"
cd "$ROOT"

if ! "$BIN/pg_isready" -d "$DSN" >/dev/null 2>&1; then
  fail "Postgres not ready — skipped (existing backups untouched)"
fi

# Poison guard. A cluster that is silently recreated leaves an empty DB behind,
# and without this check the next KEEP_DAILY scheduled runs would overwrite
# every good backup with dumps of nothing.
ROWS="$("$BIN/psql" "$DSN" -tAc "select count(*) from jobs" 2>/dev/null || echo 0)"
ROWS="${ROWS//[^0-9]/}"
if [ -z "$ROWS" ] || [ "$ROWS" -eq 0 ]; then
  # Check monthly/ too: dailies can all age out or be cleared by hand, and a
  # surviving monthly copy still means real data once existed to protect.
  if compgen -G "$OUT_DIR/*.dump" >/dev/null || compgen -G "$OUT_DIR/monthly/*.dump" >/dev/null; then
    fail "jobs table is empty but prior backups exist — refusing to overwrite"
  fi
  echo "backup_db: jobs table is empty and no prior backups — taking baseline dump anyway" >&2
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
FINAL="$OUT_DIR/roleband_$STAMP.dump"
TMP="$FINAL.partial"

# Dump to .partial first, promote only after it verifies. A truncated dump must
# never sit in the directory looking like a usable backup.
if ! "$BIN/pg_dump" "$DSN" -Fc -f "$TMP"; then
  rm -f "$TMP"
  fail "pg_dump failed"
fi

# Verify the archive is complete and readable before promoting it: read every
# block of it, data included, into nothing. `pg_restore --list` reads only the
# table of contents at the head of the file, so it passes a dump cut off in its
# data; a full read fails it, and is fast.
if ! "$BIN/pg_restore" --file /dev/null "$TMP" >/dev/null 2>&1; then
  rm -f "$TMP"
  fail "dump failed verification — discarded"
fi

mv "$TMP" "$FINAL"
SIZE="$(du -h "$FINAL" | cut -f1)"
echo "backup_db: wrote $FINAL ($SIZE, jobs=$ROWS)"

# Keep one dump per calendar month forever; they are the only defence against a
# corruption discovered later than KEEP_DAILY days.
MONTH="$(date +%Y%m)"
if ! compgen -G "$OUT_DIR/monthly/roleband_$MONTH*.dump" >/dev/null; then
  cp "$FINAL" "$OUT_DIR/monthly/roleband_${STAMP}.dump"
  echo "backup_db: kept monthly copy for $MONTH"
fi

# Prune dailies only — monthly/ is never pruned.
ls -1t "$OUT_DIR"/roleband_*.dump 2>/dev/null | tail -n +$((KEEP_DAILY + 1)) | while read -r old; do
  rm -f "$old"
  echo "backup_db: pruned $(basename "$old")"
done

exit 0
