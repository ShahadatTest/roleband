#!/usr/bin/env bash
#
# RoleBand: one-shot development setup.
#
# Provisions everything a freshly-cloned checkout needs: the backend virtualenv
# + dependencies, the embedded Postgres with its schema, and the dashboard's
# node modules. Safe to rerun; each step is idempotent.
#
#   ./setup.sh                 # full setup
#   ./setup.sh --with-browsers # also install Playwright browsers (for npm run test:ux)
#   ./setup.sh --skip-dashboard
#
# To install the supervisor as one macOS background item,
# run deploy/install.sh after setup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

WITH_BROWSERS=0
SKIP_DASHBOARD=0
for arg in "$@"; do
  case "$arg" in
    --with-browsers) WITH_BROWSERS=1 ;;
    --skip-dashboard) SKIP_DASHBOARD=1 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$1"; }
die()  { printf '    \033[31m✗\033[0m %s\n' "$1" >&2; exit 1; }

# --------------------------------------------------------------------------- #
step "Preflight"

# One supported toolchain, written down once. CI reads the same two files
# (.github/workflows/*.yml), so a local install and a CI run cannot disagree
# about the interpreter or the Node major. Every check here runs before anything
# is installed, so a refusal leaves nothing half-done behind it.
PY_WANT="$(tr -d '[:space:]' < "$ROOT/.python-version")"
NODE_MIN="$(tr -d '[:space:]' < "$ROOT/.nvmrc")"

py_minor() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true; }

# Exactly this minor. The pins are measured against it, and a newer minor is
# one nothing has ever installed them into.
PYTHON_BIN=""
for cand in "python$PY_WANT" python3; do
  if command -v "$cand" >/dev/null 2>&1 && [ "$(py_minor "$cand")" = "$PY_WANT" ]; then
    PYTHON_BIN="$(command -v "$cand")"; break
  fi
done
[ -n "$PYTHON_BIN" ] || die "Python $PY_WANT not found (as python$PY_WANT, or a python3 that is $PY_WANT) — install it (brew install python@$PY_WANT). Other versions are not measured against the pinned dependencies."
ok "python $("$PYTHON_BIN" -V 2>&1 | cut -d' ' -f2) ($PYTHON_BIN)"

# An existing venv is reused, so it must be the same interpreter; otherwise the
# check above approves one Python and pip installs into another.
if [ -d backend/.venv ]; then
  VENV_PY="$(py_minor backend/.venv/bin/python)"
  [ "$VENV_PY" = "$PY_WANT" ] || die "backend/.venv runs Python ${VENV_PY:-(none found)}, not $PY_WANT. Move it aside and re-run: mv backend/.venv backend/.venv.old && ./setup.sh"
fi

# The lock that pins every transitive package for this platform. No lock, no
# install: an unmeasured platform is refused by name rather than resolved fresh.
case "$(uname -s)/$(uname -m)" in
  Darwin/arm64) LOCK=macos-arm64 ;;
  Linux/x86_64) LOCK=linux-x86_64 ;;
  Linux/aarch64|Linux/arm64) LOCK=linux-aarch64 ;;
  *) die "no dependency lock for $(uname -s)/$(uname -m). Locked platforms: macOS arm64, Linux x86_64, Linux aarch64 (backend/constraints/). Adding one is a measured change: backend/scripts/lock_dependencies.py." ;;
esac
CONSTRAINTS="$ROOT/backend/constraints/$LOCK.txt"
[ -f "$CONSTRAINTS" ] || die "backend/constraints/$LOCK.txt is missing — this checkout is incomplete."
ok "dependency lock: backend/constraints/$LOCK.txt"

