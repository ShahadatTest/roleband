"""Notifier argv construction (pure): osascript fallback + quote safety."""

from __future__ import annotations

from tracker.osnotify import build_command


def test_osascript_fallback_shape():
    cmd = build_command("RoleBand", "hi there", has_terminal_notifier=False)
    assert cmd == ["osascript", "-e", 'display notification "hi there" with title "RoleBand"']


def test_osascript_downgrades_double_quotes():
    # Embedded double quotes would break the AppleScript string literal; they
    # must be downgraded to single quotes.
    cmd = build_command('T"t', 'm"g', has_terminal_notifier=False)
    assert cmd == ["osascript", "-e", "display notification \"m'g\" with title \"T't\""]


def test_osascript_includes_subtitle():
    cmd = build_command("RoleBand", "body", subtitle="sub", has_terminal_notifier=False)
    assert cmd[2].endswith('subtitle "sub"')


def test_terminal_notifier_preferred_when_available():
    cmd = build_command("RoleBand", "body", subtitle="sub", has_terminal_notifier=True)
    assert cmd[0] == "terminal-notifier"
    assert "-subtitle" in cmd and "sub" in cmd
