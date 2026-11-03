"""The region this machine's user chose in the OS settings, as two letters.

Usage sharing reports a country only as the region part of the OS locale
(docs/architecture.md): a setting the user picked, never a
location measured from an address. `en_US` is US; a region override
(`en_US@rg=sezzzz`, what macOS writes when Region differs from the language's
own) wins, because it is the Region the user set.

macOS keeps it in the global preferences plist (`AppleLocale`); launchd agents
start with no `LANG`, so the plist is the source there, read with `plistlib`
(binary plists included) rather than `defaults`, which would be a subprocess.
Elsewhere it is `LC_ALL`, then `LANG`, then `/etc/locale.conf` on Linux.

An answer this cannot read is None: a missing region drops one property, it
never stops anything. Whether two letters name a real country is the caller's
check. Imports no other tracker module.
"""

from __future__ import annotations

import plistlib
import re
from collections.abc import Mapping
from pathlib import Path

#: `language[_-]Script?[_-]REGION[.codeset][@modifiers]`, e.g. `zh-Hans_CN`, `en_US.UTF-8`.
_REGION = re.compile(r"^[A-Za-z]{2,3}(?:[_-][A-Za-z]{4})?[_-]([A-Za-z]{2})(?=$|[.@])")
#: The Unicode region override in the modifiers, `rg=sezzzz`: two letters then `zzzz`.
_OVERRIDE = re.compile(r"(?:^|;)rg=([A-Za-z]{2})zzzz(?=$|;)")

GLOBAL_PREFERENCES = Path("Library/Preferences/.GlobalPreferences.plist")
LOCALE_CONF = Path("/etc/locale.conf")


def region_from_locale_id(value: str | None) -> str | None:
    """The upper-case region in a locale identifier, or None.

    `en_US` -> US, `en_US.UTF-8` -> US, `zh-Hans_CN` -> CN,
    `en_US@rg=sezzzz` -> SE, `C` / `POSIX` / `en` -> None."""
    if not value:
        return None
    value = value.strip()
    base, _, modifiers = value.partition("@")
    override = _OVERRIDE.search(modifiers) if modifiers else None
    if override:
        return override.group(1).upper()
    match = _REGION.match(base)
    return match.group(1).upper() if match else None


def _locale_conf_lang(text: str) -> str | None:
    """The `LANG=` value in a systemd `locale.conf`, quotes removed."""
    for line in text.splitlines():
        key, _, raw = line.strip().partition("=")
        if key == "LANG":
            return raw.strip().strip("\"'") or None
    return None


def read_os_region(
    *,
    system: str,
    home: Path,
    environ: Mapping[str, str],
    locale_conf: Path = LOCALE_CONF,
) -> str | None:
    """The OS region for this machine. `system` is `platform.system()`."""
    try:
        if system == "Darwin":
            with (home / GLOBAL_PREFERENCES).open("rb") as handle:
                prefs = plistlib.load(handle)
            locale_id = prefs.get("AppleLocale") if isinstance(prefs, dict) else None
            return region_from_locale_id(locale_id if isinstance(locale_id, str) else None)
        for name in ("LC_ALL", "LANG"):
            region = region_from_locale_id(environ.get(name))
            if region:
                return region
        if system == "Linux" and locale_conf.is_file():
            return region_from_locale_id(_locale_conf_lang(locale_conf.read_text(errors="replace")))
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    return None
