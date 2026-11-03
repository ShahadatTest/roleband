import html.parser
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import package_image
from install_guide import LANGUAGES, SECURITY_URL, guide, messages, write_guide
from package_image import same_quarantine


class GuidePage(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.scripts = 0
        self.language = None
        self.images = []
        self.icons = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.links.append(attrs["href"])
        if tag == "script":
            self.scripts += 1
        if tag == "html":
            self.language = attrs.get("lang")
        if tag == "img":
            self.images.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "icon":
            self.icons.append(attrs["href"])


class VisibleText(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside_script = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        self.inside_script = self.inside_script or tag == "script"

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside_script = False

    def handle_data(self, data):
        if not self.inside_script and data.strip():
            self.parts.append(data.strip())


# The packaged app brings its own engine, so nothing a new person reads before first open may
# send them to install one or call the app a launcher.
SOURCE_INSTALL_WORDS = {"en": ["launcher", "engine"], "es": ["lanzador", "motor"], "zh-Hans": ["启动器", "引擎"]}


class InstallerGuideTests(unittest.TestCase):
    def test_nothing_read_before_first_open_describes_a_source_install(self):
        drawn = re.findall(r'messages\["([a-z-]+)"\]', (Path(__file__).parent / "InstallerBackground.swift").read_text())
        self.assertIn("guide-drag-caption", drawn)
        for locale, words in SOURCE_INSTALL_WORDS.items():
            copy, _ = messages(locale)
            parser = VisibleText()
            parser.feed(guide(copy, locale))
            texts = parser.parts + [copy[key] for key in drawn]
            self.assertTrue(any("Applications" in text for text in texts))
            for text in texts:
                for word in words:
                    self.assertNotIn(word, text.lower(), f"{locale}: {text}")

    def test_readonly_app_is_staged_writable_with_symlinks_and_source_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.app'
            (source / 'Contents/python/bin').mkdir(parents=True)
            binary = source / 'Contents/python/bin/python3.12'
            binary.write_bytes(b'native executable')
            (binary.parent / 'python3').symlink_to('python3.12')
            if hasattr(os, 'lchmod'):
                os.lchmod(binary.parent / 'python3', 0o555)
            for path in [*source.rglob('*'), source]:
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode & ~0o222)
            target = Path(directory) / 'staged.app'
            package_image.writable_copy(source, target)
            self.assertFalse(binary.stat().st_mode & 0o200)
            self.assertTrue((target / 'Contents/python/bin/python3.12').stat().st_mode & 0o200)
            self.assertTrue((target / 'Contents/python/bin/python3').lstat().st_mode & 0o200)
            self.assertEqual(os.readlink(target / 'Contents/python/bin/python3'), 'python3.12')
            package_image.verify_app_copy(source, target)

    def test_image_verification_rejects_changed_python_files_and_missing_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.app'
            source.mkdir()
            (source / 'module.py').write_text('engine code')
            (source / 'python3').symlink_to('module.py')
            target = Path(directory) / 'image.app'
            package_image.writable_copy(source, target)
            (target / 'module.py').write_text('changed code')
            with self.assertRaises(ValueError):
                package_image.verify_app_copy(source, target)
            (target / 'module.py').write_text('engine code')
            (target / 'python3').unlink()
            with self.assertRaises(ValueError):
                package_image.verify_app_copy(source, target)

    def test_a_downloaded_app_keeps_its_quarantine_in_the_staged_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.app'
            (source / 'Contents/MacOS').mkdir(parents=True)
            (source / 'Contents/MacOS/RoleBandLauncher').write_bytes(b'native executable')
            quarantine = '0081;6ae15da9;RoleBand Install Trial;fixture-event'
            subprocess.run(['xattr', '-w', 'com.apple.quarantine', quarantine, str(source)], check=True)
            for path in [*source.rglob('*'), source]:
                path.chmod(path.stat().st_mode & ~0o222)
            target = Path(directory) / 'staged.app'
            package_image.writable_copy(source, target)
            package_image.verify_quarantine(source, target)
            subprocess.run(['xattr', '-d', 'com.apple.quarantine', str(target)], check=True)
            with self.assertRaises(ValueError):
                package_image.verify_quarantine(source, target)
            plain = Path(directory) / 'plain.app'
            (plain / 'Contents').mkdir(parents=True)
            package_image.verify_quarantine(plain, target)

    def test_file_copy_normalization_keeps_quarantine_flags_and_event_identity(self):
        original = b"0081;6ae15da9;RoleBand Install Trial;fixture-event\n"
        self.assertTrue(same_quarantine(original, b"0081;00000000;;fixture-event\n"))
        self.assertFalse(same_quarantine(original, b"0000;00000000;;fixture-event\n"))
        self.assertFalse(same_quarantine(original, b"0081;00000000;;other-event\n"))
        self.assertFalse(same_quarantine(original, b""))

    def test_the_first_step_says_the_app_needs_apple_silicon_before_anyone_copies_it(self):
        for locale in LANGUAGES:
            copy, _ = messages(locale)
            first_step = guide(copy, locale).split('data-step="open"')[0]
            parser = VisibleText()
            parser.feed(first_step)
            self.assertIn(copy["guide-requirements"], parser.parts, locale)
            self.assertIn("Intel", copy["guide-requirements"], locale)

    def test_every_guide_has_working_language_links_and_prelaunch_security_help(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry, assets = write_guide(root, "es", for_image=True)
            for page, locale in [(entry, "es"), *[(assets / f"{code}.html", code) for code in LANGUAGES]]:
                parser = GuidePage()
                parser.feed(page.read_text())
                self.assertEqual(parser.language, locale)
                self.assertEqual(parser.scripts, 2)
                self.assertIn(SECURITY_URL, parser.links)
                self.assertEqual([Path(icon).name for icon in parser.icons], ["radar.svg"])
                for link in parser.links + parser.images + parser.icons:
                    if ":" not in link and not link.startswith("#"):
                        self.assertTrue((page.parent / link).is_file(), link)

    def test_translated_text_cannot_inject_html_or_replace_the_document_language(self):
        copy, _ = messages("en")
        copy["guide-title"] = '<script>alert("unexpected")</script>'
        parser = GuidePage()
        page = guide(copy, "en")
        parser.feed(page)
        self.assertEqual(parser.scripts, 2)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn('<script>alert("unexpected")</script>', page)

    def test_download_export_has_all_assets_and_refuses_to_overwrite_a_guide(self):
        with tempfile.TemporaryDirectory() as directory:
            entry, assets = write_guide(directory, "zh-Hans")
            self.assertEqual(entry.name, "index.html")
            for name in ["guide.js", "guide.css", "warning.png", "security.png", "radar.svg"]:
                self.assertTrue((assets / name).is_file())
            with self.assertRaises(FileExistsError):
                write_guide(directory)

    def test_the_image_wears_the_app_icon(self):
        app = Path("/staging/RoleBand.app")
        settings = package_image.layout(app, Path("/staging/installer.png"), Path("/staging/guide.html"), Path("/staging/.guide"))
        self.assertEqual(settings["icon"], str(app / "Contents/Resources/RoleBandLauncher.icns"))

    def test_unknown_languages_are_refused(self):
        with self.assertRaises(ValueError):
            messages("../outside")


if __name__ == "__main__":
    unittest.main()
