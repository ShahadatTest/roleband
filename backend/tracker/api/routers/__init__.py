"""FastAPI routers composing the RoleBand API, one module per surface.

Route paths are declared in full (no router prefixes), so each path reads
where it is declared exactly as the frozen route table
(tests/fixtures/route_table.json) lists it. `app.py` imports each module and
includes `spa` last: it owns the catch-all.
"""
