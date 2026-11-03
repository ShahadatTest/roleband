"""AI work that needs the database, sitting above the model backends.

`tracker.intelligence` owns the model seam: the provider Protocol, the registry,
the adapters wrapping the two LLM clients, the prompts and the output schemas. It
sits BELOW the service tier, which is what lets `db/repo.py` and
`semantic/anchors.py` import pure pieces of it.

That is also why it cannot rise wholesale, and why the AI code which does reach
the store (the passes, the routing assembly, the profile stores, the telemetry
writer) lives here instead, in the L4 services row: from below, it would be AI
code reaching the DB or the settings store against the layer contract.

Keeping them in one package rather than scattering them across `settings_store`,
`lineage` and `enrich` keeps the runtime findable, and keeps the routing
ladder's egress gate in one file. Search query parsing (`search/llm.py`) is the
one other path to a cloud model, and it takes the same switch.
"""
