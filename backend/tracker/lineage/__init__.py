"""Repost lineage: detect when a posting is a re-listing of an older one.

A company routinely closes a requisition and re-posts a near-identical role under
a fresh req_id (or, for URL-scraped sources, a changed slug). Because job identity
is `company:req_id`, the pipeline treats the re-listing as a brand-new job, which
inflates "new" counts and resets the aging clock. This package links such postings
into a lineage instead of merging them: both rows survive, the successor is
relabeled from "new" to repost/duplicate, and aging accrues across the lineage.

Layers:
- ``normalize``  — pure title normalization (match-grade key + display-grade).
- ``score``      — pure decision tree over a candidate pair -> Verdict.
- ``project``    — pure union-find over links -> per-job lineage projection.
- ``detect``     — DB half: fetch pgvector candidates, persist links.
"""
