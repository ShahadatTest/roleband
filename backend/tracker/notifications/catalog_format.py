"""English display primitives for the catalog compiler's Python target."""
from typing import Any


def _f(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return format(value, ",.3f").rstrip("0").rstrip(".")
    return str(value) if value is not None else ""


def _se(value: Any, key: str | int | float) -> bool:
    if value == key:
        return True
    if isinstance(value, (int, float)) and isinstance(key, str):
        return key == ("one" if value == 1 else "other")
    return False
