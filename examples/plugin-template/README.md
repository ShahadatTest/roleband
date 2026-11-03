# RoleBand plugin template

A plugin adds a data source to RoleBand without the core importing it. It runs
in its own process, talks to the host over stdio, and publishes typed rows into
the slots its manifest declares. The core decides what to do with them.

> **Preview.** Plugins are a preview in RoleBand's first release: the manifest,
> the SDK and the host protocol may change between releases.

## Layout

| Path | What |
|---|---|
| `roleband-plugin.toml` | The manifest: id, slots, hosts, jobs. The user approves this file; any change needs approval again. |
| `src/roleband_plugin_template/__init__.py` | The `Plugin` and its jobs. Every fetch and write goes through `ctx`. |
| `src/roleband_plugin_template/parse.py` | Pure parsing, tested on recorded documents. |
| `tests/` | Parser tests, the job under the SDK fake host, the no-network check. |

## Rules the host enforces

- Fetch only through `ctx.get`, only from `[network].hosts`. The host sets the
  identity and pacing; a plugin never names a User-Agent.
- Importing a network or process module (`httpx`, `requests`, `socket`,
  `subprocess`, ...) fails `python -m roleband_plugin_sdk.checks src`, and the
  host will not load the plugin.
- Publish only the slots a job declares, only for companies the core knows.
  Rows are validated on both sides; a missing amount is `None`, never `0`.
- `complete=True` means "all of this company's rows in this slot this run": the
  host reads them from that publish and retires the rows it did not repeat,
  whatever the run's end. Rows are never deleted. Publish `complete=True` only
  once you have read the company whole. More rows than one publish takes go in
  chunks: each but the last `complete=False`, the last `complete=True`.
- A job's `budget_seconds` is a ceiling: when it is spent the run ends
  `bounded`; companies it had already published whole stay read.

## Develop

```bash
pip install /path/to/roleband/robots/python /path/to/roleband/sdk/python -e ".[test]"
python -m pytest -q
python -m roleband_plugin_sdk.checks src
```
