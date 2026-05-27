#!/usr/bin/env bash
# Build script for phoenix_mobile APK.
# Uses dart snapshot directly to bypass flutter.bat issues with
# CJK usernames in paths (batch variable expansion of %E5%90%B4%E5%90%8D).
set -e

export PUB_HOSTED_URL=https://pub.flutter-io.cn
export FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn
export PUB_CACHE="${PUB_CACHE:-C:/pub-cache}"
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-C:/gradle-cache}"
export FLUTTER_ROOT="${FLUTTER_ROOT:-E:/flutter}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${BUILD_DIR:-d:/phx-build}"

echo "=== phoenix_mobile APK Builder ==="
echo "Source: $SCRIPT_DIR"
echo "Build:  $BUILD_DIR"
echo ""

# Step 1: sync source to ASCII-path build directory
SRC_WIN="$(cygpath -w "$SCRIPT_DIR")"
DEST_WIN="$(cygpath -w "$BUILD_DIR")"
echo ">>> Syncing source to $BUILD_DIR ..."
echo "  $SRC_WIN  ->  $DEST_WIN"
mkdir -p "$BUILD_DIR"
robocopy "$SRC_WIN" "$DEST_WIN" //MIR \
  //XD build .dart_tool .idea .gradle \
  //XF "*.iml" \
  //NJH //NJS //NDL //NP //NS //NC > /dev/null 2>&1 || true

cp "$SCRIPT_DIR/.metadata" "$BUILD_DIR/.metadata" 2>/dev/null || true

FLUTTER_DART="$FLUTTER_ROOT/bin/cache/dart-sdk/bin/dart.exe"
FLUTTER_SNAPSHOT="$FLUTTER_ROOT/bin/cache/flutter_tools.snapshot"

# Step 2: pub get
echo ""
echo ">>> flutter pub get..."
cd "$BUILD_DIR"
"$FLUTTER_DART" "$FLUTTER_SNAPSHOT" pub get

# Step 3: build APK
echo ""
echo ">>> flutter build apk --debug..."
"$FLUTTER_DART" "$FLUTTER_SNAPSHOT" build apk --debug

# Step 4: install on connected device (if any)
echo ""
echo ">>> Checking for connected device..."
APK_PATH="$BUILD_DIR/build/app/outputs/flutter-apk/app-debug.apk"
if adb devices 2>/dev/null | grep -q "device$"; then
  echo ">>> Installing APK on phone..."
  adb install -r "$APK_PATH" 2>/dev/null && \
    echo ">>> Install successful!" || \
    echo ">>> Install failed (maybe no device or adb not found)"
else
  echo ">>> No device connected. APK ready at:"
fi

echo ""
echo "=== Done ==="
echo "APK: $APK_PATH"
