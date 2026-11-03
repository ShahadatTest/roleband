"""A crash leaves as its type and our frames, nothing else (docs/architecture.md).

The canary sits where real crashes carry the user's data: the message (a scrape
error names the company), an argument, a local variable, a chained cause's
message, and a path under the home directory. None of it may survive.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracker.usage_stats import scrub
from tracker.usage_stats.registry import FAMILY_KINDS

pytestmark = pytest.mark.usefixtures("no_escape")

CANARY = "zyxwv-robotics"


class BoardError(RuntimeError):
    pass


def _raise_from_ours() -> None:
    secret_company = CANARY  # noqa: F841 - a local variable a reporter could capture
    try:
        json.loads(f"{{'company': '{CANARY}'}}")  # a third-party frame (json) with data
    except ValueError as cause:
        raise BoardError(f"board for {CANARY} at {Path.home()}/x answered 404", CANARY) from cause


def _caught() -> BaseException:
    try:
        _raise_from_ours()
    except BoardError as exc:
        return exc
    raise AssertionError("unreachable")


def test_no_message_argument_local_or_path_survives() -> None:
    shape = scrub.scrub(_caught())
    stored = json.dumps(scrub.to_props(shape))
    sent = json.dumps(scrub.exception_list(shape))
    for text in (stored, sent):
        assert CANARY not in text
        assert str(Path.home()) not in text
        assert "/Users/" not in text and "404" not in text


def test_shape_keeps_the_type_our_frames_and_the_chain() -> None:
    shape = scrub.scrub(_caught())
    assert shape.type == f"{__name__}.BoardError"
    # Only frames in `tracker` are kept; this test module is not tracker code,
    # and json's frames are third-party: none survive here.
    assert shape.frames == ()
    assert shape.chain == ("json.decoder.JSONDecodeError",)


def test_tracker_frames_are_kept_as_module_function_line() -> None:
    from tracker.usage_stats.registry import validate

    try:
        validate("not_an_event", {})
    except ValueError as exc:
        shape = scrub.scrub(exc)
    assert shape.type == "tracker.usage_stats.registry.UsageEventError"
    assert [(f.module, f.function) for f in shape.frames] == [
        ("tracker.usage_stats.registry", "validate"),
        ("tracker.usage_stats.registry", "event"),
    ]
    assert all(f.lineno > 0 for f in shape.frames)
    entry = scrub.exception_list(shape)[0]
    assert "value" not in entry
    assert entry["stacktrace"]["frames"][-1]["filename"] == "tracker/usage_stats/registry.py"


def test_the_same_crash_has_the_same_fingerprint() -> None:
    assert scrub.scrub(_caught()).fingerprint() == scrub.scrub(_caught()).fingerprint()
    assert scrub.scrub(_caught()).fingerprint() != scrub.scrub(KeyError("x")).fingerprint()


def test_a_stored_shape_with_anything_extra_is_refused() -> None:
    stored = scrub.to_props(scrub.scrub(_caught()))
    assert scrub.validate_stored(stored).type.endswith("BoardError")
    for bad in (
        stored | {"message": CANARY},
        stored | {"type": f"Board error at {CANARY}"},
        stored | {"frames": [["/Users/someone/x.py", "f", 1]]},
        stored | {"frames": [["tracker.x", f"{CANARY} f", 1]]},
        stored | {"chain": [f"{CANARY} happened"]},
    ):
        with pytest.raises(ValueError):
            scrub.validate_stored(bad)


def _crash_in(module: str, function: str) -> BaseException:
    """An exception whose innermost frame claims `module`/`function`, as a crash
    inside that file would."""
    source = f"def {function}():\n    raise RuntimeError('{CANARY}')\n"
    namespace: dict = {"__name__": module}
    exec(compile(source, f"/Users/someone/RoleBand/backend/{module.replace('.', '/')}.py", "exec"), namespace)  # noqa: S102
    try:
        namespace[function]()
    except RuntimeError as exc:
        return exc
    raise AssertionError("unreachable")


def test_a_frame_in_one_employers_connector_loses_its_name() -> None:
    shape = scrub.scrub(_crash_in("tracker.connectors.listing.amazon", "_parse_amazon_page"))
    assert [(f.module, f.function) for f in shape.frames] == [
        ("tracker.connectors.listing.single_company", "single_company")
    ]
    assert "amazon" not in json.dumps(scrub.exception_list(shape))


def test_a_job_site_family_keeps_its_name() -> None:
    shape = scrub.scrub(_crash_in("tracker.connectors.listing.greenhouse", "fetch_page"))
    assert [(f.module, f.function) for f in shape.frames] == [("tracker.connectors.listing.greenhouse", "fetch_page")]


def test_a_function_named_for_an_employer_elsewhere_loses_its_name() -> None:
    shape = scrub.scrub(_crash_in("tracker.taxonomy.stated_level", "_google_rung"))
    assert [(f.module, f.function) for f in shape.frames] == [("tracker.taxonomy.stated_level", "single_company")]


def _company_error(module: str, name: str) -> type[Exception]:
    return type(name, (Exception,), {"__module__": module})


def test_an_exception_class_from_one_employers_connector_loses_its_name() -> None:
    """A class a company connector defines names the employer as the crash's
    type and in its chain, wherever it is raised."""
    blocked = _company_error("tracker.connectors.listing.amazon", "AmazonBlocked")
    try:
        try:
            raise blocked("refused")
        except Exception as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        chained = scrub.scrub(outer)
    try:
        raise blocked("refused")
    except Exception as exc:
        raised = scrub.scrub(exc)

    assert raised.type == "tracker.connectors.listing.single_company.single_company"
    assert chained.chain == ("tracker.connectors.listing.single_company.single_company",)
    for shape in (raised, chained):
        sent = json.dumps(scrub.exception_list(shape)).lower()
        assert "amazon" not in sent
        scrub.validate_stored(scrub.to_props(shape))


def test_an_exception_named_for_an_employer_elsewhere_loses_its_name() -> None:
    try:
        raise _company_error("tracker.taxonomy.stated_level", "GoogleRungMissing")("x")
    except Exception as exc:
        shape = scrub.scrub(exc)
    assert shape.type == "tracker.taxonomy.stated_level.single_company"


def test_an_exception_of_a_job_site_family_keeps_its_name() -> None:
    try:
        raise _company_error("tracker.connectors.listing.greenhouse", "GreenhouseBoardGone")("x")
    except Exception as exc:
        shape = scrub.scrub(exc)
    assert shape.type == "tracker.connectors.listing.greenhouse.GreenhouseBoardGone"


def test_every_company_connector_is_a_company_word() -> None:
    connectors = Path(scrub.__file__).resolve().parents[1] / "connectors"
    for kind in ("listing", "detail"):
        for path in (connectors / kind).glob("*.py"):
            if path.stem in {"__init__", "base", "recipe_adapter", "sitemap_board"} or path.stem in FAMILY_KINDS:
                continue
            assert path.stem in scrub.COMPANY_WORDS, path.stem
