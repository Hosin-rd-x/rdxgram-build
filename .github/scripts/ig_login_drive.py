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
Finally it checks the log for FATAL crashes (CRASHED_AFTER_FEED if any
appear).

After a successful login Android may also show the system
notification-permission dialog ("Allow Rdx gram to send you
notifications?"). The driver dismisses it with "Don't allow" so it can
reach the feed instead of ending on UNKNOWN_SCREEN.

Outputs (working dir): status.json, status.txt, timeline.txt, ui_step*.xml,
shot_*.png, logcat-final.txt, crash-final.txt.
Exit code is always 0 — the verdict lives in status.json/status.txt.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

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
    path = f"ui_{name}.xml"
    for _ in range(3):
        shell("uiautomator", "dump", "/sdcard/ui.xml")
        out, _, _ = adb("pull", "/sdcard/ui.xml", path)
        if os.path.exists(path) and os.path.getsize(path) > 100:
            return path
        time.sleep(2)
    return path if os.path.exists(path) else None


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
    # System notification-permission dialog can overlay the feed, so
    # it must win over the FEED nav check below.
    if "send you notifications" in t:
        return "NOTIF_DIALOG"
    nav_hits = sum(1 for k in ("home", "search and explore", "reels",
                               "notifications", "profile")
                   if k in descs or k in t)
    if nav_hits >= 3 or "your story" in t:
        return "FEED"
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

        if state == "FEED":
            log("HOME FEED REACHED — login succeeded; letting it settle")
            time.sleep(5)
            screenshot("shot_feed")
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
                nodes_cur = parse_dump(dump(f"step_tab{i:02d}"))
                tab = find_tab(nodes_cur, desc)
                if not tab:
                    # The tab bar can hide behind a full-screen viewer
                    # (e.g. Reels): BACK once and look again.
                    log(f"tab {name} not found; pressing BACK and "
                        f"retrying once")
                    keyevent(4)
                    time.sleep(1.5)
                    nodes_cur = parse_dump(dump(f"step_tab{i:02d}b"))
                    tab = find_tab(nodes_cur, desc)
                if tab:
                    log(f"tap {i}/8: {name}")
                    tap(*tab["center"])
                    time.sleep(3)
                else:
                    log(f"tab {name} still not found; capturing "
                        f"current screen as-is")
                nodes_after = parse_dump(dump(f"step_tab{i:02d}after"))
                if classify(nodes_after) == "NOTIF_DIALOG":
                    btn = find_exact(nodes_after, "Don't allow",
                                     "Don’t allow") or \
                        find(nodes_after, "Don't allow")
                    if btn:
                        log("notification-permission dialog appeared "
                            "mid-sequence; tapping Don't allow")
                        tap(*btn["center"])
                        time.sleep(2)
                        nodes_after = parse_dump(
                            dump(f"step_tab{i:02d}after2"))
                screenshot(f"shot_tab{i:02d}_{name}")
                if not pid_alive():
                    return finish("CRASHED_AFTER_FEED",
                                  f"process died during tab sequence "
                                  f"(tap {i}/8: {name})")
            if not check_alive("8-tap tab sequence"):
                return finish("CRASHED_AFTER_FEED",
                              "FATAL or dead process after tab sequence")
            # 1.13 drag-lens acceptance test: slow horizontal drag across
            # the tab bar, Home -> Reels. Screenshot mid-drag (the lens
            # should be visible following the finger) and after release
            # (the tab should have switched to Reels). The swipe runs in
            # the background so the mid-drag screenshot lands ~40%
            # through it. Uses only `adb shell input swipe`, the same
            # `input` command family as the taps above.
            drag_result = "DRAG_SKIPPED"
            try:
                nodes_drag = parse_dump(dump("step_drag0"))
                home_tab = find_tab(nodes_drag, "Home")
                reels_tab = find_tab(nodes_drag, "Reels")
                if home_tab and reels_tab:
                    x0, y0 = home_tab["center"]
                    x1, y1 = reels_tab["center"]
                    log(f"drag test: Home {home_tab['center']} -> "
                        f"Reels {reels_tab['center']} over 1200 ms")
                    subprocess.Popen(["adb", "-s", SER, "shell",
                                      "input", "swipe",
                                      str(x0), str(y0), str(x1), str(y1),
                                      "1200"])
                    time.sleep(0.48)  # ~40% through the swipe
                    screenshot("shot_drag_mid")
                    # Swipe ends 1.2 s after it started; then wait the
                    # same 3 s the taps get, so the tab has time to settle
                    # (in the 1.12 dumps the Reels tab only reports
                    # selected=true once the viewer has fully loaded).
                    time.sleep(3.0)
                    screenshot("shot_drag_after")
                    nodes_drag_after = parse_dump(dump("step_drag_after"))
                    selected = [n["desc"] for n in nodes_drag_after
                                if n.get("selected")
                                and n["desc"] in
                                ("Home", "Reels", "Message",
                                 "Search and explore", "Profile")]
                    switched = "Reels" in selected
                    drag_result = ("DRAG_SWITCHED_TO_REELS"
                                   if switched else "DRAG_NO_SWITCH")
                    log(f"drag test: {drag_result} "
                        f"(selected now: {selected})")
                    STATUS["drag_test"] = {
                        "result": drag_result,
                        "from": list(home_tab["center"]),
                        "to": list(reels_tab["center"]),
                        "selected_after": selected,
                        "mid_shot": "shot_drag_mid.png",
                        "after_shot": "shot_drag_after.png",
                    }
                else:
                    log("drag test skipped: Home/Reels tab not found")
                    STATUS["drag_test"] = {"result": "DRAG_SKIPPED"}
            except Exception as e:
                log(f"drag test error (non-fatal): {e}")
                STATUS["drag_test"] = {"result": "DRAG_ERROR",
                                       "error": str(e)}
            return finish("LOGGED_IN_FEED", "home feed + 8-tap sequence "
                          "captured (home/reels/direct/profile x2); "
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
            btn = find_exact(nodes, "Don't allow", "Don’t allow") or \
                find(nodes, "Don't allow")
            if btn:
                log("system notification-permission dialog "
                    "('Allow Rdx gram to send you notifications?'); "
                    "tapping Don't allow")
                tap(*btn["center"])
                time.sleep(2)
                continue
            screenshot("shot_notif_dialog")
            return finish("STUCK_NOTIF_DIALOG",
                          "notification-permission dialog has no "
                          "Don't allow button")

        if state in ("FIND_PEOPLE", "INTERSTITIAL", "PHOTO"):
            if tap_skip(nodes):
                time.sleep(3)
                continue
            if tap_next(nodes):
                time.sleep(3)
                continue
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
