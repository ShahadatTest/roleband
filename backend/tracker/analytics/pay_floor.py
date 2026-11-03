"""Does a posting's stated pay clear the user's pay floor?

Pure. Reads the detail route's `disclosed_comp` block, whose `pay_period` has
already been checked against the amount's size. Honest by
construction: anything it cannot verify is no answer, never a verdict.

- Only a YEARLY band in the floor's own currency is compared: an hourly or
  monthly rate is never annualised, and no currency is converted.
- A BASE band can clear the floor, straddle it, or fall below it.
- A band whose basis is total or unstated can only be BELOW: if even the
  figure that may include bonus and equity is under the floor, the base is
  too; if it is above, the base may not be.
"""

from __future__ import annotations

CLEARS = "clears"
STRADDLES = "straddles"
BELOW = "below"


def floor_check(floor: dict | None, disclosed: dict | None) -> dict | None:
    if not floor or not disclosed or not disclosed.get("disclosed"):
        return None
    if disclosed.get("pay_period") != "year":
        return None
    if (disclosed.get("currency") or "USD").upper() != floor["currency"]:
        return None
    low, high = disclosed.get("base_min"), disclosed.get("base_max")
    low = low if low is not None else high
    high = high if high is not None else low
    if low is None or high is None:
        return None
    amount = floor["amount"]
    basis = disclosed.get("pay_basis")
    if high < amount:
        verdict = BELOW
    elif basis != "base":
        return None
    elif low >= amount:
        verdict = CLEARS
    else:
        verdict = STRADDLES
    return {"verdict": verdict, "amount": amount, "currency": floor["currency"], "basis": basis}
