"""Turn one company's ladder document into slot rows. Pure: no host, no I/O.

Keep parsing apart from fetching, so the parser is tested on recorded
documents and the job only wires the host to it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from roleband_plugin_sdk import FactClaim, PayLevel

#: The source's family names -> RoleBand's taxonomy family. A family the map
#: does not name is skipped, never guessed.
FAMILIES = {
    "Software Engineer": "software_engineering",
    "Product Manager": "product_management",
}


def parse_ladders(doc: dict[str, Any], source_url: str) -> tuple[list[PayLevel], list[FactClaim]]:
    as_of = date.fromisoformat(doc["as_of"])
    levels = []
    for ladder in doc.get("ladders", []):
        family = FAMILIES.get(ladder["name"])
        if family is None:
            continue
        for level in ladder["levels"]:
            levels.append(
                PayLevel(
                    family=family,
                    vendor_family=ladder["name"],
                    label=level["label"],
                    aliases=tuple(level.get("aliases", ())),
                    tc=level.get("total"),
                    base=level.get("base"),
                    stock=level.get("stock"),
                    # Absent is unknown, never zero.
                    bonus=level.get("bonus"),
                    currency=doc["currency"],
                    country=doc.get("country"),
                    source_url=source_url,
                    as_of=as_of,
                )
            )
    observed = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC)
    facts = [
        FactClaim(field=name, value=doc[name], observed_at=observed)
        for name in ("headcount",)
        if name in doc
    ]
    return levels, facts
