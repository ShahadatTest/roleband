"""Smart-search layer: natural-language parsing + optional LLM understanding.

`parse.parse_query` turns free text into structured filters plus a semantic
remainder, using the same taxonomy the rest of the app relies on. `llm.llm_parse`
is an optional, off-by-default enhancement that defers to the local parser on any
failure. The ranked orders themselves live in `best_match.py`
(`relevance_search`: RRF over lexical + semantic + fuzzy candidates;
`intent_ranking`: the queryless order by the standing intent vector).
"""
