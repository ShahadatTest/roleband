#!/usr/bin/env bash
set -euo pipefail

LAUNCHER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLCHAIN_BIN="$(dirname "$(xcrun --find swiftc)")"
TESTING_PLUGIN="$TOOLCHAIN_BIN/../lib/swift/host/plugins/testing/libTestingMacros.dylib"
TEST_OPTIONS=(--disable-xctest)
if [ -f "$TESTING_PLUGIN" ]; then
  TEST_OPTIONS+=(-Xswiftc -load-plugin-library -Xswiftc "$TESTING_PLUGIN")
fi
exec swift test --package-path "$LAUNCHER_ROOT" "${TEST_OPTIONS[@]}" "$@"
