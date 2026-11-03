"""The generic content fingerprint that embeddings + disclosed-comp gate on."""

from __future__ import annotations

from tracker.content import content_fingerprint


def test_fingerprint_is_stable_and_sensitive():
    a = content_fingerprint("Staff Engineer", "Build distributed systems.")
    b = content_fingerprint("Staff Engineer", "Build distributed systems.")
    c = content_fingerprint("Staff Engineer", "Build ML systems.")
    d = content_fingerprint("Senior Engineer", "Build distributed systems.")
    assert a == b
    assert a != c  # description change moves the hash
    assert a != d  # title change moves the hash


def test_fingerprint_handles_none():
    assert content_fingerprint(None, None) == content_fingerprint("", "")
