#!/usr/bin/env bash
# RdxGram emulator launch test — runs INSIDE the android-emulator-runner
# `script` step, so it must be a real file: the runner executes the
# `script` input line by line in separate shells, so shell variables
# assigned in one line do NOT survive to the next (run 43587905951
# proved it: TAG was empty in the `gh release download` line).
#
# The APK is downloaded by a normal workflow step BEFORE the emulator
# starts (gh works fine there); this script only installs the file that
# is already in apk/. It does NOT download anything itself — `gh release
# download` inside the runner's script shell failed with "release not
# found" in run 43588243927 even though the tag exists.
#
# Usage: emulator-test.sh <release-tag>
# Writes status.txt / logcat.txt / screen.png in the current directory.
# Always exits 0: an app crash (or install failure) is a TEST RESULT,
# not a CI failure — verdict lives in status.txt.

TAG="${1:-instagram-451.0.0.53.80-rdxgram-theme-1.1}"

echo "apk_tag=$TAG"
ls -la apk 2>/dev/null || true
APK=$(ls apk/Instagram-*.apk 2>/dev/null | head -n1)
if [ -z "$APK" ]; then
  echo "DOWNLOAD_FAILED" > status.txt
  echo "tag=$TAG" >> status.txt
  echo "reason=no Instagram-*.apk file in apk/ (download step did not produce one)" >> status.txt
  adb logcat -d > logcat.txt 2>/dev/null || true
  adb exec-out screencap -p > screen.png 2>/dev/null || true
  echo "DOWNLOAD FAILED — see status.txt"
  exit 0
fi
echo "apk=$APK size=$(stat -c%s "$APK")"

# The APK's package is NOT always com.instagram.android: the side-by-side
# build is com.rdx.gram. The test script used to hardcode
# com.instagram.android, so run 43596343821 monkeyed a package that was
# never installed ("** No activities found to run, monkey aborted") and
# the pidof check then wrote a bogus CRASHED verdict for an app that was
# never launched. Derive the package from the APK's own manifest
# (verify_apk_manifest.py is checked out with this repo and reads LSPatch
# output fine); fall back to the theme package if the parse fails.
PKG="com.instagram.android"
DETECTED=$(python3 .github/scripts/verify_apk_manifest.py "$APK" 2>/dev/null | sed -n 's/^package=\([^ ]*\).*/\1/p')
if [ -n "$DETECTED" ]; then
  PKG="$DETECTED"
fi
echo "package=$PKG (from APK manifest)"

# Clear the log so the dump is mostly about this launch.
adb logcat -c 2>/dev/null || true

if ! adb install -r -g "$APK"; then
  echo "INSTALL_FAILED" > status.txt
  echo "tag=$TAG" >> status.txt
  echo "apk=$(basename "$APK")" >> status.txt
  adb logcat -d > logcat.txt 2>/dev/null || true
  adb exec-out screencap -p > screen.png 2>/dev/null || true
  echo "INSTALL FAILED — see logcat.txt"
  exit 0
fi

# Open the app the way a launcher tap would.
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 2>/dev/null || true
sleep 45

if adb shell pidof "$PKG" >/dev/null 2>&1; then
  echo "ALIVE" > status.txt
else
  echo "CRASHED" > status.txt
fi
echo "tag=$TAG" >> status.txt
echo "package=$PKG" >> status.txt
echo "apk=$(basename "$APK")" >> status.txt
echo "apk_size=$(stat -c%s "$APK")" >> status.txt
echo "checked_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> status.txt
adb shell dumpsys package "$PKG" 2>/dev/null | grep -iE "versionName|versionCode|firstInstallTime" >> status.txt || true
adb logcat -d > logcat.txt 2>/dev/null || true
adb exec-out screencap -p > screen.png 2>/dev/null || true
echo "verdict: $(head -n1 status.txt)"
exit 0
