import argparse
import os
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path

IDENTIFIER = "com.roleband.launcher"


def validate(app):
    if app.is_symlink() or not app.is_dir() or app.stat().st_uid != os.getuid():
        raise ValueError("Expected an app directory owned by the current user")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != IDENTIFIER or info.get("CFBundleExecutable") != "RoleBandLauncher":
        raise ValueError("This app is not the RoleBand launcher; it was left untouched")
    if "RoleBandRegistration" in info or "RoleBandDemoReleaseFile" in info or info.get("RoleBandPreview"):
        raise ValueError("A preview bound to a test engine cannot replace the installed launcher")
    subprocess.run(["codesign", "--verify", "--strict", str(app)], check=True)


def running(app):
    binary = str(app.resolve() / "Contents/MacOS/RoleBandLauncher")
    commands = subprocess.check_output(["/bin/ps", "-axo", "comm="], text=True)
    return binary in (line.strip() for line in commands.splitlines())


def install(source, destination):
    validate(source)
    parent = destination.parent
    if parent.is_symlink() or destination.is_symlink():
        raise ValueError("The installation path is a symbolic link; use Finder to install the app")
    parent.mkdir(parents=True, exist_ok=True)
    if parent.stat().st_uid != os.getuid():
        raise ValueError("The Applications folder is not owned by the current user")
    exists = destination.exists()
    original = destination.stat() if exists else None
    if exists:
        validate(destination)
        if running(destination):
            raise ValueError("Quit the installed RoleBand launcher, then run this installer again")
    directory = Path(tempfile.mkdtemp(prefix=".roleband-install-", dir=parent))
    backup = directory / "previous.app"
    published = False
    try:
        staging = directory / destination.name
        subprocess.run(["ditto", str(source), str(staging)], check=True)
        validate(staging)
        # A copy or signature check can take time; recheck before replacing the app.
        if destination.exists() != exists or destination.is_symlink():
            raise ValueError("The installed app changed during the build; try again")
        if exists:
            current = destination.stat()
            if (current.st_dev, current.st_ino, current.st_mtime_ns) != (original.st_dev, original.st_ino, original.st_mtime_ns):
                raise ValueError("The installed app changed during the build; try again")
            validate(destination)
            if running(destination):
                raise ValueError("Quit the installed RoleBand launcher, then run this installer again")
            destination.rename(backup)
        try:
            staging.rename(destination)
            published = True
        except BaseException:
            if backup.exists():
                try:
                    backup.rename(destination)
                except OSError as error:
                    raise RuntimeError(f"The previous launcher is preserved at {backup}") from error
            raise
    finally:
        if published or not backup.exists():
            shutil.rmtree(directory)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    if os.uname().sysname != "Darwin":
        parser.error("The launcher installs on macOS only")
    destination = Path.home() / "Applications/RoleBand Launcher.app"
    try:
        install(args.app, destination)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Launcher installation failed: {error}\n")
    print(f"Launcher installed: {destination}\nOpen it in Finder to begin setup. Start at login stays optional.")


if __name__ == "__main__":
    main()
