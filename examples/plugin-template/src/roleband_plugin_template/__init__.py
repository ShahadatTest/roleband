"""A minimal RoleBand plugin: one weekly job that reads a ladder per company.

Everything goes through `ctx`: the host fetches (and paces, and enforces the
manifest's hosts), stores what is published, and keeps `ctx.state`.

`ctx.resume` carries the job over as many runs as the list takes: a cursor in
`ctx.state` after each company, a company that fails logged and passed over,
and a stop at a company boundary before the budget runs out, so every run ends
clean and the host continues the pass soon.

`ctx.summary` says what the run has done in the plugin's own words; Settings
shows the latest one beside the plugin, so it is said after each company and
a run the host stops still has one.
"""

from __future__ import annotations

from roleband_plugin_sdk import COMPANY_FACTS, PAY_LEVELS, Company, JobContext, Plugin

from .parse import parse_ladders

plugin = Plugin("plugin-template")

BASE_URL = "https://data.example.com/v1/ladders"


@plugin.job("refresh")
def refresh(ctx: JobContext) -> None:
    read_this_run = 0

    def step(company: Company) -> None:
        nonlocal read_this_run
        if read(ctx, company):
            read_this_run += 1
            ctx.summary(f"Read ladders for {read_this_run} {'company' if read_this_run == 1 else 'companies'}")

    ctx.resume("refresh", ctx.companies(), step, key=lambda c: c.slug)


def read(ctx: JobContext, company: Company) -> bool:
    """Publish one company's ladder and facts; whether there was a ladder to publish."""
    url = f"{BASE_URL}/{company.slug}.json"
    response = ctx.get(url, headers={"accept": "application/json"})
    if response.status == 404:
        # The source has no ladder for this company. Publish nothing, so
        # nothing is retired: absence here is not evidence of anything.
        ctx.log(f"no ladder for {company.slug}")
        return False
    if not response.ok:
        # One company failing is not the run failing. Skip it, say so.
        ctx.log(f"{company.slug}: HTTP {response.status}, skipped", level="warning")
        return False
    levels, facts = parse_ladders(response.json(), url)
    if levels:
        # complete=True: these are all of this company's rows this run, so
        # the host retires, at this publish, the rows this run did not repeat.
        ctx.publish(PAY_LEVELS, company=company.slug, rows=levels, complete=True)
    else:
        # No ladder the parser maps (a family renamed upstream, say). An empty
        # complete publish would retire the company's whole ladder, so publish
        # none: a parse that found nothing is not evidence the ladder is gone.
        ctx.log(f"{company.slug}: no ladder this plugin maps, levels not published", level="warning")
    ctx.publish(COMPANY_FACTS, company=company.slug, rows=facts, complete=True)
    return bool(levels)
