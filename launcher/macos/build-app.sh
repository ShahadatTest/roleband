#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LAUNCHER_ROOT/../.." && pwd)"
BUILD_ROOT="${ROLEBAND_LAUNCHER_BUILD_ROOT:-$LAUNCHER_ROOT/.build}"
CONFIGURATION="${ROLEBAND_LAUNCHER_CONFIGURATION:-release}"
APP_PATH="${ROLEBAND_LAUNCHER_APP_PATH:-$BUILD_ROOT/RoleBand Launcher.app}"
if [ -n "${ROLEBAND_LAUNCHER_DEMO_RELEASE_FILE:-}" ] && [ -z "${ROLEBAND_LAUNCHER_REGISTRATION:-}" ]; then
  echo "A demo release feed requires a preview registration." >&2
  exit 1
fi
if [ -e "$APP_PATH" ]; then
  echo "Refusing to replace an existing app: $APP_PATH" >&2
  exit 1
fi
# Assembled beside the target and moved into place last, so a failed build leaves nothing that
# blocks the next attempt.
mkdir -p "$(dirname "$APP_PATH")"
STAGE_DIR="$(mktemp -d "$(dirname "$APP_PATH")/.partial.XXXXXX")"
trap 'rm -rf "$STAGE_DIR"' EXIT
STAGE="$STAGE_DIR/$(basename "$APP_PATH")"
swift build --package-path "$LAUNCHER_ROOT" --scratch-path "$BUILD_ROOT" --configuration "$CONFIGURATION" --product RoleBandLauncher
BINARY_DIR="$(swift build --package-path "$LAUNCHER_ROOT" --scratch-path "$BUILD_ROOT" --configuration "$CONFIGURATION" --show-bin-path)"
mkdir -p "$STAGE/Contents/MacOS" "$STAGE/Contents/Resources"
cp "$LAUNCHER_ROOT/Resources/LauncherInfo.plist" "$STAGE/Contents/Info.plist"
cp "$BINARY_DIR/RoleBandLauncher" "$STAGE/Contents/MacOS/RoleBandLauncher"
cp -R "$BINARY_DIR/RoleBandLauncher_LauncherCore.bundle" "$STAGE/Contents/Resources/"
VERSION="$(plutil -extract version raw -o - "$REPO_ROOT/dashboard/package.json")"
VERSION_CORE="${VERSION%%[-+]*}"
plutil -insert RoleBandVersion -string "$VERSION" "$STAGE/Contents/Info.plist"
plutil -insert CFBundleShortVersionString -string "$VERSION_CORE" "$STAGE/Contents/Info.plist"
plutil -insert CFBundleVersion -string "$VERSION_CORE" "$STAGE/Contents/Info.plist"
# A source download has no git history: its revision is unknown and counted as dirty, which
# release.py refuses, so only a build from a clean checkout can become a release asset.
if REVISION="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null)"; then
  SOURCE_STATE="$(git -C "$REPO_ROOT" status --porcelain --untracked-files=normal)"
else
  REVISION=unknown
  SOURCE_STATE=unknown
fi
plutil -insert RoleBandSourceRevision -string "$REVISION" "$STAGE/Contents/Info.plist"
if [ -n "$SOURCE_STATE" ]; then
  plutil -insert RoleBandSourceDirty -bool YES "$STAGE/Contents/Info.plist"
else
  plutil -insert RoleBandSourceDirty -bool NO "$STAGE/Contents/Info.plist"
fi
if [ -n "${ROLEBAND_LAUNCHER_BUNDLE_ID:-}" ]; then
  plutil -replace CFBundleIdentifier -string "$ROLEBAND_LAUNCHER_BUNDLE_ID" "$STAGE/Contents/Info.plist"
fi
if [ -n "${ROLEBAND_LAUNCHER_DISPLAY_NAME:-}" ]; then
  plutil -replace CFBundleDisplayName -string "$ROLEBAND_LAUNCHER_DISPLAY_NAME" "$STAGE/Contents/Info.plist"
  plutil -replace CFBundleName -string "$ROLEBAND_LAUNCHER_DISPLAY_NAME" "$STAGE/Contents/Info.plist"
fi
if [ -n "${ROLEBAND_LAUNCHER_REGISTRATION:-}" ]; then
  plutil -insert RoleBandRegistration -string "$ROLEBAND_LAUNCHER_REGISTRATION" "$STAGE/Contents/Info.plist"
  plutil -insert RoleBandPreview -bool YES "$STAGE/Contents/Info.plist"
fi
if [ -n "${ROLEBAND_LAUNCHER_DEMO_RELEASE_FILE:-}" ]; then
  plutil -insert RoleBandDemoReleaseFile -string "$ROLEBAND_LAUNCHER_DEMO_RELEASE_FILE" "$STAGE/Contents/Info.plist"
fi
ICONSET="$STAGE/Contents/Resources/RoleBandLauncher.iconset"
swift "$LAUNCHER_ROOT/Tools/Icon.swift" "$ICONSET"
iconutil -c icns "$ICONSET" -o "$STAGE/Contents/Resources/RoleBandLauncher.icns"
rm -r "$ICONSET"
codesign --force --sign - "$STAGE"
codesign --verify --strict "$STAGE"
mv "$STAGE" "$APP_PATH"
printf '%s\n' "$APP_PATH"
