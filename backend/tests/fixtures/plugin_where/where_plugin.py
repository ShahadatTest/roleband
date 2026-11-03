"""A plugin that reads a file relative to its working directory
(tests/test_plugin_sdk.py): in process, from the test's directory, it is
found; over the runner, which starts where the live host starts it, it is not."""

from roleband_plugin_sdk import Plugin

plugin = Plugin("plugin-template")


@plugin.job("refresh")
def refresh(ctx):
    with open("notes.txt") as notes:
        notes.read()
