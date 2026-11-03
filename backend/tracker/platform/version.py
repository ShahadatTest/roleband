"""What code is running — recorded on each run so the question is answerable.

`deploy/run_daily.sh` executes the working tree: it resolves the repo root from
its own path and runs `python -m tracker.daily`. Nothing pins a ref, so a branch
switch silently changes what the nightly scrape executes, and a checkout older
than the database it writes to fails in ways only the build explains (a
company seeded with an adapter that build lacks fails with a bare `KeyError`).

Without a record, diagnosing that means inferring the build from incidental
signatures in the run's own record. One recorded string makes it a lookup
instead, which is the whole point of this module.

Best-effort by construction: a deployment need not be a git checkout, and a
scrape must never fail because it could not name itself. Every failure path
returns None, and the answer is computed once per process.
"""

from __future__ import annotations

import logging
import subprocess
from functools import lru_cache

from tracker.platform.paths import PACKAGED, REPO_ROOT
from tracker.platform.releases import running_version

logger = logging.getLogger(__name__)

#: Fits `scrape_runs.code_version`; also the width of "abc1234-dirty (branch)".
MAX_LEN = 64
_GIT_TIMEOUT_SECONDS = 5.0


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell, repo-local
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("code_version: git %s failed (%s)", " ".join(args), exc)
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@lru_cache(maxsize=1)
def code_version() -> str | None:
    """`"<sha>[-dirty] (<branch>)"` for this checkout, or None if not a git tree.

    The branch is included because it is what a human recognizes, and `-dirty`
    because an uncommitted working tree means the sha alone does not identify
    what ran.
    """
    if PACKAGED:
        return running_version()
    sha = _git("rev-parse", "--short", "HEAD")
    if sha is None:
        return None
    # `--porcelain` is empty iff the tree is clean; any output at all is dirt.
    if _git("status", "--porcelain"):
        sha = f"{sha}-dirty"
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    version = f"{sha} ({branch})" if branch and branch != "HEAD" else sha
    return version[:MAX_LEN]
