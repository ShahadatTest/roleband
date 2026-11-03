"""Concrete `IntelligenceProvider` implementations for the non-Apple backends.

`tracker.local_llm` and `tracker.cloud_llm` own transport, profiles, and their
own error vocabulary; these adapters own ONLY the translation into the seam
(`Availability` / `GenerationResult`). Keeping the translation here rather than
inside those packages is what lets the registry be the single backend picker
without either client package knowing the Protocol exists.
"""
