from tracker.lineage.content_diff import compare_descriptions, normalize_department


def _sections(content: str):
    return [{"key": "basic_qualifications", "title": "Basic Qualifications", "content": content}]


def test_cosmetic_bullets_case_and_reordering_are_equivalent():
    diff = compare_descriptions(
        _sections("- Build secure systems\n- 5+ years experience"),
        None,
        _sections("• 5+ YEARS EXPERIENCE\n* Build secure systems"),
        None,
    )

    assert diff.comparable is True
    assert diff.equivalent is True
    assert diff.shared_count == 2
    assert diff.left_only_count == diff.right_only_count == 0


def test_changed_number_is_preserved_as_difference():
    diff = compare_descriptions(
        _sections("- 5+ years experience\n- Security certification"),
        None,
        _sections("- 7+ years experience\n- Security certification"),
        None,
    )

    assert diff.equivalent is False
    assert diff.shared_count == 1
    assert diff.left_only[0].text == "- 5+ years experience"
    assert diff.right_only[0].text == "- 7+ years experience"
    assert 0 < diff.token_similarity < 1


def test_duplicate_passages_use_multiset_counts():
    diff = compare_descriptions(
        _sections("- Same\n- Same"), None, _sections("- Same"), None
    )
    assert diff.shared_count == 1
    assert diff.left_only_count == 1
    assert diff.right_only_count == 0


def test_missing_side_is_not_comparable():
    diff = compare_descriptions([], None, _sections("- Present"), None)
    assert diff.comparable is False
    assert diff.equivalent is False


def test_department_normalization_is_case_and_whitespace_insensitive():
    assert normalize_department("  AWS   Security ") == "aws security"
    assert normalize_department(None) is None
