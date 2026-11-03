"""The one API answer each company-store refusal gets, on every route.

`company_store` and `db.reconciliation` raise a `CompanyError` whose class says
what kind of refusal it is. A route that calls them raises `company_error(exc)`
and never picks a code itself, so the same refusal reads the same in every
screen (docs/copy.md, "API errors are codes").
"""

from __future__ import annotations

from fastapi import HTTPException

from tracker.api.errors import ErrorCode, api_error
from tracker.company_store import (
    CompanyConflict,
    CompanyError,
    CompanyNotFound,
    ConsentRequired,
    RecipeConflict,
    RecipeNotFound,
)

#: Status and code per refusal class. A refusal answers with the row of the
#: nearest class in its MRO, so `CompanyError` is the fallback for bad input.
COMPANY_REFUSALS: dict[type[CompanyError], tuple[int, ErrorCode]] = {
    CompanyError: (400, ErrorCode.COMPANY_REFUSED),
    CompanyNotFound: (404, ErrorCode.COMPANY_NOT_FOUND),
    CompanyConflict: (409, ErrorCode.COMPANY_CONFLICT),
    ConsentRequired: (409, ErrorCode.CONSENT_REQUIRED),
    RecipeNotFound: (404, ErrorCode.RECIPE_NOT_FOUND),
    RecipeConflict: (409, ErrorCode.RECIPE_CONFLICT),
}


def company_error(exc: CompanyError) -> HTTPException:
    """The API error a company-store refusal answers with."""
    status, code = next(
        COMPANY_REFUSALS[cls]
        for cls in type(exc).__mro__
        if issubclass(cls, CompanyError) and cls in COMPANY_REFUSALS
    )
    return api_error(status, code, str(exc))
