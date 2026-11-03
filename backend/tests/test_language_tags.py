import pytest
from pydantic import ValidationError

from tracker.api.schemas.locale import LocaleSettings
from tracker.platform.language_tags import is_locale_tag


@pytest.mark.parametrize("tag", ["en", "en-US", "zh-Hant-TW", "es-419", "en-u-nu-latn", "de-1996"])
def test_valid_intl_tags(tag):
    assert is_locale_tag(tag)
    assert LocaleSettings(language=tag).language == tag

@pytest.mark.parametrize("tag", ["en-12-34", "en-US-US", "en-u", "en-u-ca-gregory-u-nu-latn", "de-1996-1996", "en_US", "", "en-123456789"])
def test_invalid_tags_never_reach_formatters(tag):
    assert not is_locale_tag(tag)
    with pytest.raises(ValidationError):
        LocaleSettings(language="en", region=tag)
