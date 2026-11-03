"""Job Intelligence — reading structure out of stored postings.

Two things live here, and they are deliberately separate:

  - `extract.py` is the disclosed-salary-band pass. It is **deterministic**: a
    grounded scanner (`schema.extract_grounded_band`) reads the band the posting
    literally states and stores it alongside the level-seeded comp ESTIMATE, so
    the UI can show both. No model, no SDK, no configuration — salary is core
    functionality, so it must behave identically on every machine.

  - The provider abstraction (`provider.py`, `registry.py`, `router.py`,
    `providers/`) and the local/cloud tier ladder built over it
    (`intelligence_runtime/routing.py`) are the model bench's harness
    (`scripts.bench_relevance_review`). No product task routes through them,
    so no RoleBand task sends job text to a cloud model.

The one model task the product runs is `duplicate_review`: on a pair the user
picks in the Review queue, it asks the user's own local model directly.

The Apple Foundation Models provider (`apple_fm.py`) is part of neither path. It
is reachable only from the Settings > Experimental self-test, so the integration
stays exercisable for whenever Apple's on-device model grows a capability worth
routing to, without anything depending on it.
"""
