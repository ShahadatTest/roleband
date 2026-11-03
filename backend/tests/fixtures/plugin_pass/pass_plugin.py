"""A plugin whose margin exceeds its budget: it stops before its first unit
and says `more` (tests/test_plugin_sdk.py, over the real runner)."""

from roleband_plugin_sdk import Plugin

plugin = Plugin("plugin-template")


@plugin.job("refresh")
def refresh(ctx):
    ctx.resume("refresh", ctx.companies(), lambda c: None, key=lambda c: c.slug, margin=60)
