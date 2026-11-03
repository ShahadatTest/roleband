"""The public list of what can leave is the code's list (docs/usage-data.md).

Both directions: an event, a property or a browser capability the code can
send and the page does not list fails; so does one the page lists that the code
does not send. A page that drifted from the code would be a promise nobody
checks.
"""

from __future__ import annotations

import re
from pathlib import Path

from tracker.usage_stats.registry import BROWSER_SCOPE, CATALOGUE

DOC = Path(__file__).resolve().parents[2] / "docs" / "usage-data.md"


def _sections(text: str) -> dict[str, str]:
    """`### `name`` heading -> the text up to the next heading."""
    parts = re.split(r"^### ", text, flags=re.MULTILINE)
    sections: dict[str, str] = {}
    for part in parts[1:]:
        title, _, body = part.partition("\n")
        match = re.fullmatch(r"`([^`]+)`", title.strip())
        if match:
            sections[match.group(1)] = body.split("\n## ", 1)[0]
    return sections


def test_every_backend_event_and_property_is_listed_and_nothing_else() -> None:
    sections = _sections(DOC.read_text())
    assert set(sections) == set(CATALOGUE)
    for name, spec in CATALOGUE.items():
        listed = set(re.findall(r"^\| `([a-z0-9_]+)` \|", sections[name], flags=re.MULTILINE))
        assert listed == set(spec.props), name


def test_every_browser_capability_is_listed_and_nothing_else() -> None:
    text = DOC.read_text()
    listed = set(re.findall(r"^- `([a-z_]+)`$", text, flags=re.MULTILINE))
    assert listed == {capability for scope in BROWSER_SCOPE.values() for capability in scope}


def test_the_deletion_request_names_an_address_the_project_publishes() -> None:
    """Deleting what was sent needs somewhere to send the install ID. The page
    names that address itself, and it is one SECURITY.md also publishes, so a
    reader never follows a pointer to a channel that is not there."""
    bullet = re.search(r"^- \*\*Deleting what was sent\*\*.*?(?=^\S|^- |\Z)", DOC.read_text(),
                       flags=re.MULTILINE | re.DOTALL)
    assert bullet, "docs/usage-data.md lost its deletion bullet"
    addresses = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", bullet.group(0))
    assert addresses, "the deletion bullet names no address to send the install ID to"
    published = (DOC.parents[1] / "SECURITY.md").read_text()
    assert all(address in published for address in addresses), addresses