if [ "$SKIP_DASHBOARD" -eq 0 ]; then
  { command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; } \
    || die "Node $NODE_MIN+ with npm not found — install it (nvm install $NODE_MIN, or brew install node)."
  NODE_MAJOR="$(node -v | sed -E 's/^v([0-9]+).*/\1/')"
  case "$NODE_MAJOR" in ''|*[!0-9]*) die "could not read a Node version from: $(node -v)" ;; esac
  # A floor, not an exact pin: CI builds with $NODE_MIN and a developer machine
  # may build with a newer major. Below it, npm 10 and npm 11 disagree about the
  # committed lock's nested optional dependencies.
  [ "$NODE_MAJOR" -ge "$NODE_MIN" ] || die "Node $(node -v) is older than $NODE_MIN, which CI builds with and the committed lock needs — install it (nvm install $NODE_MIN)."
  ok "node $(node -v)"
fi

# --------------------------------------------------------------------------- #
step "Environment file"

if [ -f backend/.env ]; then
  ok "backend/.env already exists (left untouched)"
else
  cp backend/.env.example backend/.env
  ok "created backend/.env from .env.example"
fi

# --------------------------------------------------------------------------- #
step "Backend"

cd "$ROOT/backend"

if [ -d .venv ]; then
  ok ".venv already exists"
else
  "$PYTHON_BIN" -m venv .venv
  ok "created .venv"
fi

.venv/bin/python -m pip install --quiet --upgrade pip
# requirements.txt is the runtime; requirements-dev.txt is the test and lint
# tooling the verification gate in AGENTS.md needs. The lock pins everything
# both pull in. apple-fm-sdk is macOS-gated by a marker, so this is portable.
.venv/bin/pip install --quiet -r requirements.txt -r requirements-dev.txt -c "$CONSTRAINTS"
# The robots matcher is its own distribution in this repo, not on an index:
# the host and the plugin SDK's fake host share it so both answer a robots
# file the same way, and the API may not load the SDK to get at it.
.venv/bin/pip install --quiet -e ../robots/python
ok "python dependencies installed from the $LOCK lock (runtime, tests, lint)"

# Optional extras, NEVER fatal. `apple-fm-sdk` publishes an sdist, so
# pip BUILDS it, and its build backend requires a full Xcode — not just the
# Command Line Tools, and the feature is optional at runtime and self-disables
# when the import fails, so it must never take the whole setup down. Pinned by
# the same lock, so installing it is still exact.
if .venv/bin/pip install --quiet -r requirements-optional.txt -c "$CONSTRAINTS" 2>/dev/null; then
  ok "optional extras installed"
else
  warn "optional extras skipped (on macOS, apple-fm-sdk needs a full Xcode to build). Nothing required is affected; see the Apple Intelligence step below."
fi

# The prebuilt extension must be installed before the first migration.
.venv/bin/python -m scripts.install_pg_contrib
ok "pg_trgm installed for the embedded server"

# Starts the embedded Postgres on first use (~/.roleband/db), then migrates it.
.venv/bin/alembic upgrade head
ok "embedded database started and schema at head"

# The first scrape embeds every role it keeps, and that pass is fatal without the
# model's weights — by design: the pipeline fails honestly where the API degrades
# to lexical (tracker/semantic/provision.py). Provision them here, so the scrape
# this script tells you to run next can finish. ~90-600 MB on first
# download; never fatal to setup itself.
if .venv/bin/python -m tracker.semantic.provision; then
  ok "embedding model provisioned"
else
  warn "embedding model not provisioned (offline?). The first scrape stops at its embeddings pass until: .venv/bin/python -m tracker.semantic.provision"
fi

# --------------------------------------------------------------------------- #
step "Apple Intelligence (experimental, optional)"

# Never fatal, and nothing depends on the answer: pay extraction is built in and
# needs no model. This only reports whether the experimental self-test can run.
if .venv/bin/python - <<'PY'
import sys
try:
    import apple_fm_sdk as fm
except Exception:
    sys.exit(3)
try:
    available, reason = fm.SystemLanguageModel().is_available()
except Exception as exc:
    print(f"SDK installed but the model could not be queried: {exc}")
    sys.exit(4)
