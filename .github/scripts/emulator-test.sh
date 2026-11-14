#!/usr/bin/env bash
# RdxGram emulator launch test — runs INSIDE the android-emulator-runner
# `script` step, so it must be a real file: the runner executes the
# `script` input line by line in separate shells, so shell variables
# assigned in one line do NOT survive to the next (run 43587905951
# proved it: TAG was empty in the `gh release download` line).
#
# Usage: emulator-test.sh <release-tag>
# Writes status.txt / logcat.txt / screen.png in the current directory.
# Always exits 0: an app crash (or install failure) is a TEST RESULT,
# not a CI failure — verdict lives in status.txt.

TAG="${1:-instagram-451.0.0.53.80-rdxgram-theme-1.0}"
PKG="com.instagram.android"

echo "apk_tag=$TAG"
mkdir -p apk
if ! gh release download "$TAG" -p 'Instagram-*.apk' --repo "$GITHUB_REPOSITORY" --dir apk; then
  echo "DOWNLOAD_FAILED" > status.txt
  echo "tag=$TAG" >> status.txt
  echo "reason=gh release download failed for tag $TAG" >> status.txt
  adb logcat -d > logcat.txt 2>/dev/null || true
  adb exec-out screencap -p > screen.png 2>/dev/null || true
  echo "DOWNLOAD FAILED — see status.txt"
  exit 0
fi
ls -la apk
APK=$(ls apk/Instagram-*.apk 2>/dev/null | head -n1)
if [ -z "$APK" ]; then
  echo "DOWNLOAD_FAILED" > status.txt
  echo "tag=$TAG" >> status.txt
  echo "reason=no Instagram-*.apk asset in release $TAG" >> status.txt
  adb logcat -d > logcat.txt 2>/dev/null || true
  exit 0
fi
echo "apk=$APK size=$(stat -c%s "$APK")"

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
echo "apk=$(basename "$APK")" >> status.txt
echo "apk_size=$(stat -c%s "$APK")" >> status.txt
echo "checked_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> status.txt
adb shell dumpsys package "$PKG" 2>/dev/null | grep -iE "versionName|versionCode|firstInstallTime" >> status.txt || true
adb logcat -d > logcat.txt 2>/dev/null || true
adb exec-out screencap -p > screen.png 2>/dev/null || true
echo "verdict: $(head -n1 status.txt)"
exit 0
