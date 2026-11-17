#!/usr/bin/env python3
"""RdxGram 1.8 login probe — log in with a REAL Instagram account inside
the app on Redroid and reach the home feed.

Runs on the GitHub Actions arm runner AFTER the boot step installed and
launched the APK. Credentials arrive via environment (repo secrets) and are
NEVER printed, logged, or stored in any output file. If the password is
wrong, it stops at WRONG_PASSWORD. Only ONE login submit is ever attempted.

Verification code: if Instagram asks for a 6-digit code after the login
submit, the driver WAITS for it instead of stopping. The code comes from
one of two sources, in this order:
  1. IG_CODE — repo secret IG_LOGIN_CODE, set before the run starts.
     (A code issued by an earlier login is bound to that login, so in
     practice this only works if the code is already in hand at dispatch.)
  2. IG_CODE_URL — repo secret IG_CODE_URL, a one-time mailbox file the
     operator writes while the run waits; the driver polls it every 15 s
     for up to CODE_WAIT_SEC (default 600 s) until the body is exactly
     6 digits. This is the path that works for the real flow: the fresh
     login in this run triggers a fresh code, the operator reads it from
     the mailbox and writes it to the file.
At most TWO code attempts: if no code arrives, the driver waits once more
and then ends with CODE_TIMEOUT; if an entered code is rejected, it waits
once more for a fresh code and then ends with CODE_REJECTED. The code
value itself is never logged, printed, or written to any output file.

After a successful login the driver lets the feed settle a few seconds,
then runs the capsule-fix acceptance sequence: 8 tab taps
home -> reels -> direct -> profile -> home -> reels -> direct -> home,
with a screenshot AND a UI dump after EVERY tap. (The 1.10/1.11 probes
only did feed -> explore -> profile -> feed, so the suspected trigger
tabs reels/direct were never visited and the fix stayed unproven.)
If a tab is not found the driver re-dumps in place and relaunches if
the app left the foreground — it NEVER presses BACK on the feed,
because BACK exits the app to the launcher and poisons every later
screenshot (1.13 probe: all 8 tab shots were the launcher).
1.15: if a first-run promo sheet ("Introducing instants") covers the
tab bar mid-sequence, the driver dismisses it with its exact "Not
now" secondary action and retries the tab once (the 1.14 probe's
tabs 4-8 died on that sheet).
Finally it checks the log for FATAL crashes (CRASHED_AFTER_FEED if any
appear).

1.17 re-probe: after login the feed's top item auto-opened a
full-screen reel viewer (no tab bar by design) and the driver had no
way back — it misread the viewer as the add-photo interstitial
("Profile picture of <author>" in the reel header) and died on
STUCK_PHOTO. The viewer is now a first-class screen (REEL_VIEWER):
BACK (on-screen Back button first, then the BACK key) returns to the
feed, verified by a fresh dump, at most 3 attempts. BACK is still
never pressed on the feed itself.
The same run exposed a worse bug in dump(): a failed uiautomator run
left the previous /sdcard/ui.xml in place, so the driver acted on a
STALE dump — the notification dialog looked present for 4 steps while
it was already gone, and the blind re-taps landed on the feed and
opened the reel. dump() now deletes the old file (device + local)
before every attempt, validates the XML, and returns None instead of
a stale file; the main loop waits and retries the step instead of
acting. The notification dialog is now dismissed with verification
(tap, settle 5 s, fresh dump) and at most 2 taps.

1.17 re-probe 3: after tap 2 (Reels) EVERY dump() returned None —
uiautomator times out while the reels video SurfaceView is active —
so find_tab could never see the bar again even though every
screenshot showed it healthy with all 5 icons, and the old tap loop
burned ~4 min per failed tap (2 in-place re-dumps + a sheet dismissal
that was not there + a futile relaunch, each failing dump ~40 s).
The tap loop now has a dump-failure path: tap the wanted tab at its
LAST-KNOWN coordinates (remember_tabs, from the last dump that had
the bar), and if dumps still fail press the BACK key EXACTLY ONCE
to leave the Reels tab for the feed; each tap is capped at
TAP_BUDGET_SEC so a failure can never burn 4 min again. The relaunch
path is gated on a SUCCEEDED dump showing the app is gone —
app_foreground([]) is False, but that means "no dump", not "left
the app". The drag test falls back to the last-known Home/Reels
centers the same way, and reports DRAG_UNKNOWN_DUMP_FAILED (with
the mid/after screenshots as evidence) when the after-dump cannot
confirm the switch, instead of silently skipping.

1.17.1 probe: after SAVE_LOGIN Instagram showed a first-run
"Set up on new device" location-services onboarding (no Skip /
Not now — only a "Continue" button) instead of the feed, and the
driver had no handler for it, so it died on UNKNOWN_SCREEN at
step 4. The screen is now a first-class screen
(ONBOARDING_LOCATION): BACK first (it may skip the onboarding
without granting location), then Continue + DENY the Android
system location dialog ("Don't allow", verified — never "While
using the app" / "Only this time"). Both steps are verified with
fresh dumps, at most 2 attempts, and a relaunch after BACK is
gated on a SUCCEEDED dump showing the app is gone (the same rule
as the tap loop — never a blind relaunch).

After a successful login Android may also show the system
notification-permission dialog ("Allow Rdx gram to send you
notifications?"). The driver dismisses it with "Don't allow" so it can
reach the feed instead of ending on UNKNOWN_SCREEN.

1.17.1 re-probe: the drag DID switch the tab (Home 23:21:28 ->
Reels viewer 23:21:36, Reels highlighted) — the first time a drag
ever switched — but the verdict stayed DRAG_UNKNOWN_DUMP_FAILED:
no lens was seen in the mid-shot, the after-dump failed (reels
SurfaceView), and logcat-final.txt had ZERO RdxGramTheme lines
(the final capture ran ~44 s after the drag; reels log spam evicted
the drag lines from the ring buffer). Three verification gaps, all
driver-side, fixed in #4: (1) the switch is now also confirmed from
the after-SCREENSHOT itself (the Reels viewer has a dark capsule +
dark top strip, vs the light Home feed — measured on the real shots
from the 1.15 + 1.17.1 re-probe runs, no false positive on any
Home/Direct/Profile shot); a late re-dump after the SurfaceView
settles is tried first, and DRAG_UNKNOWN_DUMP_FAILED is kept only
when neither the dump nor the screenshot confirms the switch (or
the no-switch). NOTE — the dump alone cannot prove a Reels switch:
measured on the real dumps, a post-Reels-tap dump keeps Home
selected=true and usually has no "Reel by" text at +3 s (1.15
tab02after/tab06after, 1.17.1 re-probe has no tab02after at all),
so a Home-selected dump does NOT prove no-switch either; the
screenshot is the primary switch evidence and the dump only fires
when Reels is selected or viewer text is present. (2) TWO
mid-shots (~40% and ~70% through the swipe) and the lens is
measured by pixel comparison against the tab-8 reference shot
(the glass lens darkens the capsule ~17-29 units where it sits;
the negative controls — 1.15 with no drag hook, 1.17 re-probe 4
with the broken overlay — darken by exactly 0). (3) logcat is
snapshotted IMMEDIATELY after the drag test (logcat-drag.txt)
before the ~40 s dump-retry loop, so the drag RdxLog.d lines
survive; the existing final capture in finish() is untouched.

Outputs (working dir): status.json, status.txt, timeline.txt, ui_step*.xml,
shot_*.png, logcat-final.txt, crash-final.txt.
Exit code is always 0 — the verdict lives in status.json/status.txt.
"""
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zlib

SER = os.environ.get("ANDROID_SERIAL", "localhost:5555")
PKG = os.environ["PKG"]
USER = os.environ["IG_USER"]
PASS = os.environ["IG_PASS"]
# Verification-code sources (see module docstring). IG_CODE is the repo
# secret IG_LOGIN_CODE, fixed when the step starts; IG_CODE_URL is the
# repo secret IG_CODE_URL, polled while the run waits on the code screen.
IG_CODE = os.environ.get("IG_CODE", "").strip()
IG_CODE_URL = os.environ.get("IG_CODE_URL", "").strip()
CODE_WAIT_SEC = int(os.environ.get("CODE_WAIT_SEC", "600"))
_CODE_USED = False  # the IG_CODE secret value is single-use per run
DEADLINE = time.time() + int(os.environ.get("DEADLINE_SEC", "1440"))
STATUS = {"status": "STARTED", "cold_start_total_ms": None, "fatal_count": 0,
          "steps": 0, "screenshots": [], "started_at": int(time.time()),
          "finished_at": None, "last_screen": None, "detail": "",
          "code_destination_masked": None, "code_attempts": 0,
          "code_source": None}
# Bottom-bar tab descs, and their centers from the last dump that had
# them (see remember_tabs). 1.17 re-probe 3: dumps fail while the
# reels video SurfaceView is active, so the last-known centers are
# the only way to keep tapping when find_tab can no longer see the bar.
TAB_DESCS = ("Home", "Reels", "Message", "Search and explore", "Profile")
LAST_TABS = {}  # desc -> (x, y)
# Name of the last tab actually tapped in the 8-tap sequence (None
# before tap 1). The dump-failure BACK below is only safe when the
# previous tap was Reels: BACK from the Reels tab returns to the
# feed, but BACK on the home feed would exit the app to the launcher.
LAST_TAP_NAME = None
# Per-tap time cap in the 8-tap sequence (re-probe 3: one failed tap
# burned ~4 min). No new expensive step starts once it is spent.
TAP_BUDGET_SEC = 120

# Drag-test timing (fix #4). The swipe runs DRAG_SWIPE_MS on-device,
# but it only starts after the adb round-trip (~0.2-0.6 s), and each
# screencap costs another adb round-trip (~0.3-0.5 s), so a single
# mid-shot is a gamble on adb latency: the 1.17.1 re-probe's only
# mid-shot (0.48 s after Popen) caught the lens only faintly — the
# pixel profile shows the glass darkening (~29 early / ~17 late units
# vs the tab-8 reference shot) but at 1x it looked like a plain Home
# feed, so the lens was judged "not seen". Two mid-shots bracket the
# gesture instead (early ~40%, late ~70%), and the lens is now also
# measured by pixel comparison (see detect_lens_in_shots), not just
# eyeballed. The after-shot stays at the same ~3.48 s after Popen as
# before (0.48 + 3.0), so the tab has the same time to settle.
DRAG_SWIPE_MS = 1200
DRAG_MID1_S = 0.48   # ~40% through the swipe
DRAG_MID2_S = 0.84   # ~70% through the swipe (0.36 s after mid1)
DRAG_AFTER_S = 3.48  # after-shot, same total as the old 0.48 + 3.0