if available:
    print("Apple Foundation Models is READY on this machine.")
    sys.exit(0)
print(f"SDK installed, but the model is unavailable: {reason}")
sys.exit(5)
PY
then
  ok "Apple Intelligence available — enable it under Settings > Experimental to run a test extraction"
else
  case $? in
    3) warn "apple-fm-sdk not installed (expected off macOS). Nothing is affected — pay extraction is built in." ;;
    *) warn "Apple Intelligence not usable here (needs macOS 26+, Apple silicon, Xcode 26+, enabled in System Settings). Nothing is affected." ;;
  esac
fi

# --------------------------------------------------------------------------- #
if [ "$SKIP_DASHBOARD" -eq 0 ]; then
  step "Dashboard"
  cd "$ROOT/dashboard"
  # `npm ci` or nothing. It installs exactly the committed lock and never writes
  # it; an `npm install` fallback would rewrite package-lock.json whenever the
  # local npm disagrees with it, then report success.
  [ -f package-lock.json ] || die "dashboard/package-lock.json is missing — this checkout is incomplete."
  npm ci --silent || die "npm ci failed; package-lock.json is untouched. The usual cause is an npm that disagrees with the lock — use Node $NODE_MIN (.nvmrc). Changing a dependency is a deliberate \`npm install <pkg>\` with the lock diff reviewed."
  ok "node modules installed from package-lock.json"

  if [ "$WITH_BROWSERS" -eq 1 ]; then
    # Playwright checks host libraries AFTER downloading, and reports a missing
    # one in a warning that its EXIT CODE DOES NOT CARRY. Without reading the
    # log, a green tick would sit under "Host system is missing dependencies to
    # run browsers" and every UX spec would then die at browserType.launch.
    BROWSER_LOG="$(mktemp)"
    npx playwright install chromium webkit 2>&1 | tee "$BROWSER_LOG"
    if grep -q "missing dependencies to run browsers" "$BROWSER_LOG"; then
      warn "browsers downloaded, but this host is missing the libraries they need to LAUNCH. \`npm run test:ux\` fails at browserType.launch until you run:  cd dashboard && sudo npx playwright install-deps"
    else
      ok "playwright browsers installed"
    fi
    rm -f "$BROWSER_LOG"
  fi
fi

# --------------------------------------------------------------------------- #
# What this run installed from. A running supervisor holds a landing whose
# dependencies differ from these until this script has run again. The record
# names every dependency file, the dashboard's lock included, so a run that
# skipped the dashboard records nothing.
if [ "$SKIP_DASHBOARD" -eq 1 ]; then
  warn "installed dependencies not recorded: --skip-dashboard left the dashboard's unchecked; a running supervisor treats them as unknown until a full ./setup.sh"
elif (cd "$ROOT/backend" && .venv/bin/python -m tracker.supervisor.activation record-deps >/dev/null); then
  ok "installed dependencies recorded"
else
  warn "could not record the installed dependencies; a running supervisor treats them as unknown"
fi

# --------------------------------------------------------------------------- #
cd "$ROOT"
step "Done"
cat <<'EOF'
    The database is running and the schema is current, but there are no jobs yet.

    Fill it with synthetic postings, which contacts nobody:

      cd backend
      .venv/bin/python -m scripts.seed_synthetic

    Or collect real postings with a capped scrape, which reads real employers'
    boards and never closes a posting:

      .venv/bin/python -m tracker.daily --max-list 150 --no-hydrate -v

    Then start the API and the dashboard, in two shells:

      cd backend && .venv/bin/uvicorn tracker.api.app:app --port 8010
      cd dashboard && npm run dev

    Open http://localhost:5173. The README's Quickstart says the same.

    Optional:
      deploy/install.sh    install the supervisor as one macOS background item
      ./setup.sh --with-browsers   add Playwright browsers for `npm run test:ux`
EOF
