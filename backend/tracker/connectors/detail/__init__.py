"""Company-granular job-detail connector registry."""

from __future__ import annotations

from typing import Protocol

from tracker.connectors.detail.amazon import AmazonDetailConnector
from tracker.connectors.detail.anthropic import AnthropicDetailConnector
from tracker.connectors.detail.apple import AppleDetailConnector
from tracker.connectors.detail.ashby import AshbyDetailConnector
from tracker.connectors.detail.atlassian import AtlassianDetailConnector
from tracker.connectors.detail.base import (
    HtmlDetailConnector,
    sections_to_html,
    sections_to_text,
)
from tracker.connectors.detail.eightfold import EightfoldDetailConnector
from tracker.connectors.detail.google import GoogleDetailConnector
from tracker.connectors.detail.greenhouse import GreenhouseDetailConnector
from tracker.connectors.detail.lever import LeverDetailConnector
from tracker.connectors.detail.microsoft import MicrosoftDetailConnector
from tracker.connectors.detail.netflix import NetflixDetailConnector
from tracker.connectors.detail.openai import OpenAIDetailConnector
from tracker.connectors.detail.tiktok import TikTokDetailConnector
from tracker.connectors.detail.workday import WorkdayDetailConnector
from tracker.platform.util import html_to_text
from tracker.schema import RawJob
from tracker.taxonomy.stated_level import stated_level

# Every built-in company owns a replaceable registry entry even when its source
# currently needs only the shared HTML parser. Company-specific behavior can be
# added without modifying the ATS transport adapter or dashboard.
_workday_connector = WorkdayDetailConnector()
_lever_connector = LeverDetailConnector()
# Google's careers board also serves other companies (google-deepmind), so the
# Google parser is the source's, not only the company's.
_google_connector = GoogleDetailConnector()
DETAIL_CONNECTORS: dict[str, HtmlDetailConnector] = {
    "amazon": AmazonDetailConnector(),
    "apple": AppleDetailConnector(),
    "google": _google_connector,
    "netflix": NetflixDetailConnector(),
    "openai": OpenAIDetailConnector(),
    "anthropic": AnthropicDetailConnector(),
    "microsoft": MicrosoftDetailConnector(),
    # Nvidia is a Workday company; own the registry entry (convention: every
    # built-in has one) while future Workday companies use SOURCE_CONNECTORS.
    "nvidia": _workday_connector,
    # Spotify is a Lever company; same convention as nvidia/workday.
    "spotify": _lever_connector,
}
SOURCE_CONNECTORS: dict[str, HtmlDetailConnector] = {
    "ashby": AshbyDetailConnector(),
    "atlassian": AtlassianDetailConnector(),
    "eightfold": EightfoldDetailConnector(),
    "google": _google_connector,
    "greenhouse": GreenhouseDetailConnector(),
    "lever": _lever_connector,
    "tiktok": TikTokDetailConnector(),
    "workday": _workday_connector,
}
_DEFAULT_CONNECTOR = HtmlDetailConnector()


class DriftRecorder(Protocol):
    def note(self, message: str, **context) -> None: ...


def get_detail_connector(company: str, source: str | None = None) -> HtmlDetailConnector:
    return DETAIL_CONNECTORS.get(company) or SOURCE_CONNECTORS.get(source or "") or _DEFAULT_CONNECTOR


def structure_job_detail(
    job: RawJob,
    drift: DriftRecorder,
    *,
    payload: object | None = None,
    source: str | None = None,
) -> None:
    """Populate sections for every source after optional detail hydration."""
    if job.description_sections or (not job.description_html and payload is None):
        _note_stated_level(job)
        return
    connector = get_detail_connector(job.company, source)
    result = (
        connector.parse_payload(payload, job.description_html)
        if payload is not None
        else connector.parse_html(job.description_html)
    )
    job.description_sections = result.sections
    if result.sections:
        job.description_html = sections_to_html(result.sections)
    job.source_disclosed_comp = result.source_disclosed_comp
    job.description_complete = (
        result.complete if payload is not None else job.description_complete and result.complete
    )
    # Looked, and saw the whole page: an empty or failover read never says the
    # posting states no pay.
    job.pay_looked = (
        connector.pay_from_text and result.mode == "primary" and job.description_complete
        and bool(result.sections)
    )
    if result.mode == "failover":
        drift.note(
            "job detail connector entered failover mode",
            company=job.company,
            req=job.req_id,
            reason=result.reason,
            connector=connector.source,
            recovered_sections=len(result.sections),
            complete=result.complete,
        )
    _note_stated_level(job)


def _note_stated_level(job: RawJob) -> None:
    """Record the ladder rung the posting states, when it states one.

    Here rather than in a connector because it is one rule over the assembled
    description text, and employers that print a rung reach this function
    through different connectors. Never overwrites a rung an
    adapter already read from a structured field: a listing payload that names
    the level outranks prose.
    """
    if job.raw_level:
        return
    text = sections_to_text(job.description_sections) or html_to_text(job.description_html)
    job.raw_level = stated_level(job.company, text)


__all__ = [
    "DETAIL_CONNECTORS",
    "SOURCE_CONNECTORS",
    "get_detail_connector",
    "structure_job_detail",
]
