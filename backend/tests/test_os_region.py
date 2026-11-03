"""The OS region is the region the user set, read without a subprocess.

Usage sharing sends a country only as this setting (docs/architecture.md).
The macOS plist below is written with `plistlib` in binary form, the format
macOS keeps `.GlobalPreferences.plist` in; `AppleLocale` values are the shapes
macOS writes (`@rg=` appears when Region and language disagree).
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from tracker.platform.os_region import (
    GLOBAL_PREFERENCES,
    read_os_region,
    region_from_locale_id,
)

pytestmark = pytest.mark.usefixtures("no_escape")


@pytest.mark.parametrize(
    ("value", "region"),
    [
        ("en_US", "US"),
        ("en_US.UTF-8", "US"),
        ("de-DE", "DE"),
        ("zh-Hans_CN", "CN"),
        ("sr_Latn_RS", "RS"),
        # The Region the user set wins over the language's own country.
        ("en_US@rg=sezzzz", "SE"),
        ("en_GB@calendar=gregorian;rg=uazzzz", "UA"),
        ("en_US@calendar=gregorian", "US"),
        # No region: never guess one from the language ("EN" is not a country).
        ("en", None),
        ("C", None),
        ("POSIX", None),
        ("C.UTF-8", None),
        ("", None),
        (None, None),
        ("garbage value", None),
    ],
)
def test_region_from_locale_id(value: str | None, region: str | None) -> None:
    assert region_from_locale_id(value) == region


def _write_prefs(home: Path, prefs: object) -> None:
    path = home / GLOBAL_PREFERENCES
    path.parent.mkdir(parents=True)
    path.write_bytes(plistlib.dumps(prefs, fmt=plistlib.FMT_BINARY))


def test_macos_reads_applelocale_from_the_binary_plist(tmp_path: Path) -> None:
    _write_prefs(tmp_path, {"AppleLocale": "en_US@rg=sezzzz", "AppleLanguages": ["en-US"]})
    # LANG says otherwise, as a shell might: the plist is what the user set.
    assert read_os_region(system="Darwin", home=tmp_path, environ={"LANG": "de_DE.UTF-8"}) == "SE"


def test_macos_without_a_readable_plist_is_none(tmp_path: Path) -> None:
    assert read_os_region(system="Darwin", home=tmp_path, environ={"LANG": "de_DE.UTF-8"}) is None
    (tmp_path / GLOBAL_PREFERENCES).parent.mkdir(parents=True)
    (tmp_path / GLOBAL_PREFERENCES).write_bytes(b"not a plist")
    assert read_os_region(system="Darwin", home=tmp_path, environ={}) is None


def test_macos_plist_without_applelocale_is_none(tmp_path: Path) -> None:
    _write_prefs(tmp_path, {"AppleLanguages": ["en-US"]})
    assert read_os_region(system="Darwin", home=tmp_path, environ={}) is None


def test_linux_prefers_lc_all_then_lang_then_locale_conf(tmp_path: Path) -> None:
    conf = tmp_path / "locale.conf"
    conf.write_text('LANG="fr_FR.UTF-8"\nLC_TIME=en_GB.UTF-8\n')
    linux = {"system": "Linux", "home": tmp_path, "locale_conf": conf}
    assert read_os_region(environ={"LC_ALL": "pl_PL.UTF-8", "LANG": "it_IT.UTF-8"}, **linux) == "PL"
    assert read_os_region(environ={"LANG": "it_IT.UTF-8"}, **linux) == "IT"
    # A region-less LANG ("C.UTF-8", common in containers) falls through to the file.
    assert read_os_region(environ={"LANG": "C.UTF-8"}, **linux) == "FR"
    assert read_os_region(environ={}, **linux) == "FR"


def test_linux_with_nothing_set_is_none(tmp_path: Path) -> None:
    missing = tmp_path / "absent.conf"
    assert read_os_region(system="Linux", home=tmp_path, environ={}, locale_conf=missing) is None
