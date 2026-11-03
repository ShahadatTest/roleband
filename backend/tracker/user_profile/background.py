"""The fields a profile claim records.

`profile_claims` holds facts about the candidate, one row per fact, superseded
rather than edited. The inference pass reads the active `experience` rows
(`workflows/profile_inference_pass.py`); nothing in the app writes them.
"""

from __future__ import annotations

EXPERIENCE = "experience"
