"""BCP 47 tags in the app's Intl-compatible subset; no product locale registry."""
import re

# Language, optional script/region, variants, extensions and private use.
# Deliberately excludes grandfathered and extlang forms Intl rejects.
LOCALE_TAG = (r"^[A-Za-z]{2,3}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
              r"(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*"
              r"(?:-[0-9A-WY-Za-wy-z](?:-[A-Za-z0-9]{2,8})+)*"
              r"(?:-[xX](?:-[A-Za-z0-9]{1,8})+)?$")
_PATTERN = re.compile(LOCALE_TAG)


def is_locale_tag(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 35 or not _PATTERN.fullmatch(value):
        return False
    parts = value.lower().split("-")
    public = parts[1:parts.index("x")] if "x" in parts else parts[1:]
    singletons = [p for p in public if len(p) == 1]
    variants = []
    for p in parts[1:]:
        if len(p) == 1:
            break
        if len(p) >= 5 or (len(p) == 4 and p[0].isdigit()):
            variants.append(p)
    return len(singletons) == len(set(singletons)) and len(variants) == len(set(variants))
