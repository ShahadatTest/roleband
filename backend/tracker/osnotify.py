"""Best-effort macOS desktop notifications.

Used by the daily run (on failure) and the watchdog (on a newly-detected
unhealthy condition). Never raises: notification failure must not affect the
pipeline or supervision path.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

TITLE = "RoleBand"


def build_command(
    title: str,
    message: str,
    *,
    subtitle: str | None = None,
    has_terminal_notifier: bool = False,
) -> list[str]:
    """Build the notifier argv. Pure (no IO) so it can be unit-tested.

    Prefers ``terminal-notifier`` when present (richer, non-blocking); otherwise
    falls back to ``osascript`` which ships with macOS. Double quotes are
    downgraded to single quotes to keep the AppleScript string literal intact.
    """
    if has_terminal_notifier:
        cmd = ["terminal-notifier", "-title", title, "-message", message]
        if subtitle:
            cmd += ["-subtitle", subtitle]
        return cmd

    safe_title = title.replace('"', "'")
    safe_msg = message.replace('"', "'")
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    if subtitle:
        script += f' subtitle "{subtitle.replace(chr(34), chr(39))}"'
    return ["osascript", "-e", script]


def notify(title: str, message: str, *, subtitle: str | None = None) -> bool:
    """Post a desktop banner. Returns True if the command was dispatched."""
    cmd = build_command(
        title,
        message,
        subtitle=subtitle,
        has_terminal_notifier=shutil.which("terminal-notifier") is not None,
    )
    try:
        subprocess.run(cmd, check=False, capture_output=True, timeout=10)
        return True
    except Exception as exc:  # noqa: BLE001 - notifications are best-effort
        logger.warning("desktop notification failed: %s", exc)
        return False


def banner(key: str, **params: object) -> str:
    """Desktop product copy has the same FTL owner as dashboard text.

    English until a banner locale is deliberately introduced; no account read
    on the failure path, which may itself be reporting an unavailable database.
    """
    from tracker.notifications.catalog_gen import BANNERS
    return str(BANNERS[key](params))