# Transition-burst test (1.19, capsule flash). A page switch takes
# ~200-400 ms; a flat frame can last a single frame, so the burst is
# 4 shots as fast as screencap allows (~0.12 s sleeps, each shot
# costs another ~0.3-0.5 s adb round-trip). The burst alone can miss
# a 1-frame flash — the primary evidence is the pre-draw guard's
# logcat lines ("capsule re-applied in pre-draw", counted live after
# the bursts); the burst shots catch a longer flash (guard broken
# and the flat frame surviving until the 400 ms sweep) and are
# eyeballed by the monitor either way.
TRANS_BURST_SHOTS = 4
TRANS_BURST_INTERVAL_S = 0.12


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open("timeline.txt", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def save_status():
    STATUS["finished_at"] = int(time.time())
    with open("status.json", "w", encoding="utf-8") as fh:
        json.dump(STATUS, fh, indent=2, ensure_ascii=False)
    with open("status.txt", "w", encoding="utf-8") as fh:
        fh.write(STATUS["status"] + "\n")


def adb(*args, timeout=60):
    cmd = ["adb", "-s", SER] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "adb timeout", 1


def shell(*args, timeout=60):
    return adb("shell", *args, timeout=timeout)


def tap(x, y):
    shell("input", "tap", str(x), str(y))
    time.sleep(1)


def keyevent(code):
    shell("input", "keyevent", str(code))
    time.sleep(0.5)


def dismiss_keyboard():
    keyevent(111)  # KEYCODE_ESCAPE


def maybe_hide_keyboard(nodes):
    """If an EditText is focused the soft keyboard is up and it covers the
    lower buttons: a tap meant for a button lands on a keyboard key
    instead (seen in run 43679452461: 58 taps on 'Sign up with email'
    typed 58 '2's into the phone field). Hide it with BACK (which only
    dismisses the keyboard while one is shown) and re-dump.
    Returns fresh nodes (or the original ones if nothing was hidden)."""
    focused = [n for n in nodes
               if n["cls"].endswith("EditText")
               and n.get("focused") == "true"]
    # parse_dump drops the focused attr; re-check via a fresh attribute read
    if not focused:
        return nodes, False
    log("keyboard is up (focused field); hiding it with BACK")
    keyevent(4)
    time.sleep(1.5)
    path = dump(f"step{STATUS['steps']:02d}k")
    fresh = parse_dump(path)
    return fresh, True


def type_text(s):
    # spaces must be %s for `input text`; other chars go through as-is
    arg = s.replace(" ", "%s")
    shell("input", "text", arg)
    time.sleep(1)


def clear_field(center):
    tap(*center)
    for _ in range(30):
        shell("input", "keyevent", "67")
    time.sleep(0.5)


def dump(name):
    """Dump the UI hierarchy to ui_<name>.xml and return its path.

    1.17 re-probe lesson: a failed `uiautomator dump` leaves the
    PREVIOUS /sdcard/ui.xml in place, and the old code pulled that
    stale file and acted on it as if it were fresh — the
    notification dialog looked present for 4 steps while it was
    already gone, and the blind re-taps landed on the feed and
    opened a reel. So the old file is deleted (device AND local)
    before EVERY attempt, the pulled XML is validated, and a total
    failure returns None instead of a stale file. Callers must
    handle None (the main loop waits and retries the step)."""
    path = f"ui_{name}.xml"
    for _ in range(3):
        if os.path.exists(path):
            os.remove(path)
        shell("rm", "/sdcard/ui.xml")
        shell("uiautomator", "dump", "/sdcard/ui.xml")
        out, _, _ = adb("pull", "/sdcard/ui.xml", path)
        if os.path.exists(path) and os.path.getsize(path) > 100:
            try:
                ET.parse(path)
            except Exception:
                os.remove(path)
                time.sleep(2)
                continue
            return path
        time.sleep(2)
    return None


def parse_dump(path):
    """Return list of nodes: dicts with text/desc/class/clickable/bounds."""
    nodes = []
    if not path or not os.path.exists(path):
        return nodes
    try:
        tree = ET.parse(path)
    except Exception:
        return nodes
    for n in tree.iter("node"):
        b = n.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
        center = ((int(m.group(1)) + int(m.group(3))) // 2,
                  (int(m.group(2)) + int(m.group(4))) // 2) if m else None
        nodes.append({
            "text": n.get("text") or "",
            "desc": n.get("content-desc") or "",
            "cls": n.get("class") or "",
            "clickable": n.get("clickable") == "true",
            "selected": n.get("selected") == "true",
            "bounds": b,
            "center": center,
            "resource": n.get("resource-id") or "",
            "focused": n.get("focused") or "",
        })
    return nodes


def all_text(nodes):
    return " | ".join((n["text"] + " " + n["desc"]).strip()
                      for n in nodes if n["text"] or n["desc"])


def low(nodes):
    return all_text(nodes).lower()


def find(nodes, *patterns, clickable_only=False):
    """First node whose text or desc contains any pattern (case-insensitive).
    Prefer clickable nodes, then any node."""
    best = None
    for n in nodes:
        hay = (n["text"] + " " + n["desc"]).lower()
        if any(p.lower() in hay for p in patterns):
            if n["center"] is None:
                continue
            if n["clickable"]:
                return n
            if best is None:
                best = n
    return best


def find_exact(nodes, *labels):
    """Clickable node whose text or desc is EXACTLY one of the labels
    (case-insensitive). Avoids matching 'Log in with Facebook' when the
    submit button 'Log in' is wanted."""
    for n in nodes:
        if not n["clickable"] or n["center"] is None:
            continue
        for lab in labels:
            if n["text"].strip().lower() == lab.lower():
                return n
            if n["desc"].strip().lower() == lab.lower():
                return n
    return None


def find_tab(nodes, desc):
    """Bottom-nav tab by EXACT content-desc, restricted to the bottom bar.

    The tab bar in the 1.11 probe dumps is five clickable FrameLayouts at
    y 1072-1168 of a 1280-high screen, descs Home / Reels / Message /
    Search and explore / Profile. Exact-desc matching avoids content nodes
    like "Reel by ..." and the bottom-bar check avoids feed content.
    Returns the node or None."""
    h = 0
    for n in nodes:
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n["bounds"])
        if m:
            h = max(h, int(m.group(4)))
    bar_top = 0.8 * h if h else 0
    for n in nodes:
        if not n["clickable"] or n["center"] is None:
            continue
        if n["desc"].strip() == desc and n["center"][1] >= bar_top:
            return n
    return None


def remember_tabs(nodes):
    """Remember the bottom-bar tab centers from a dump that has them.

    Re-probe 3: after tap 2 (Reels) every uiautomator dump returned
    None while the reels video SurfaceView was active, so find_tab
    could never see the bar again — even though every screenshot
    showed it healthy with all 5 icons. The last-known centers are
    the fallback: tapping them navigates off the Reels tab to a
    static screen where dumps work again. Only real, clickable,
    bottom-bar tabs are remembered (find_tab's exact-desc + bar
    check), and only from dumps that actually have them — an
    empty-bar dump (1.13/1.16 regression) remembers nothing, and a
    failed dump (nodes == []) remembers nothing either."""
    for desc in TAB_DESCS:
        node = find_tab(nodes, desc)
        if node:
            LAST_TABS[desc] = node["center"]


def app_foreground(nodes):
    """True if any node in the dump belongs to our app package.

    Tells a genuinely missing tab bar (we are in the app, the bar has
    no tabs — a real app failure, as in the 1.13 probe) from having
    left the app entirely (launcher/home screen — a driver failure,
    not an app failure)."""
    return any((n.get("resource") or "").startswith(
        ("com.rdx.gram", "com.instagram")) for n in nodes)


def dismiss_sheet(nodes, tag):
    """Dismiss a first-run promo sheet covering the tab bar (e.g. the
    "Introducing instants" dialog from the 1.14 probe) by tapping its
    exact "Not now" secondary action. Only that label is ever matched
    — never "Try it" or any primary action — and the feed itself has
    no clickable "Not now" node (suggested cards say "Dismiss"), so
    the match is safe on a healthy feed. Returns fresh nodes after a
    dismissal, or None if no sheet was found."""
    btn = find_exact(nodes, "Not now")
    if not btn:
        return None
    log(f"first-run sheet present; dismissing with 'Not now' "
        f"({btn['resource'] or 'no resource-id'})")
    tap(*btn["center"])
    time.sleep(2)
    STATUS.setdefault("sheets_dismissed", []).append("Not now")
    save_status()
    return parse_dump(dump(tag))


def find_back_button(nodes):
    """Top-left Back affordance of a full-screen viewer.

    The reels viewer (1.17 re-probe ui_step08.xml) has a clickable
    ImageView with content-desc "Back" at [0,66][96,160], center
    (48,113). Restricted to the top-left corner so a "Back" node
    elsewhere (a caption, a button label) never matches."""
    for n in nodes:
        if not n["clickable"] or n["center"] is None:
            continue
        if n["desc"].strip().lower() == "back":
            x, y = n["center"]
            if x <= 120 and y <= 200:
                return n
    return None


def exit_viewer(tag, screen="REEL_VIEWER"):
    """Leave a full-screen reel/photo viewer and get back to the feed.

    The viewer hides the tab bar by design, so the only way back is
    BACK: tap the on-screen Back button first, fall back to the BACK
    key. Every attempt is verified with a fresh dump — BACK is NEVER
    pressed on the feed itself (that would exit the app to the
    launcher). At most 3 attempts. Returns (state, nodes): ("FEED",
    nodes) on success, otherwise the last classified state and its
    nodes. A success is recorded in status.json (viewer_recoveries)."""
    nodes = []
    state = None
    for attempt in (1, 2, 3):
        nodes = parse_dump(dump(f"{tag}b{attempt}"))
        state = classify(nodes)
        if state == "FEED":
            break
        btn = find_back_button(nodes)
        if btn:
            log(f"viewer recovery: tapping Back button "
                f"(attempt {attempt}/3)")
            tap(*btn["center"])
        else:
            log(f"viewer recovery: no Back button; BACK key "
                f"(attempt {attempt}/3)")
            keyevent(4)
        time.sleep(3)
        nodes = parse_dump(dump(f"{tag}b{attempt}after"))
        state = classify(nodes)
        if state == "FEED":
            STATUS.setdefault("viewer_recoveries", []).append(
                {"screen": screen, "tag": tag, "attempts": attempt})
            save_status()
            log(f"viewer recovery: back on FEED after {attempt} "
                f"attempt(s)")
            break
        log(f"viewer recovery: still {state} after attempt {attempt}/3")
    return state, nodes


def dismiss_notif(nodes, tag):
    """Dismiss the system notification-permission dialog, VERIFIED.

    1.17 re-probe lesson: the driver tapped "Don't allow" four times
    while the dialog (or a stale dump of it) kept showing, and the
    blind re-taps landed on the feed and opened a reel. The dialog
    itself dismisses fine with one tap (1.15 probe) — the bug was
    tapping without verifying. So: tap at most twice, settle 5 s,
    and check a FRESH dump before tapping again. Returns
    (state, nodes) after dismissal, or (None, nodes) if the dialog
    is still up after 2 verified taps."""
    for attempt in (1, 2):
        btn = find_exact(nodes, "Don't allow", "Don’t allow") or \
            find(nodes, "Don't allow")
        if not btn:
            return None, nodes
        log(f"notification-permission dialog; tapping Don't allow "
            f"(attempt {attempt}/2, verified)")
        tap(*btn["center"])
        time.sleep(5)
        nodes = parse_dump(dump(f"{tag}n{attempt}"))
        state = classify(nodes)
        if state != "NOTIF_DIALOG":
            log(f"notification dialog dismissed after {attempt} "
                f"tap(s); now on {state}")
            return state, nodes
        log(f"notification dialog still present after tap "
            f"{attempt}/2; verifying with a fresh dump before retrying")
    return None, nodes


def dismiss_location_permission(nodes, tag):
    """Deny the Android system location-permission dialog, VERIFIED.

    Same pattern as dismiss_notif (tap, settle, fresh dump, at most
    2 taps) — never tap "While using the app" or "Only this time":
    the probe must not grant location. Returns (state, nodes) after
    denial, or (None, nodes) if the dialog is still up after 2
    verified taps."""
    for attempt in (1, 2):
        btn = find_exact(nodes, "Don't allow", "Don’t allow") or \
            find(nodes, "Don't allow")
        if not btn:
            return None, nodes
        log(f"location-permission dialog; tapping Don't allow "
            f"(attempt {attempt}/2, verified)")
        tap(*btn["center"])
        time.sleep(5)
        nodes = parse_dump(dump(f"{tag}n{attempt}"))
        state = classify(nodes)
        if state != "LOCATION_PERMISSION":
            log(f"location dialog denied after {attempt} "
                f"tap(s); now on {state}")
            return state, nodes
        log(f"location dialog still present after tap "
            f"{attempt}/2; verifying with a fresh dump before retrying")
    return None, nodes


def exit_onboarding_location(nodes, tag):
    """Leave the first-run "Set up on new device" location
    onboarding and get to the feed (or whatever Instagram shows
    next).

    1.17.1 probe: Instagram showed this screen after SAVE_LOGIN
    instead of the feed, and the driver had no handler for it — it
    died on UNKNOWN_SCREEN at step 4. The screen has no Skip /
    Not now affordance; its only clickable node is "Continue"
    (which triggers the Android location-permission dialog).
    Recovery order, max 2 attempts:
      (a) BACK key first — it may skip the onboarding WITHOUT
          granting location. Verified with a fresh dump.
      (b) If still on the onboarding, tap "Continue" and DENY the
          system location dialog ("Don't allow", verified — never
          "While using the app" / "Only this time"). Verified with
          a fresh dump.
    If BACK leaves the app entirely (launcher), the relaunch is
    gated on a SUCCEEDED dump showing the app is gone — the same
    rule as the tap loop — never a blind relaunch. BACK is never
    pressed on the feed itself: this handler only runs while the
    current screen IS the onboarding, and every press is verified
    by a fresh dump before the next one.
    Returns (state, nodes): the fresh classified state after
    recovery, or ("ONBOARDING_LOCATION", nodes) if still stuck.
    A success is recorded in status.json (onboarding_recoveries)."""
    state = "ONBOARDING_LOCATION"
    # Attempt 1: BACK — skip without granting location.
    log("location onboarding; BACK key first (attempt 1/2)")
    keyevent(4)
    time.sleep(3)
    nodes = parse_dump(dump(f"{tag}b1"))
    if nodes:
        state = classify(nodes)
        if state != "ONBOARDING_LOCATION" and not app_foreground(nodes):
            # BACK left the app (launcher): relaunch once, gated on
            # this SUCCEEDED dump.
            log("BACK left the app; relaunching once")
            relaunch()
            time.sleep(5)
            nodes = parse_dump(dump(f"{tag}re"))
            if nodes:
                state = classify(nodes)
        if state != "ONBOARDING_LOCATION":
            STATUS.setdefault("onboarding_recoveries", []).append(
                {"screen": "ONBOARDING_LOCATION", "tag": tag,
                 "method": "back", "attempts": 1})
            save_status()
            log(f"onboarding cleared by BACK; now on {state}")
            return state, nodes
    else:
        # No fresh hierarchy after BACK: wait and re-dump once
        # instead of acting blindly.
        log("no UI dump after BACK on onboarding; waiting and "
            "re-dumping once")
        time.sleep(3)
        nodes = parse_dump(dump(f"{tag}b1r"))
        if nodes:
            state = classify(nodes)
            if state != "ONBOARDING_LOCATION":
                STATUS.setdefault("onboarding_recoveries", []).append(
                    {"screen": "ONBOARDING_LOCATION", "tag": tag,
                     "method": "back", "attempts": 1})
                save_status()
                log(f"onboarding cleared by BACK; now on {state}")
                return state, nodes
    # Attempt 2: Continue, then DENY the system location dialog.
    log("onboarding still up after BACK; tapping Continue "
        "(attempt 2/2)")
    btn = find_exact(nodes, "Continue") if nodes else None
    if not btn:
        log("onboarding has no Continue button; giving up")
        return "ONBOARDING_LOCATION", nodes
    tap(*btn["center"])
    time.sleep(3)
    nodes = parse_dump(dump(f"{tag}c2"))
    state = classify(nodes) if nodes else "ONBOARDING_LOCATION"
    saw_perm = False
    if state == "LOCATION_PERMISSION":
        saw_perm = True
        new_state, nodes = dismiss_location_permission(nodes,
                                                      f"{tag}perm")
        if new_state is not None:
            state = new_state
    if nodes and state != "ONBOARDING_LOCATION":
        STATUS.setdefault("onboarding_recoveries", []).append(
            {"screen": "ONBOARDING_LOCATION", "tag": tag,
             "method": "continue+deny" if saw_perm else "continue",
             "attempts": 2})
        save_status()
        log(f"onboarding cleared by Continue + deny; now on {state}")
        return state, nodes
    log("onboarding still up after Continue + deny")
    return "ONBOARDING_LOCATION", nodes


def find_edit(nodes, *desc_prefixes):
    for n in nodes:
        if n["cls"].endswith("EditText"):
            if not desc_prefixes:
                return n
            if any(n["desc"].lower().startswith(p.lower())
                   for p in desc_prefixes):
                return n
    return None


def edits(nodes):
    return [n for n in nodes if n["cls"].endswith("EditText")]


def screenshot(name):
    shell("screencap", "-p", f"/sdcard/{name}.png")
    out, _, _ = adb("pull", f"/sdcard/{name}.png", f"{name}.png")
    if os.path.exists(f"{name}.png"):
        STATUS["screenshots"].append(f"{name}.png")
        log(f"screenshot saved: {name}.png")
        return True
    log(f"screenshot FAILED: {name}.png")
    return False


def pid_alive():
    out, _, _ = shell("pidof", PKG)
    return bool(out and out != "not-running")


def logcat_fatal_count():
    out, _, _ = adb("logcat", "-d", timeout=90)
    return out.count("FATAL EXCEPTION"), out


def check_alive(context):
    if not pid_alive():
        log(f"process DEAD after {context}")
        return False
    count, _ = logcat_fatal_count()
    if count > STATUS["fatal_count"]:
        STATUS["fatal_count"] = count
        log(f"FATAL EXCEPTION seen in logcat after {context} (count={count})")
        return False
    return True


def cold_start_ms():
    try:
        with open("launch.txt", encoding="utf-8", errors="replace") as fh:
            m = re.search(r"TotalTime:\s*(\d+)", fh.read())
            if m:
                return int(m.group(1))
    except OSError:
        pass
    return None


def relaunch():
    log("relaunching app")
    out, _, _ = shell("cmd", "package", "resolve-activity", "--brief",
                      "-a", "android.intent.action.MAIN",
                      "-c", "android.intent.category.LAUNCHER", PKG)
    launcher = out.strip().splitlines()[-1] if out.strip() else ""
    if launcher and "/" in launcher:
        shell("am", "start", "-W", "-a", "android.intent.action.MAIN",
              "-c", "android.intent.category.LAUNCHER", "-n", launcher)
    else:
        shell("am", "start", "-W", "-a", "android.intent.action.MAIN",
              "-c", "android.intent.category.LAUNCHER", PKG)
    time.sleep(20)


def extract_code_destination(nodes):
    """The code screen shows the destination already masked by Instagram
    (e.g. h••••@gmail.com, +98 ••• ••• 4426). Return that masked fragment
    (or the 'sent' sentence) — never anything unmasked."""
    text = all_text(nodes)
    m = re.search(r"\S+@\S+", text)
    if m:
        return m.group(0)
    m = re.search(r"\+\d[\d\s•*]{6,}", text)
    if m:
        return m.group(0).strip()
    m = re.search(r"(we sent[^|]{0,120}|sent a code[^|]{0,120})",
                  text, re.I)
    if m:
        return m.group(0).strip()
    return text[:200]


def fetch_code(timeout_sec):
    """Poll IG_CODE_URL until the body is exactly 6 digits, or time out.

    The body is NEVER logged or stored — only its presence (6 digits) is
    reported. Returns the code string, or None on timeout / deadline.
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if time.time() > DEADLINE:
            return None
        try:
            req = urllib.request.Request(IG_CODE_URL, headers={
                "User-Agent": "rdxgram-login-probe/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", "replace").strip()
            if re.fullmatch(r"\d{6}", body):
                log("confirmation code arrived at mailbox (6 digits)")
                return body
        except Exception as e:
            log(f"code poll: {type(e).__name__} (retrying)")
        time.sleep(15)
    return None


def obtain_code():
    """Get one 6-digit code, or None if none arrives in CODE_WAIT_SEC.

    Source order: the IG_CODE env value (repo secret IG_LOGIN_CODE) first
    — single-use, only if it was set before the run started; otherwise
    poll IG_CODE_URL (repo secret IG_CODE_URL, a one-time mailbox file the
    operator writes after the fresh login triggers a fresh code).
    The code value itself is never logged. Returns (code, source).
    """
    global _CODE_USED
    if IG_CODE and not _CODE_USED:
        _CODE_USED = True
        if re.fullmatch(r"\d{6}", IG_CODE):
            log("using confirmation code from IG_CODE secret")
            return IG_CODE, "secret"
        log("IG_CODE secret is set but is not 6 digits; ignoring it")
    if IG_CODE_URL:
        code = fetch_code(CODE_WAIT_SEC)
        if code:
            return code, "url"
        return None, None
    return None, None


def enter_code(nodes, code):
    """Type a 6-digit code on the code screen and submit it.

    Handles both layouts: a single code field (the one seen in run
    43706519687), or six one-digit boxes. Returns the screen state after
    submitting (re-dumped + classified). The code value is never logged.
    """
    eds = edits(nodes)
    if not eds:
        log("code screen has no input field")
        return "CODE"
    if len(eds) >= 6:
        # Six one-digit boxes: one digit per box.
        for i, digit in enumerate(code[:6]):
            box = eds[i]
            tap(*box["center"])
            type_text(digit)
    else:
        field = eds[0]
        clear_field(field["center"])
        type_text(code)
    log("code entered (6 digits, not shown); hiding keyboard")
    dismiss_keyboard()
    time.sleep(1)
    nodes_sub = parse_dump(dump(f"step{STATUS['steps']:02d}c"))
    btn = find_exact(nodes_sub, "Continue", "Confirm", "Verify")
    if not btn:
        btn = find(nodes_sub, "Continue", "Confirm", "Verify", "Next")
    if not btn:
        log("no Continue/Confirm button on code screen")
        return "CODE"
    log("tapping code submit button")
    tap(*btn["center"])
    time.sleep(10)
    nodes_after = parse_dump(dump(f"step{STATUS['steps']:02d}d"))
    return classify(nodes_after)


def classify(nodes):
    t = low(nodes)
    descs = " ".join(n["desc"].lower() for n in nodes)
    # Wrong-password dialog sits ON TOP of the login form — check first.
    if any(k in t for k in ("incorrect password",
                            "password you've entered is incorrect",
                            "the password you entered is incorrect",
                            "wrong password")):
        return "WRONG_PASSWORD"
    # First-run "Set up on new device" location onboarding (1.17.1
    # probe): shown after SAVE_LOGIN instead of the feed. Checked
    # FIRST (before FEED/NOTIF) — the screen is unmistakable and
    # must never be mistaken for the feed or the notification
    # dialog.
    if "set up on new device" in t:
        return "ONBOARDING_LOCATION"
    # Android system location-permission dialog (appears after
    # tapping Continue on the onboarding): "Allow Rdx gram to access
    # this device's location?" with While using the app / Only this
    # time / Don't allow. Checked after ONBOARDING_LOCATION on
    # purpose — the onboarding screen itself says "access your
    # location", which must not match here.
    if ("access this device's location" in t
            or "while using the app" in t):
        return "LOCATION_PERMISSION"
    # System notification-permission dialog can overlay the feed, so
    # it must win over the FEED nav check below.
    if "send you notifications" in t:
        return "NOTIF_DIALOG"
    nav_hits = sum(1 for k in ("home", "search and explore", "reels",
                               "notifications", "profile")
                   if k in descs or k in t)
    if nav_hits >= 3 or "your story" in t:
        return "FEED"
    # Full-screen reel viewer (1.17 re-probe): the feed's top item can
    # auto-open it right after login. It hides the tab bar by design,
    # so nav_hits stays low (header "Reels" + "Profile picture of
    # <author>" = 2 at most) and FEED above does not fire. Checked
    # AFTER FEED on purpose: a healthy feed never contains "Reel by",
    # and a viewer must never be mistaken for the feed.
    if any(k in t for k in ("reel by", "double tap to play or pause")):
        return "REEL_VIEWER"
    if any(k in t for k in (
            "suspicious", "checkpoint", "confirm it's you",
            "we need to confirm", "verify your account",
            "unusual login", "help us confirm",
            "is this your phone number",
            "verify with a code", "add your phone number to",
            "temporarily locked", "account locked")):
        return "CHALLENGE"
    if any(k in t for k in ("confirmation code", "enter the code",
                            "enter code", "6-digit", "verification code",
                            "enter the 6-digit code",
                            "we sent a code", "sent a code to",
                            "get a code", "two-factor")):
        return "CODE"
    # Login form BEFORE any single-field state: it has BOTH fields.
    if find_edit(nodes, "Username") and find_edit(nodes, "Password"):
        return "LOGIN_FORM"
    if len(edits(nodes)) >= 2:
        return "LOGIN_FORM"
    if "save your login info" in t or "save login info" in t:
        return "SAVE_LOGIN"
    if any(k in t for k in ("create new account", "get started",
                            "join instagram", "i already have a profile")):
        return "LANDING"
    if any(k in t for k in ("find people", "discover people",
                            "follow people to see")):
        return "FIND_PEOPLE"
    if any(k in t for k in ("turn on notifications", "allow notifications",
                            "enable notifications", "sync your contacts",
                            "find your friends", "add to home screen")):
        return "INTERSTITIAL"
    if any(k in t for k in ("profile photo", "profile picture",
                            "add a photo")):
        # A reel/photo viewer header also says "Profile picture of
        # <author>" — that is NOT the add-photo interstitial (1.17
        # re-probe: the viewer was misread as PHOTO and died on
        # STUCK_PHOTO). Only call it PHOTO when it really asks to add
        # one, or offers a Skip/Not-now affordance, which the viewer
        # never does.
        if ("add a photo" in t or "add a profile photo" in t
                or find_exact(nodes, "Skip", "Not now",
                              "Maybe later")):
            return "PHOTO"
    if any(k in t for k in ("we limit how often", "try again later",
                            "too many attempts")):
        return "RATE_LIMITED"
    return "UNKNOWN"


def tap_skip(nodes):
    node = find(nodes, "Skip", "Not now", "Maybe later", "Don't allow",
                "No thanks")
    if node:
        log(f"tapping dismiss: {node['text'] or node['desc']!r}")
        tap(*node["center"])
        return True
    return False


def tap_next(nodes):
    node = find(nodes, "Next", "Continue", "Confirm", "Verify", "Set",
                "Create account", "Sign up", "Log in")
    if node:
        log(f"tapping next: {node['text'] or node['desc']!r}")
        tap(*node["center"])
        return True
    return False


def tap_sequence_tab(i, name, desc):
    """One tap of the 8-tap acceptance sequence. Returns
    (nodes_after, crashed): nodes_after is the dump after the tap
    (possibly []), crashed is True if the process died mid-tap.

    Re-probe 3 dump-failure path: when the UI dump itself fails
    (uiautomator times out while the reels video SurfaceView is
    active), the old code re-dumped in place twice, dismissed a
    sheet that was not there, and relaunched — each failing dump
    costs ~40 s, so one tap burned ~4 min and all 6 remaining taps
    did the same. New behaviour, in order:
      1. Dumps SUCCEED but the tab is not found: the old in-place
         re-dump + sheet-dismiss path (bar settling), time-boxed.
      2. Dumps FAIL (nodes empty): tap the wanted tab at its
         LAST-KNOWN coordinates (remember_tabs) — the bar is
         visibly present in the screenshots, and the tap navigates
         off the Reels tab to a static screen where dumps work
         again. Recorded in status.json (dump_fallback_taps).
      3. Still no dump after the fallback tap: press the BACK key
         EXACTLY ONCE (from the Reels tab BACK returns to the feed;
         never on the feed itself — this branch only runs when no
         dump has succeeded since the Reels tab AND the previous
         tap was Reels, so the current screen is the Reels tab and
         not the feed) and re-dump once.
         If the screen after BACK has the bar, the fallback tap's
         navigation was undone by the BACK, so the tab is tapped
         again for real below. Recorded in status.json
         (back_recoveries). The old exit_viewer() is NOT reused
         here: it presses BACK up to 3 times, and a second BACK
         from the feed would exit the app to the launcher.
      4. Per-tap budget TAP_BUDGET_SEC: no new expensive step starts
         once the budget is spent — record the failure and move on.
    The relaunch path is gated on a SUCCEEDED dump showing the app
    is gone: app_foreground([]) is False, but that means "no dump",
    not "left the app" — the old code relaunched on empty nodes
    (futile: relaunch just brings the same Reels task forward)."""
    global LAST_TAP_NAME
    tap_started = time.time()
    # The tab tapped by the PREVIOUS sequence tap: the dump-failure
    # BACK below is only safe when it was Reels (BACK from the Reels
    # tab returns to the feed; BACK on the home feed exits the app).
    # Captured before this tap sets LAST_TAP_NAME to its own name.
    prev_tap = LAST_TAP_NAME
    tapped = False
    nodes_cur = parse_dump(dump(f"step_tab{i:02d}"))
    if nodes_cur:
        remember_tabs(nodes_cur)
    tab = find_tab(nodes_cur, desc)
    if not tab and nodes_cur:
        # Dumps work but the tab is not there yet: bar settling.
        # Time-boxed — each re-dump is cheap while dumps succeed.
        for retry in range(2):
            if time.time() - tap_started > 45:
                break
            time.sleep(2)
            log(f"tab {name} not found; re-dumping in place "
                f"(retry {retry + 1}/2, no BACK)")
            nodes_cur = parse_dump(dump(f"step_tab{i:02d}r{retry}"))
            if nodes_cur:
                remember_tabs(nodes_cur)
            tab = find_tab(nodes_cur, desc)
            if tab:
                break
    if not tab and nodes_cur:
        # A first-run promo sheet (e.g. "Introducing instants") can
        # cover the tab bar DURING the loop — the 1.14 probe's tabs
        # 4-8 died on it — so the main loop's tap_skip never sees it.
        # Dismiss it here and retry the tab once.
        fresh = dismiss_sheet(nodes_cur, f"step_tab{i:02d}sheet")
        if fresh is not None:
            nodes_cur = fresh
            remember_tabs(nodes_cur)
            tab = find_tab(nodes_cur, desc)
    if not tab and not nodes_cur:
        # --- dump-failure path (re-probe 3) ---
        if desc in LAST_TABS and time.time() - tap_started < 90:
            cx, cy = LAST_TABS[desc]
            log(f"tab {name} not found and UI dumps keep failing "
                f"(reels video SurfaceView); tapping last-known "
                f"coordinates ({cx}, {cy})")
            tap(cx, cy)
            STATUS.setdefault("dump_fallback_taps", []).append(name)
            save_status()
            tapped = True
            LAST_TAP_NAME = name
            time.sleep(3)
            nodes_cur = parse_dump(dump(f"step_tab{i:02d}fb"))
            if nodes_cur:
                remember_tabs(nodes_cur)
                tab = find_tab(nodes_cur, desc)
            else:
                # Still no dump: the fallback tap did not get us to a
                # screen dumps can read. BACK once to leave the Reels
                # tab for the feed, then re-dump once — but ONLY when
                # the previous tap was Reels, so the current screen
                # is the Reels tab and not the home feed (BACK on the
                # feed would exit the app to the launcher).
                if prev_tap == "reels" and \
                        time.time() - tap_started < 75:
                    log(f"still no UI dump after fallback tap; "
                        f"BACK key once to leave the Reels tab")
                    keyevent(4)
                    STATUS.setdefault("back_recoveries", []).append(
                        {"tab": name, "after": "fallback_tap"})
                    save_status()
                    time.sleep(3)
                    nodes_cur = parse_dump(dump(f"step_tab{i:02d}bk"))
                    if nodes_cur:
                        remember_tabs(nodes_cur)
                        if classify(nodes_cur) == "FEED":
                            tab = find_tab(nodes_cur, desc)
                            if tab:
                                # BACK undid the fallback tap's
                                # navigation: tap the tab again
                                # for real below.
                                tapped = False
                elif time.time() - tap_started < 75:
                    log(f"still no UI dump after fallback tap; NOT "
                        f"pressing BACK (previous tap was "
                        f"{prev_tap!r}, not Reels — the current "
                        f"screen could be the feed, where BACK would "
                        f"exit the app)")
    if not tab and nodes_cur and not app_foreground(nodes_cur):
        # We are no longer in the app at all: relaunch and try once
        # more instead of screenshotting the launcher as if it were
        # Instagram. Gated on a SUCCEEDED dump: empty nodes mean the
        # dump failed, not that we left the app.
        if time.time() - tap_started < 60:
            log(f"tab {name} not found and app not in foreground; "
                f"relaunching")
            relaunch()
            time.sleep(5)
            nodes_cur = parse_dump(dump(f"step_tab{i:02d}re"))
            if nodes_cur:
                remember_tabs(nodes_cur)
            tab = find_tab(nodes_cur, desc)
    if tab and not tapped:
        log(f"tap {i}/8: {name}")
        tap(*tab["center"])
        tapped = True
        LAST_TAP_NAME = name
        time.sleep(3)
    elif tapped:
        log(f"tap {i}/8: {name} (via last-known coordinates)")
    else:
        log(f"tab {name} still not found after in-place retries; "
            f"recording the failure and capturing current screen "
            f"as-is")
        STATUS.setdefault("tab_failures", []).append(name)
        save_status()
    nodes_after = parse_dump(dump(f"step_tab{i:02d}after"))
    if nodes_after:
        remember_tabs(nodes_after)
    if classify(nodes_after) == "NOTIF_DIALOG":
        log("notification-permission dialog appeared mid-sequence; "
            "dismissing (verified)")
        new_state, nodes_after = dismiss_notif(nodes_after,
                                               f"step_tab{i:02d}")
        if new_state is None:
            log("notification dialog still up mid-sequence after 2 "
                "verified taps; leaving it for the next tab iteration")
    elif classify(nodes_after) == "REEL_VIEWER":
        # A tap opened a full-screen reel viewer (no tab bar): go
        # back to the feed so the next tab tap can find the bar again.
        log("full-screen reel viewer opened mid-sequence; going back "
            "to the feed")
        rec_state, rec_nodes = exit_viewer(f"step_tab{i:02d}reel",
                                           "REEL_VIEWER")
        if rec_state == "FEED":
            nodes_after = rec_nodes
        else:
            log("reel viewer still up mid-sequence after BACK "
                "attempts; continuing with the next tab")
    screenshot(f"shot_tab{i:02d}_{name}")
    if not pid_alive():
        return nodes_after, True
    return nodes_after, False


def _png_pixels(path):
    """Decode a screencap PNG (8-bit RGB/RGBA, non-interlaced) with
    stdlib only — the probe runner has no Pillow. Returns
    (width, height, channels, pixels-bytes) or None on any failure.
    Only mean luminances of small regions are ever read from the
    pixels, never the full image."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    idat = b""
    width = height = bitdepth = colortype = None
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bitdepth, colortype = struct.unpack(
                ">IIBB", chunk[:10])
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if width is None or bitdepth != 8 or colortype not in (2, 6):
        return None
    ch = 3 if colortype == 2 else 4
    try:
        raw = zlib.decompress(idat)
    except Exception:
        return None
    stride = width * ch
    if len(raw) < height * (stride + 1):
        return None
    out = bytearray(width * height * ch)
    prev = bytearray(stride)
    p = 0
    for y in range(height):
        f = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (
                    b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif f != 0:
            return None
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return width, height, ch, bytes(out)


def _region_mean_lum(png, x0, y0, x1, y1):
    """Mean luminance of a rectangle, given in logical 720x1280
    coordinates (scaled to the actual screenshot size). Samples
    every 2nd pixel in both axes — thousands of samples per box,
    plenty for a mean. Returns None if the rectangle is empty."""
    width, height, ch, px = png
    sx = width / 720.0
    sy = height / 1280.0
    x0 = max(0, int(x0 * sx))
    y0 = max(0, int(y0 * sy))
    x1 = min(width, int(x1 * sx))
    y1 = min(height, int(y1 * sy))
    if x1 <= x0 or y1 <= y0:
        return None
    total = 0.0
    n = 0
    for y in range(y0, y1, 2):
        base = y * width * ch
        for x in range(x0, x1, 2):
            o = base + x * ch
            total += 0.299 * px[o] + 0.587 * px[o + 1] + 0.114 * px[o + 2]
            n += 1
    return total / n if n else None


def detect_drag_switch_from_shot(path):
    """Classify an after-drag screenshot as 'reels' (the Reels viewer
    is up — the drag switched), 'home' (the home feed is up — the
    drag did not switch), or 'unclear'.

    Signals, measured on the real probe shots (1.17.1 re-probe,
    1.15, 1.17 re-probe 4): the bottom capsule over the Reels viewer
    is dark (mean of the 5 tab boxes ~= 150) and the top strip is
    dark (mean ~= 136-165), while the home feed is light on both
    (capsule ~= 226, top ~= 233-239). Thresholds sit in wide gaps
    (capsule 150 vs 226+, top 136-165 vs 226+), so a bright reel
    that pushes the capsule over the line only degrades to
    'unclear' — never a false 'reels'. The Direct inbox is 'unclear'
    too (light capsule, dark top). The Profile screen reads as
    'home' (light capsule + light top); the swipe path Home->Reels
    cannot land on Profile, so that mislabel cannot affect the drag
    verdict. Returns (label, evidence dict)."""
    png = _png_pixels(path)
    if png is None:
        return "unclear", {}
    tab_centers = (97, 228, 359, 490, 622)
    box_means = [_region_mean_lum(png, x - 45, 1080, x + 45, 1160)
                 for x in tab_centers]
    if any(v is None for v in box_means):
        return "unclear", {}
    bar_mean = sum(box_means) / len(box_means)
    top_mean = _region_mean_lum(png, 0, 60, 720, 120)
    if top_mean is None:
        return "unclear", {}
    ev = {"bar_mean": round(bar_mean, 1), "top_mean": round(top_mean, 1)}
    if bar_mean < 190 and top_mean < 200:
        return "reels", ev
    if bar_mean > 200 and top_mean > 200:
        return "home", ev
    return "unclear", ev


def detect_lens_in_shots(mid_paths, ref_path):
    """Measure whether the glass lens is visible in mid-drag shots.

    Compares each mid-shot against the pre-drag Home shot
    (shot_tab08_home.png, captured minutes earlier — the bar is
    static and the capsule effectively opaque, so the reference
    zones are stable to <1 unit across every Home shot in every
    probe): the glass lens darkens the capsule where it sits. Two
    zones cover the lens positions at ~40% (early, x 110-200) and
    ~70% (late, x 150-250) through the swipe. Measured: the 1.17.1
    re-probe mid-shot darkens by ~29 (early) / ~17 (late) units,
    while the negative controls — 1.15 (no drag hook) and 1.17
    re-probe 4 (broken overlay) — darken by exactly 0. A darkening
    of 10-60 counts as the lens; below 10 is noise, above 60 means
    the shot is already a different (dark) screen, not a lens.
    Returns (seen, darkening, zone, shot) — seen None when the
    reference shot is missing or no mid-shot decodes."""
    ref = _png_pixels(ref_path)
    if ref is None:
        return None, None, None, None
    zones = {"early": (110, 1090, 200, 1150),
             "late": (150, 1090, 250, 1150)}
    ref_means = {}
    for name, (x0, y0, x1, y1) in zones.items():
        v = _region_mean_lum(ref, x0, y0, x1, y1)
        if v is None:
            return None, None, None, None
        ref_means[name] = v
    best = None  # (darkening, zone, shot)
    for shot in mid_paths:
        png = _png_pixels(shot)
        if png is None:
            continue
        for name, (x0, y0, x1, y1) in zones.items():
            v = _region_mean_lum(png, x0, y0, x1, y1)
            if v is None:
                continue
            dark = ref_means[name] - v
            if best is None or dark > best[0]:
                best = (dark, name, shot)
    if best is None:
        return None, None, None, None
    dark, zone, shot = best
    seen = 10.0 <= dark <= 60.0
    return seen, round(dark, 1), zone, shot


def _row_mean_lum(png, y, x_ranges):
    """Mean luminance of one screenshot row (logical 720x1280
    coordinates), sampled over x_ranges — the columns BETWEEN the tab
    icons, so no icon pixels pollute the reading. Returns None when
    the row is empty."""
    width, height, ch, px = png
    sx = width / 720.0
    sy = height / 1280.0
    yy = int(y * sy)
    if yy < 0 or yy >= height:
        return None
    total = 0.0
    n = 0
    base = yy * width * ch
    for x0, x1 in x_ranges:
        for x in range(max(0, int(x0 * sx)), min(width, int(x1 * sx)), 2):
            o = base + x * ch
            total += 0.299 * px[o] + 0.587 * px[o + 1] + 0.114 * px[o + 2]
            n += 1
    return total / n if n else None


def detect_flat_bar_frame(path):
    """Is the bottom bar in this shot the glass capsule or the flat
    background frame Instagram's bar controller repaints on page
    switches (1.19 capsule flash)?

    The capsule is a translucent vertical gradient pill, so four rows
    across it (y=1082/1120/1158/1166, between the icons) always
    differ from each other; a flat repaint is one solid colour, so
    all four rows read identical. Measured on the real 1.18 probe
    shots (capsule, good): row spreads 35-44; on a synthetic flat
    frame (the feed shot with the bar strip painted solid #121212):
    spread exactly 0.0. Thresholds sit in the gap: spread < 5
    -> 'flat', 5-15 -> 'unclear', >= 15 -> 'capsule'. A stock bar
    background with its own strong gradient could read 'capsule'
    (false negative) — the burst shots are eyeballed by the monitor
    as the backstop, and the pre-draw guard's logcat lines are the
    primary evidence either way. Returns (verdict, evidence dict)."""
    png = _png_pixels(path)
    if png is None:
        return "unclear", {}
    xs = [(130, 195), (260, 330), (390, 460), (520, 585)]
    rows = [_row_mean_lum(png, y, xs) for y in (1082, 1120, 1158, 1166)]
    if any(v is None for v in rows):
        return "unclear", {}
    spread = max(rows) - min(rows)
    ev = {"spread": round(spread, 1),
          "rows": [round(v, 1) for v in rows]}
    if spread < 5.0:
        return "flat", ev
    if spread < 15.0:
        return "unclear", ev
    return "capsule", ev


def run_transition_test():
    """1.19 capsule-flash acceptance test: Home -> Reels -> Home
    with rapid screenshot bursts DURING each switch, checking every
    burst shot for the flat background frame (see
    detect_flat_bar_frame). Runs between the 8-tap sequence and the
    drag test (the sequence ends on Home, the drag test starts from
    Home). Records STATUS['transition_test'] with the per-shot
    verdicts plus the live count of pre-draw guard firings in
    logcat — the guard is what prevents a 1-frame flash the burst
    can miss, so its firings are evidence too. Returns the result
    string."""
    result = "TRANSITION_SKIPPED"
    info = {"result": result, "shots": [], "guard_firings": 0}
    try:
        # Guard firings BEFORE the switches, so the count below is
        # the delta during the transitions (not everything since
        # launch, which includes the 8-tap sequence).
        guard_before = 0
        try:
            out, _, _ = adb("logcat", "-d", timeout=90)
            guard_before = out.count("capsule re-applied in pre-draw")
        except Exception:
            pass
        nodes = parse_dump(dump("step_trans0"))
        if nodes:
            remember_tabs(nodes)
        home = find_tab(nodes, "Home")
        reels = find_tab(nodes, "Reels")
        if ((not home or not reels) and "Home" in LAST_TABS
                and "Reels" in LAST_TABS):
            home = {"center": LAST_TABS["Home"]}
            reels = {"center": LAST_TABS["Reels"]}
            info["used_fallback_coords"] = True
            log("transition test: UI dumps failing; using last-known "
                "tab coordinates")
        if not home or not reels:
            log("transition test skipped: Home/Reels tab not found")
            STATUS["transition_test"] = info
            return result
        for label, target in (("h2r", reels), ("r2h", home)):
            x, y = target["center"]
            log(f"transition test: tapping {label} at {(x, y)}")
            # Direct input tap, NOT tap(): tap() sleeps 1 s, which
            # would push the first burst shot past the whole
            # ~200-400 ms switch. The burst must start immediately.
            shell("input", "tap", str(x), str(y))
            for i in range(TRANS_BURST_SHOTS):
                time.sleep(TRANS_BURST_INTERVAL_S)
                name = f"shot_trans_{label}_{i}"
                screenshot(name)
                verdict, ev = detect_flat_bar_frame(f"{name}.png")
                info["shots"].append(
                    {"name": f"{name}.png", "verdict": verdict, **ev})
                log(f"transition {label} shot {i}: {verdict} "
                    f"(spread {ev.get('spread')})")
        # Let the switch settle back on Home before the drag test.
        time.sleep(1.5)
        try:
            out, _, _ = adb("logcat", "-d", timeout=90)
            info["guard_firings"] = (
                out.count("capsule re-applied in pre-draw") - guard_before)
            log(f"transition test: pre-draw guard fired "
                f"{info['guard_firings']} time(s) during the switches")
        except Exception as e:
            log(f"transition test: guard count failed ({e})")
        verdicts = [s["verdict"] for s in info["shots"]]
        if "flat" in verdicts:
            result = "FLAT_FRAME_SEEN"
        elif "unclear" in verdicts:
            result = "TRANSITION_UNCLEAR"
        elif verdicts:
            result = "NO_FLAT_FRAME"
        else:
            result = "TRANSITION_SKIPPED"
        info["result"] = result
        log(f"transition test: {result} "
            f"({len(verdicts)} burst shots analysed)")
        STATUS["transition_test"] = info
    except Exception as e:
        log(f"transition test error (non-fatal): {e}")
        info["result"] = "TRANSITION_ERROR"
        info["error"] = str(e)
        STATUS["transition_test"] = info
        result = "TRANSITION_ERROR"
    return result


def capture_drag_logcat():
    """Snapshot logcat IMMEDIATELY after the drag test, before the
    ~40 s after-dump retry loop: the 1.17.1 re-probe's final capture
    ran ~44 s after the drag and reels log spam had evicted every
    RdxGramTheme line from the ring buffer (0 lines, even "drag
    overlay attached" which the earlier probe did show). Writes
    logcat-drag.txt (full dump) and logs the drag lines found, so
    the evidence survives even if the final capture loses them. The
    existing final capture in finish() is untouched. Returns the
    matching lines (diagnostics only — no secrets)."""
    out, _, _ = adb("logcat", "-d", timeout=90)
    try:
        with open("logcat-drag.txt", "w", encoding="utf-8") as fh:
            fh.write(out)
    except OSError:
        pass
    lines = [l.strip() for l in out.splitlines()
             if "RdxGramTheme" in l and "drag" in l.lower()]
    log(f"drag logcat snapshot: {len(lines)} drag line(s)")
    for l in lines[:10]:
        log(f"  {l[:200]}")
    return lines


def run_drag_test():
    """1.13 drag-lens acceptance test: slow horizontal drag across
    the tab bar, Home -> Reels. Screenshot mid-drag (the lens should
    be visible following the finger) and after release (the tab
    should have switched to Reels). The swipe runs in the background
    so the mid-drag screenshot lands ~40% through it. Uses only
    `adb shell input swipe`, the same `input` command family as the
    taps above. Returns the drag result string and records
    STATUS["drag_test"].

    Re-probe 3: the drag test was SKIPPED because the dump after the
    tap loop failed (reels SurfaceView) and Home/Reels could not be
    found. If the dumps fail here but last-known tab centers exist,
    the swipe still runs between those coordinates (the bar is
    visibly present) and the result is DRAG_UNKNOWN_DUMP_FAILED
    when the after-dump cannot confirm the switch — the mid/after
    screenshots are the evidence.

    Fix #4 (1.17.1 re-probe): the drag DID switch, but the verdict
    stayed DRAG_UNKNOWN_DUMP_FAILED — the after-dump failed, the
    lens was not seen, and the logcat lines were evicted. So the
    switch is now confirmed from the after-SCREENSHOT too
    (DRAG_SWITCHED_VISUAL when it shows the Reels viewer,
    DRAG_NO_SWITCH when it still shows the home feed), after one
    late re-dump; DRAG_UNKNOWN_DUMP_FAILED is kept only when
    neither the dump nor the screenshot confirms either outcome.
    The dump alone cannot prove a Reels switch (measured: a
    post-Reels-tap dump keeps Home selected=true and usually has
    no "Reel by" text at +3 s), so a Home-selected dump does NOT
    prove no-switch either — the screenshot is the primary switch
    evidence. Two mid-shots (~40% and ~70%) bracket the gesture,
    the lens is measured by pixel comparison against the tab-8
    reference shot, and logcat is snapshotted immediately after
    the drag (see capture_drag_logcat). The verdict stays honest:
    a switch is claimed only from a dump showing Reels selected /
    viewer text, or from an after-shot showing the Reels viewer."""
    drag_result = "DRAG_SKIPPED"
    try:
        nodes_drag = parse_dump(dump("step_drag0"))
        if nodes_drag:
            remember_tabs(nodes_drag)
        home_tab = find_tab(nodes_drag, "Home")
        reels_tab = find_tab(nodes_drag, "Reels")
        used_fallback = False
        if not home_tab or not reels_tab:
            # A first-run sheet may be covering the bar here too;
            # dismiss it and retry once.
            fresh = dismiss_sheet(nodes_drag, "step_drag_sheet")
            if fresh is not None:
                nodes_drag = fresh
                remember_tabs(nodes_drag)
                home_tab = find_tab(nodes_drag, "Home")
                reels_tab = find_tab(nodes_drag, "Reels")
        if (not home_tab or not reels_tab) and "Home" in LAST_TABS \
                and "Reels" in LAST_TABS:
            # Dumps failed (re-probe 3) but the bar is visibly
            # present: swipe between the last-known centers.
            log("drag test: UI dumps failing; using last-known tab "
                "coordinates")
            used_fallback = True
            home_tab = {"center": LAST_TABS["Home"]}
            reels_tab = {"center": LAST_TABS["Reels"]}
        if home_tab and reels_tab:
            x0, y0 = home_tab["center"]
            x1, y1 = reels_tab["center"]
            log(f"drag test: Home {home_tab['center']} -> "
                f"Reels {reels_tab['center']} over {DRAG_SWIPE_MS} ms")
            subprocess.Popen(["adb", "-s", SER, "shell",
                              "input", "swipe",
                              str(x0), str(y0), str(x1), str(y1),
                              str(DRAG_SWIPE_MS)])
            # Two mid-shots bracket the gesture (fix #4): the swipe
            # only starts after the adb round-trip, and each
            # screencap costs another one, so one shot is a gamble.
            time.sleep(DRAG_MID1_S)  # ~40% through the swipe
            screenshot("shot_drag_mid")
            time.sleep(DRAG_MID2_S - DRAG_MID1_S)  # ~70%
            screenshot("shot_drag_mid2")
            # The swipe ends 1.2 s after it started on-device; wait
            # until DRAG_AFTER_S after Popen (the same total as
            # before) so the tab has time to settle — in the 1.12
            # dumps the Reels tab only reports selected=true once
            # the viewer has fully loaded.
            time.sleep(max(0.0, DRAG_AFTER_S - DRAG_MID2_S))
            screenshot("shot_drag_after")
            # Logcat FIRST, before the dump retries: the final
            # capture in finish() runs ~40 s later, after the
            # after-dump retry loop, and by then reels log spam
            # has evicted the drag lines (1.17.1 re-probe: 0
            # RdxGramTheme lines in logcat-final.txt).
            drag_lines = capture_drag_logcat()
            # The lens is measured, not just eyeballed: compare the
            # mid-shots against the pre-drag Home shot (the bar is
            # static, so the reference zones are stable to <1 unit).
            lens_seen, lens_dark, lens_zone, lens_shot = \
                detect_lens_in_shots(
                    ["shot_drag_mid.png", "shot_drag_mid2.png"],
                    "shot_tab08_home.png")
            if lens_seen is None:
                log("drag test: lens check skipped (no reference shot)")
            else:
                log(f"drag test: lens seen={lens_seen} "
                    f"(darkening {lens_dark} in {lens_zone} zone of "
                    f"{lens_shot})")
            nodes_drag_after = parse_dump(dump("step_drag_after"))
            late_dump = False
            if not nodes_drag_after:
                # The after-dump failed (reels SurfaceView): wait
                # for the SurfaceView to settle and re-dump ONCE
                # before giving up on the dump path.
                log("drag test: after-dump failed; waiting 5s and "
                    "re-dumping once (SurfaceView may settle)")
                time.sleep(5)
                nodes_drag_after = parse_dump(dump("step_drag_after2"))
                late_dump = nodes_drag_after is not None
            drag_info = {
                "from": list(home_tab["center"]),
                "to": list(reels_tab["center"]),
                "used_fallback_coords": used_fallback,
                "mid_shot": "shot_drag_mid.png",
                "mid_shot2": "shot_drag_mid2.png",
                "after_shot": "shot_drag_after.png",
                "lens_seen": lens_seen,
                "lens_darkening": lens_dark,
                "lens_zone": lens_zone,
                "logcat_drag_lines": len(drag_lines),
                "late_dump": late_dump,
            }
            switched_by_dump = False
            dump_evidence = None
            if nodes_drag_after:
                selected = [n["desc"] for n in nodes_drag_after
                            if n.get("selected")
                            and n["desc"] in
                            ("Home", "Reels", "Message",
                             "Search and explore", "Profile")]
                drag_info["selected_after"] = selected
                low_text = low(nodes_drag_after)
                if "Reels" in selected:
                    switched_by_dump = True
                    dump_evidence = f"dump: Reels selected {selected}"
                elif ("reel by" in low_text or
                        "double tap to play or pause" in low_text):
                    # The viewer is up even though the bar still
                    # reports Home selected (measured: post-Reels-tap
                    # dumps keep Home selected and usually have no
                    # viewer text at +3 s — the late retry is the
                    # one that can catch it once loaded).
                    switched_by_dump = True
                    dump_evidence = "dump: Reels viewer text present"
            if switched_by_dump:
                drag_result = "DRAG_SWITCHED_TO_REELS"
                log(f"drag test: {drag_result} ({dump_evidence})")
                drag_info["dump_evidence"] = dump_evidence
                drag_info["result"] = drag_result
            else:
                # No dump evidence either way: a Home-selected dump
                # does NOT prove no-switch (measured: a successful
                # Reels tap leaves Home selected), so judge the
                # switch from the after-screenshot itself.
                shot_label, shot_ev = detect_drag_switch_from_shot(
                    "shot_drag_after.png")
                drag_info["shot_label"] = shot_label
                drag_info["shot_evidence"] = shot_ev
                if shot_label == "reels":
                    drag_result = "DRAG_SWITCHED_VISUAL"
                    log(f"drag test: {drag_result} (after-shot "
                        f"shows the Reels viewer: {shot_ev})")
                elif shot_label == "home":
                    drag_result = "DRAG_NO_SWITCH"
                    log(f"drag test: {drag_result} (after-shot "
                        f"still shows the home feed: {shot_ev})")
                else:
                    drag_result = "DRAG_UNKNOWN_DUMP_FAILED"
                    log("drag test: after-dump failed and the "
                        "after-shot is ambiguous; switch "
                        "unconfirmed (see shot_drag_after.png)")
                drag_info["result"] = drag_result
            STATUS["drag_test"] = drag_info
        else:
            log("drag test skipped: Home/Reels tab not found")
            STATUS["drag_test"] = {"result": "DRAG_SKIPPED"}
    except Exception as e:
        log(f"drag test error (non-fatal): {e}")
        STATUS["drag_test"] = {"result": "DRAG_ERROR",
                               "error": str(e)}
    return drag_result


def finish(status, detail=""):
    STATUS["status"] = status
    STATUS["detail"] = detail
    STATUS["cold_start_total_ms"] = cold_start_ms()
    count, out = logcat_fatal_count()
    STATUS["fatal_count"] = max(count, STATUS["fatal_count"])
    with open("logcat-final.txt", "w", encoding="utf-8") as fh:
        fh.write(out)
    m = re.search(r"(FATAL EXCEPTION.{0,3000})", out, re.S)
    with open("crash-final.txt", "w", encoding="utf-8") as fh:
        fh.write(m.group(1) if m else "")
    save_status()
    log(f"FINAL: {status} — {detail}")


def main():
    STATUS["cold_start_total_ms"] = cold_start_ms()
    save_status()
    log(f"driver started; package={PKG}; deadline in "
        f"{int(DEADLINE - time.time())}s")
    if not pid_alive():
        relaunch()
    if not pid_alive():
        return finish("NOT_RUNNING", "app process never started")

    submitted = False
    login_form_revisits = 0
    last_state = None
    same_state_runs = 0
    kb_hidden_for = None  # state for which the keyboard was already hidden

    for step in range(1, 61):
        STATUS["steps"] = step
        if time.time() > DEADLINE:
            return finish("TIMEOUT", "driver deadline reached")
        path = dump(f"step{step:02d}")
        nodes = parse_dump(path)
        if path is None:
            # dump() failed 3x (e.g. the UI never goes idle while a
            # video plays): there is NO fresh hierarchy, so act on
            # nothing — wait and retry this step instead of tapping
            # blindly at coordinates from an old screen.
            log("UI dump failed (no fresh hierarchy); waiting 3s "
                "and retrying this step without acting")
            time.sleep(3)
            continue
        state = classify(nodes)
        # A focused field means the soft keyboard is up and covers the
        # lower buttons: hide it once per screen visit before any button
        # tap, then re-classify. (Hiding twice would send a real BACK.)
        if state in ("LOGIN_FORM", "CODE", "SAVE_LOGIN", "FIND_PEOPLE",
                     "INTERSTITIAL", "LANDING"):
            if kb_hidden_for != state:
                nodes, hid = maybe_hide_keyboard(nodes)
                if hid:
                    kb_hidden_for = state
                    state = classify(nodes)
        if state != last_state and kb_hidden_for != state:
            kb_hidden_for = None
        STATUS["last_screen"] = state
        # Stuck detection: same state 6 times in a row = no progress.
        if state == last_state:
            same_state_runs += 1
        else:
            last_state = state
            same_state_runs = 1
        if same_state_runs >= 6:
            screenshot(f"shot_stuck_{state.lower()}")
            return finish(f"STUCK_{state}",
                          f"same screen {same_state_runs} steps in a row "
                          f"with no progress")
        log(f"step {step}: screen={state} "
            f"texts={all_text(nodes)[:300]!r}")
        save_status()

        if state == "REEL_VIEWER":
            # Full-screen reel viewer opened right after login (the
            # feed's top item auto-opened it in the 1.17 re-probe) or
            # mid-flow: the tab bar is hidden by design, so go BACK
            # to the feed — verified, at most 3 attempts. BACK is
            # never pressed on the feed itself. On success the next
            # loop iteration re-classifies the fresh screen (FEED).
            log("full-screen reel viewer (tab bar hidden by design); "
                "going back to the feed")
            rec_state, _ = exit_viewer(f"step{step:02d}reel",
                                       "REEL_VIEWER")
            if rec_state == "FEED":
                continue
            screenshot("shot_stuck_reel")
            return finish("STUCK_REEL_VIEWER",
                          "full-screen reel viewer did not return to "
                          "the feed after 3 BACK attempts")

        if state == "FEED":
            log("HOME FEED REACHED — login succeeded; letting it settle")
            time.sleep(5)
            screenshot("shot_feed")
            # Remember the bar now, while the dumps still work: the
            # tap loop's dump-failure fallback needs last-known tab
            # coordinates (re-probe 3: dumps die on the Reels tab).
            remember_tabs(nodes)
            # 1.11 capsule-fix acceptance test: 8 tab taps
            # home -> reels -> direct -> profile -> home -> reels ->
            # direct -> home, screenshot + UI dump after EVERY tap.
            # The 1.10/1.11 probes only did feed -> explore -> profile ->
            # feed, so the suspected trigger tabs (reels/direct) were
            # never visited and the fix stayed unproven.
            sequence = [
                ("home", "Home"), ("reels", "Reels"),
                ("direct", "Message"), ("profile", "Profile"),
                ("home", "Home"), ("reels", "Reels"),
                ("direct", "Message"), ("home", "Home"),
            ]
            for i, (name, desc) in enumerate(sequence, 1):
                _, crashed = tap_sequence_tab(i, name, desc)
                if crashed:
                    return finish("CRASHED_AFTER_FEED",
                                  f"process died during tab sequence "
                                  f"(tap {i}/8: {name})")
            if not check_alive("8-tap tab sequence"):
                return finish("CRASHED_AFTER_FEED",
                              "FATAL or dead process after tab sequence")
            # 1.19 capsule-flash acceptance test (see
            # run_transition_test): Home -> Reels -> Home bursts.
            trans_result = run_transition_test()
            if not check_alive("transition test"):
                return finish("CRASHED_AFTER_FEED",
                              "FATAL or dead process after transition test")
            # 1.13 drag-lens acceptance test (see run_drag_test).
            drag_result = run_drag_test()
            return finish("LOGGED_IN_FEED", "home feed + 8-tap sequence "
                          "captured (home/reels/direct/profile x2); "
                          f"transition test: {trans_result}; "
                          f"drag test: {drag_result}")
        if state == "WRONG_PASSWORD":
            screenshot("shot_wrong_password")
            return finish("WRONG_PASSWORD",
                          f"Instagram rejected the password: "
                          f"{all_text(nodes)[:300]!r}")

        if state == "CODE":
            dest = extract_code_destination(nodes)
            STATUS["code_destination_masked"] = dest
            save_status()
            screenshot("shot_code_required")
            if not IG_CODE and not IG_CODE_URL:
                return finish("CODE_REQUIRED",
                              f"Instagram asked for a verification code, "
                              f"but no code source is configured "
                              f"(IG_CODE / IG_CODE_URL empty). "
                              f"Destination (as shown, masked): {dest}")
            # At most two code attempts: wait once more if the code
            # never arrives or the entered code is rejected.
            rejected = False
            for attempt in (1, 2):
                STATUS["code_attempts"] = attempt
                save_status()
                code, source = obtain_code()
                if code is None:
                    if attempt == 1:
                        log("no code arrived; waiting once more "
                            "(second and last wait)")
                        continue
                    return finish("CODE_TIMEOUT",
                                  "no 6-digit code arrived after two "
                                  f"waits ({CODE_WAIT_SEC}s each)" +
                                  ("; the first code was rejected"
                                   if rejected else ""))
                STATUS["code_source"] = source
                save_status()
                log(f"code attempt {attempt} via {source}")
                new_state = enter_code(nodes, code)
                code = None  # never keep the value around
                if new_state != "CODE":
                    # Accepted (or a different screen): let the main
                    # loop handle whatever Instagram shows next.
                    log(f"after code submit: screen={new_state}")
                    break
                rejected = True
                screenshot(f"shot_code_rejected_{attempt}")
                if attempt == 1:
                    log("code was rejected; waiting once more for a "
                        "fresh code")
                    nodes = parse_dump(dump(f"step{step:02d}e"))
                    continue
                return finish("CODE_REJECTED",
                              "Instagram rejected the verification code "
                              "twice")
            continue

        if state == "CHALLENGE":
            screenshot("shot_challenge")
            return finish("CHALLENGE",
                          f"Instagram asked for extra verification: "
                          f"{all_text(nodes)[:400]!r}")

        if state == "RATE_LIMITED":
            screenshot("shot_rate_limited")
            return finish("RATE_LIMITED",
                          f"Instagram rate-limited the login: "
                          f"{all_text(nodes)[:300]!r}")

        if state == "LANDING":
            node = find(nodes, "I already have a profile")
            if node:
                log("tapping 'I already have a profile'")
                tap(*node["center"])
                time.sleep(3)
                continue
            node = find_exact(nodes, "Log in")
            if node:
                log("tapping 'Log in' on landing")
                tap(*node["center"])
                time.sleep(3)
                continue
            return finish("STUCK_LANDING", "landing has no login button")

        if state == "LOGIN_FORM":
            if submitted:
                # One submit only: if the form is still showing, give it
                # one more chance, then stop — never re-submit.
                login_form_revisits += 1
                if login_form_revisits >= 2:
                    screenshot("shot_login_no_advance")
                    return finish("LOGIN_NO_ADVANCE",
                                  "login form still showing after submit, "
                                  "no error dialog and no advance")
                log("still on login form after submit; waiting once more")
                time.sleep(8)
                continue
            # Login-only probe: never tap "Sign up" / "Create new account".
            eds = edits(nodes)
            user_field = find_edit(nodes, "Username") or (
                eds[0] if eds else None)
            pass_field = find_edit(nodes, "Password") or (
                eds[1] if len(eds) > 1 else None)
            if not user_field or not pass_field:
                return finish("STUCK_LOGIN_FORM",
                              "login form has no username/password fields")
            tap(*user_field["center"])
            type_text(USER)
            # Verify the username landed WITHOUT logging its value.
            nodes_chk = parse_dump(dump(f"step{step:02d}u"))
            shown = " ".join(n["text"] for n in edits(nodes_chk))
            if USER not in shown:
                log("username text did not land; retrying once")
                clear_field(user_field["center"])
                type_text(USER)
            # Focus bug (run 43754171807): the password was typed into the
            # still-focused username field because the tap on the password
            # field used STALE coordinates from the pre-typing dump and was
            # never verified. Re-find the password field from a FRESH dump,
            # tap it, and confirm it is focused before typing.
            nodes_fresh = parse_dump(dump(f"step{step:02d}p"))
            pass_field = find_edit(nodes_fresh, "Password") or (
                edits(nodes_fresh)[1] if len(edits(nodes_fresh)) > 1 else None)
            if not pass_field:
                return finish("STUCK_LOGIN_FORM",
                              "password field vanished after typing username")
            tap(*pass_field["center"])
            time.sleep(1)
            nodes_foc = parse_dump(dump(f"step{step:02d}f"))
            pf = find_edit(nodes_foc, "Password") or (
                edits(nodes_foc)[1] if len(edits(nodes_foc)) > 1 else None)
            if pf and pf.get("focused") != "true":
                log("password field not focused after tap; tapping again")
                tap(*pf["center"])
                time.sleep(1)
            type_text(PASS)
            # Regression check: the username field must still be EXACTLY the
            # username — if the password leaked into it, it would read
            # USER+PASS (seen in run 43754171807). Field values are never
            # logged; only the equality result is used.
            nodes_ver = parse_dump(dump(f"step{step:02d}v"))
            uf = find_edit(nodes_ver, "Username") or (
                edits(nodes_ver)[0] if edits(nodes_ver) else None)
            if uf and uf["text"] != USER:
                log("username field changed after password typing; "
                    "refilling both fields once")
                clear_field(uf["center"])
                type_text(USER)
                nodes_r = parse_dump(dump(f"step{step:02d}r"))
                pf2 = find_edit(nodes_r, "Password") or (
                    edits(nodes_r)[1] if len(edits(nodes_r)) > 1 else None)
                if not pf2:
                    return finish("STUCK_LOGIN_FORM",
                                  "password field missing on refill")
                tap(*pf2["center"])
                time.sleep(1)
                type_text(PASS)
                nodes_ver2 = parse_dump(dump(f"step{step:02d}v2"))
                uf2 = find_edit(nodes_ver2, "Username") or (
                    edits(nodes_ver2)[0] if edits(nodes_ver2) else None)
                if uf2 and uf2["text"] != USER:
                    return finish("LOGIN_NO_ADVANCE",
                                  "username field corrupted twice while "
                                  "typing password; aborting before submit")
            log("username and password filled; hiding keyboard")
            dismiss_keyboard()
            time.sleep(1)
            nodes_sub = parse_dump(dump(f"step{step:02d}b"))
            btn = find_exact(nodes_sub, "Log in")
            if not btn:
                btn = find(nodes_sub, "Log in")
            if not btn:
                return finish("STUCK_LOGIN_FORM",
                              "no Log in button on login form")
            log("tapping Log in (submit) — single login attempt")
            tap(*btn["center"])
            submitted = True
            time.sleep(10)
            continue

        if state == "SAVE_LOGIN":
            if tap_skip(nodes):
                time.sleep(3)
                continue
            screenshot("shot_save_login")
            return finish("STUCK_SAVE_LOGIN",
                          "save-login sheet has no Not-now button")

        if state == "NOTIF_DIALOG":
            # Dismiss with verification (tap, settle, fresh dump) and
            # at most 2 taps — the 1.17 re-probe tapped blindly 4
            # times while a stale dump kept showing the dialog, and
            # the extra taps landed on the feed and opened a reel.
            new_state, nodes = dismiss_notif(nodes, f"step{step:02d}")
            if new_state is None:
                screenshot("shot_notif_dialog")
                return finish("STUCK_NOTIF_DIALOG",
                              "notification-permission dialog could not "
                              "be dismissed (no button, or still up "
                              "after 2 verified taps)")
            # Dismissed (or the screen changed): the next loop
            # iteration classifies the fresh screen.
            continue

        if state == "ONBOARDING_LOCATION":
            # First-run "Set up on new device" location onboarding
            # (1.17.1 probe): BACK first, then Continue + deny the
            # system dialog — verified at every step, max 2 attempts
            # per call. On success the next loop iteration classifies
            # the fresh screen.
            rec_state, _ = exit_onboarding_location(
                nodes, f"step{step:02d}onb")
            if rec_state not in (None, "ONBOARDING_LOCATION"):
                continue
            # Still on the onboarding: loop re-classifies; the
            # same-state guard above finishes STUCK_ONBOARDING_LOCATION
            # after 6 identical steps.
            continue

        if state == "LOCATION_PERMISSION":
            # System location dialog outside the onboarding flow
            # (should not happen — the onboarding handler denies it
            # inline — but never grant it anywhere).
            new_state, nodes = dismiss_location_permission(
                nodes, f"step{step:02d}")
            if new_state is None:
                screenshot("shot_location_dialog")
                return finish("STUCK_LOCATION_PERMISSION",
                              "system location-permission dialog could "
                              "not be denied (no button, or still up "
                              "after 2 verified taps)")
            continue

        if state in ("FIND_PEOPLE", "INTERSTITIAL", "PHOTO"):
            if tap_skip(nodes):
                time.sleep(3)
                continue
            if tap_next(nodes):
                time.sleep(3)
                continue
            # A full-screen photo viewer can still land here as PHOTO
            # (its header says "Profile picture of <author>") even
            # with the tightened PHOTO check — if it has a Back button
            # and no Skip/Next, it is a viewer, not the interstitial:
            # go back to the feed instead of declaring STUCK.
            if state == "PHOTO" and find_back_button(nodes):
                log("PHOTO screen has a Back button and no Skip/Next "
                    "— treating it as a full-screen viewer")
                rec_state, _ = exit_viewer(f"step{step:02d}photo",
                                           "PHOTO_VIEWER")
                if rec_state == "FEED":
                    continue
                screenshot(f"shot_stuck_{state.lower()}")
                return finish("STUCK_REEL_VIEWER",
                              "full-screen viewer (seen as PHOTO) did "
                              "not return to the feed after 3 BACK "
                              "attempts")
            screenshot(f"shot_stuck_{state.lower()}")
            return finish(f"STUCK_{state}",
                          f"no Skip/Not-now on {state} screen")

        # UNKNOWN — could be a post-login extra prompt (birthday / phone):
        # the login itself already succeeded in that case.
        t = low(nodes)
        if submitted and any(k in t for k in ("birthday", "date of birth",
                                              "add your phone number",
                                              "add a phone number")):
            screenshot("shot_post_login_prompt")
            return finish("LOGGED_IN_EXTRA_PROMPT",
                          f"login advanced past the form; Instagram now "
                          f"asks for extra profile info: "
                          f"{all_text(nodes)[:300]!r}")
        if tap_skip(nodes):
            time.sleep(3)
            continue
        screenshot(f"shot_unknown_{step:02d}")
        return finish("UNKNOWN_SCREEN",
                      f"unrecognized screen: {all_text(nodes)[:400]!r}")

    return finish("TOO_MANY_STEPS", "60 steps without a verdict")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            finish("DRIVER_ERROR", f"{type(e).__name__}: {e}")
        except Exception:
            pass
    sys.exit(0)
