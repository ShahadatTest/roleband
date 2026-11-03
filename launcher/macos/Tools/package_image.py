import argparse
import hashlib
import importlib.metadata
import os
import plistlib
import re
import subprocess
import tempfile
from pathlib import Path

from install_guide import GUIDE_NAME, LANGUAGES, messages, write_guide

ROOT = Path(__file__).resolve().parents[1]

WINDOW = ((160, 120), (760, 680))


def layout(app, background, guide_path, languages):
    return {
        "format": "UDZO", "filesystem": "HFS+", "compression_level": 9,
        "files": [str(app), (str(guide_path), GUIDE_NAME), (str(languages), ".guide")],
        "symlinks": {"Applications": "/Applications"},
        "background": str(background), "window_rect": WINDOW,
        "icon": str(app / "Contents/Resources/RoleBandLauncher.icns"),
        "default_view": "icon-view", "icon_size": 96, "text_size": 13,
        "label_pos": "bottom", "arrange_by": None,
        "grid_spacing": 96,
        "show_status_bar": False, "show_toolbar": False, "show_sidebar": False,
        "show_tab_view": False, "show_pathbar": False,
        "hide_extensions": [GUIDE_NAME],
        "icon_locations": {app.name: (200, 335), "Applications": (560, 335), GUIDE_NAME: (108, 126)},
    }


def check_tools():
    for line in (ROOT / "packaging-requirements.txt").read_text().splitlines():
        package, pinned = line.split(" --hash=", 1)[0].split("==")
        actual = importlib.metadata.version(package)
        if actual != pinned:
            raise RuntimeError(f"Expected {package} {pinned}, found {actual}")


def same_quarantine(source, copied):
    # macOS can normalize the timestamp and agent fields during a file copy.
    before, after = source.strip().split(b";"), copied.strip().split(b";")
    if len(before) < 3 or len(after) < 3 or int(before[0], 16) != int(after[0], 16):
        return False
    return len(before) < 4 or not before[3] or (len(after) >= 4 and before[3] == after[3])


def verify_quarantine(source, copied):
    def read(path):
        result = subprocess.run(["xattr", "-p", "com.apple.quarantine", str(path)], capture_output=True, check=False)
        return result.stdout if result.returncode == 0 else b""
    original = read(source)
    if original and not same_quarantine(original, read(copied)):
        raise ValueError("Image did not preserve the app's quarantine")


def writable_copy(source, destination):
    # shutil copies no extended attributes on macOS; ditto keeps them, quarantine among them.
    subprocess.run(["ditto", str(source), str(destination)], check=True)
    # ditto restores metadata through symlinks while copying into the image.
    for path in [destination, *destination.rglob('*')]:
        mode = path.lstat().st_mode
        if not mode & 0o200:
            path.chmod(mode | 0o200, follow_symlinks=False)


def verify_app_copy(source, copied):
    def inventory(root):
        result = {}
        for path in root.rglob('*'):
            relative = str(path.relative_to(root))
            if path.is_symlink():
                result[relative] = ('link', str(path.readlink()))
            elif path.is_file():
                result[relative] = ('file', hashlib.sha256(path.read_bytes()).hexdigest())
            else:
                result[relative] = ('directory',)
        return result

    if inventory(source) != inventory(copied):
        raise ValueError('The image changed app files or symbolic links')


def verify_image(image, source):
    from ds_store import DSStore
    from mac_alias import Alias

    with tempfile.TemporaryDirectory(prefix="roleband-image-check-") as directory:
        volume = Path(directory) / "volume"
        subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(volume),
                        str(image)], check=True, stdout=subprocess.DEVNULL)
        try:
            app = volume / source.name
            subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
            expected = plistlib.loads((source / "Contents/Info.plist").read_bytes())
            actual = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            if actual != expected or not (volume / "Applications").is_symlink():
                raise ValueError("Image has a different app identity or no Applications shortcut")
            verify_app_copy(source, app)
            if (volume / "Applications").readlink() != Path("/Applications"):
                raise ValueError("Applications shortcut has an unexpected target")
            verify_quarantine(source, app)
            for filename in [GUIDE_NAME, *[f".guide/{locale}.html" for locale in LANGUAGES],
                             ".guide/guide.js", ".guide/guide.css", ".guide/warning.png", ".guide/security.png", ".guide/radar.svg"]:
                if not (volume / filename).is_file():
                    raise ValueError(f"Missing installer guide: {filename}")
            volume_icon = volume / ".VolumeIcon.icns"
            if not volume_icon.is_file() or volume_icon.read_bytes() != (source / "Contents/Resources/RoleBandLauncher.icns").read_bytes():
                raise ValueError("Image does not wear the app's icon")
            with DSStore.open(str(volume / ".DS_Store"), "r") as store:
                bounds = store["."]["bwsp"]["WindowBounds"]
                _, _, width, height = [float(value) for value in re.findall(r"-?[\d.]+", bounds)]
                view = store["."]["icvp"]
                size = view["iconSize"]
                app_point, folder_point = store[source.name]["Iloc"], store["Applications"]["Iloc"]
                if not app_point[0] < folder_point[0] or app_point[1] != folder_point[1]:
                    raise ValueError("Image does not present an app-to-Applications drag")
                for filename in [source.name, "Applications", GUIDE_NAME]:
                    x, y = store[filename]["Iloc"]
                    if not size / 2 <= x <= width - size / 2 or not size / 2 <= y <= height - size / 2:
                        raise ValueError(f"Icon outside installer window: {filename}")
                background = Alias.from_bytes(view["backgroundImageAlias"]).target.filename
                if not (volume / background).is_file():
                    raise ValueError("Installer background cannot be resolved")
        finally:
            subprocess.run(["hdiutil", "detach", str(volume)], check=True, stdout=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--language", choices=LANGUAGES, default="en")
    args = parser.parse_args()
    app, output = args.app.resolve(), args.output.absolute()
    if not (app / "Contents/MacOS/RoleBandLauncher").is_file() or output.exists():
        parser.error("Provide an assembled launcher and a new output path")
    check_tools()
    import dmgbuild

    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    with tempfile.TemporaryDirectory(prefix="roleband-dmg-", dir=output.parent) as temporary:
        staging = Path(temporary)
        copied_app = staging / app.name
        writable_copy(app, copied_app)
        _, catalog = messages(args.language)
        guide_path, languages = write_guide(staging, args.language, for_image=True)
        subprocess.run(["swift", str(ROOT / "Tools/InstallerBackground.swift"), str(staging), str(catalog)], check=True)
        image = staging / "installer.dmg"
        dmgbuild.build_dmg(str(image), "RoleBand Launcher", settings=layout(copied_app, staging / "installer.png", guide_path, languages))
        subprocess.run(["hdiutil", "verify", str(image)], check=True)
        verify_image(image, app)
        os.link(image, output)
    print(output)


if __name__ == "__main__":
    main()
