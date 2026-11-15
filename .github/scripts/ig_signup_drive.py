#!/usr/bin/env python3
"""RdxGram 1.5 signup probe — create a real Instagram test account inside
the app on Redroid and log in to the home feed.

Runs on the GitHub Actions arm runner AFTER the boot step installed and
launched the APK. Credentials arrive via environment (repo secrets) and are
NEVER printed, logged, or stored in any output file. The email confirmation
code is polled from CODE_URL (a one-time mailbox file); only its presence
and shape are logged, never its value.

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
EMAIL = os.environ["IG_EMAIL"]
PASS = os.environ["IG_PASS"]
CODE_URL = os.environ["CODE_URL"]
CANDIDATES = [c.strip() for c in
              os.environ.get("USER_CANDIDATES", "").split(",") if c.strip()]
FULL_NAME = os.environ.get("FULL_NAME", "Rdx Test")
DEADLINE = time.time() + int(os.environ.get("DEADLINE_SEC", "1440"))
CODE_WAIT_SEC = int(os.environ.get("CODE_WAIT_SEC", "600"))
STATUS = {"status": "STARTED", "username_accepted": None,
          "cold_start_total_ms": None, "fatal_count": 0,
          "steps": 0, "screenshots": [], "started_at": int(time.time()),
          "finished_at": None, "last_screen": None, "detail": ""}


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


def type_text(s):
    # spaces must be %s for `input text`; other chars go through as-is
    arg = s.replace(" ", "%s")
    shell("input", "text", arg)
    time.sleep(1)


def type_digits_slow(s):
    for ch in s:
        shell("input", "text", ch)
        time.sleep(0.3)


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
            "bounds": b,
            "center": center,
            "resource": n.get("resource-id") or "",
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


def fetch_code(timeout_sec):
    """Poll CODE_URL until the body is exactly 6 digits, or time out."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if time.time() > DEADLINE:
            return None
        try:
            req = urllib.request.Request(CODE_URL, headers={
                "User-Agent": "rdxgram-signup-probe/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", "replace").strip()
            if re.fullmatch(r"\d{6}", body):
                log("confirmation code arrived at mailbox (6 digits)")
                return body
        except Exception as e:
            log(f"code poll: {type(e).__name__} (retrying)")
        time.sleep(20)
    return None


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


def classify(nodes):
    t = low(nodes)
    descs = " ".join(n["desc"].lower() for n in nodes)
    nav_hits = sum(1 for k in ("home", "search and explore", "reels",
                               "notifications", "profile")
                   if k in descs or k in t)
    if nav_hits >= 3 or "your story" in t:
        return "FEED"
    if any(k in t for k in (
            "suspicious", "checkpoint", "confirm it's you",
            "we need to confirm", "verify your account",
            "unusual login", "help us confirm",
            "code we sent to your phone", "is this your phone number",
            "verify with a code", "add your phone number to")):
        return "CHALLENGE"
    # Login form BEFORE any single-field password/username state: it has
    # BOTH fields, and its content-descs would otherwise match PASSWORD
    # and USERNAME.
    if find_edit(nodes, "Username") and find_edit(nodes, "Password"):
        return "LOGIN_FORM"
    if any(k in t for k in ("confirmation code", "enter the code",
                            "enter code", "6-digit", "verification code")):
        return "CODE"
    # Phone screen BEFORE the email screen: its "Sign up with email"
    # link contains the word "email" and its phone field is an EditText.
    if "sign up with email" in t or "sign up with email address" in t:
        return "PHONE_OR_EMAIL"
    if any(k in t for k in ("mobile number", "phone number")):
        return "PHONE_OR_EMAIL"
    if any(k in t for k in ("email address", "what's your email",
                            "enter your email", "your email")):
        return "EMAIL"
    if any(k in t for k in ("create a password", "choose a password",
                            "set a password")) or (
            "password" in t and find_edit(nodes)):
        return "PASSWORD"
    if any(k in t for k in ("birthday", "date of birth", "how old are you")):
        return "BIRTHDAY"
    if any(k in t for k in ("create a username", "choose a username",
                            "pick a username")) or (
            "username" in t and find_edit(nodes)):
        return "USERNAME"
    if any(k in t for k in ("what's your name", "add your name",
                            "full name", "enter your name")):
        return "NAME"
    if any(k in t for k in ("create new account", "get started",
                            "join instagram", "i already have a profile")):
        return "LANDING"
    if any(k in t for k in ("profile photo", "profile picture",
                            "add a photo")):
        return "PHOTO"
    if "save your login info" in t or "save login info" in t:
        return "SAVE_LOGIN"
    if any(k in t for k in ("find people", "discover people",
                            "follow people to see")):
        return "FIND_PEOPLE"
    if any(k in t for k in ("turn on notifications", "allow notifications",
                            "enable notifications", "sync your contacts",
                            "find your friends", "add to home screen")):
        return "INTERSTITIAL"
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

    code_done = False
    username_tried = []
    stuck = {}

    for step in range(1, 61):
        STATUS["steps"] = step
        if time.time() > DEADLINE:
            return finish("TIMEOUT", "driver deadline reached")
        path = dump(f"step{step:02d}")
        nodes = parse_dump(path)
        state = classify(nodes)
        STATUS["last_screen"] = state
        log(f"step {step}: screen={state} "
            f"texts={all_text(nodes)[:300]!r}")
        save_status()

        if state == "FEED":
            log("HOME FEED REACHED — login succeeded")
            screenshot("shot_feed")
            home = find(nodes, "Search and explore")
            if home:
                tap(*home["center"])
                time.sleep(3)
                screenshot("shot_explore")
            nodes2 = parse_dump(dump("step_explore"))
            prof = find(nodes2, "Profile")
            if prof:
                tap(*prof["center"])
                time.sleep(3)
                screenshot("shot_profile")
            nodes3 = parse_dump(dump("step_home2"))
            hm = find(nodes3, "Home")
            if hm:
                tap(*hm["center"])
                time.sleep(2)
                screenshot("shot_feed2")
            if not check_alive("feed screenshots"):
                return finish("CRASHED_AFTER_FEED",
                              "FATAL or dead process after reaching feed")
            return finish("LOGGED_IN_FEED", "home feed + explore + profile "
                          "captured")

        if state == "CHALLENGE":
            screenshot("shot_challenge")
            return finish("CHALLENGE",
                          f"Instagram asked for extra verification: "
                          f"{all_text(nodes)[:400]!r}")

        if state == "LANDING":
            node = find(nodes, "Create new account", "Get started",
                        "Join Instagram")
            if node:
                tap(*node["center"])
                time.sleep(3)
                continue
            node = find(nodes, "I already have a profile", "Log in")
            if node:
                tap(*node["center"])
                time.sleep(3)
                continue
            return finish("STUCK_LANDING", "landing has no usable button")

        if state == "LOGIN_FORM":
            node = find(nodes, "Sign up", "Create new account")
            if node:
                tap(*node["center"])
                time.sleep(3)
                continue
            keyevent(4)
            time.sleep(2)
            continue

        if state == "PHONE_OR_EMAIL":
            node = find(nodes, "Sign up with email",
                        "Sign up with email address")
            if node:
                tap(*node["center"])
                time.sleep(3)
                continue
            return finish("STUCK_PHONE",
                          "phone screen has no email-signup link")

        if state == "EMAIL":
            field = find_edit(nodes) or edits(nodes)[0] if edits(nodes) else None
            if not field:
                return finish("STUCK_EMAIL", "no input field on email screen")
            tap(*field["center"])
            type_text(EMAIL)
            dismiss_keyboard()
            time.sleep(1)
            nodes_chk = parse_dump(dump(f"step{step:02d}b"))
            shown = " ".join(n["text"] for n in edits(nodes_chk))
            log(f"email field now shows: {shown[:80]!r}")
            if EMAIL.split("@")[0] not in shown and "@" not in shown:
                log("email text did not land; retrying once")
                clear_field(field["center"])
                type_text(EMAIL)
                dismiss_keyboard()
            if not tap_next(nodes_chk):
                return finish("STUCK_EMAIL", "no Next button on email screen")
            time.sleep(5)
            continue

        if state == "CODE":
            if not code_done:
                log("code screen reached; polling mailbox")
                code = fetch_code(CODE_WAIT_SEC)
                if not code:
                    screenshot("shot_code_timeout")
                    return finish("CODE_TIMEOUT",
                                  "no 6-digit code arrived at mailbox in "
                                  f"{CODE_WAIT_SEC}s")
                field = find_edit(nodes)
                boxes = edits(nodes)
                target = field or (boxes[0] if boxes else None)
                if not target:
                    return finish("STUCK_CODE",
                                  "no input field on code screen")
                tap(*target["center"])
                type_digits_slow(code)
                code_done = True
                dismiss_keyboard()
                time.sleep(1)
                nodes_chk = parse_dump(dump(f"step{step:02d}b"))
                if any(k in low(nodes_chk) for k in
                       ("incorrect", "wrong code", "doesn't match",
                        "didn't match", "expired")):
                    screenshot("shot_code_wrong")
                    return finish("CODE_WRONG",
                                  "Instagram rejected the code")
                if not tap_next(nodes_chk):
                    log("no Next on code screen; waiting for auto-advance")
                    time.sleep(5)
                time.sleep(5)
                continue
            return finish("STUCK_CODE", "code screen appeared again after "
                          "submit")

        if state == "PASSWORD":
            field = find_edit(nodes, "Password") or find_edit(nodes)
            if not field:
                return finish("STUCK_PASSWORD",
                              "no field on password screen")
            tap(*field["center"])
            type_text(PASS)
            dismiss_keyboard()
            if not tap_next(parse_dump(dump(f"step{step:02d}b"))):
                return finish("STUCK_PASSWORD", "no Next on password screen")
            time.sleep(4)
            continue

        if state == "NAME":
            field = find_edit(nodes)
            if not field:
                return finish("STUCK_NAME", "no field on name screen")
            tap(*field["center"])
            type_text(FULL_NAME)
            dismiss_keyboard()
            if not tap_next(parse_dump(dump(f"step{step:02d}b"))):
                return finish("STUCK_NAME", "no Next on name screen")
            time.sleep(4)
            continue

        if state == "USERNAME":
            field = find_edit(nodes, "Username") or find_edit(nodes)
            if not field:
                return finish("STUCK_USERNAME",
                              "no field on username screen")
            current = field["text"].strip()
            if current and len(current) >= 3 and current not in username_tried:
                STATUS["username_accepted"] = current
                log(f"using suggested username (recorded in status.json)")
                save_status()
                if not tap_next(nodes):
                    return finish("STUCK_USERNAME",
                                  "no Next on username screen")
                time.sleep(4)
                continue
            progressed = False
            for cand in CANDIDATES:
                if cand in username_tried:
                    continue
                username_tried.append(cand)
                clear_field(field["center"])
                type_text(cand)
                dismiss_keyboard()
                time.sleep(1)
                if not tap_next(parse_dump(dump(f"step{step:02d}b"))):
                    return finish("STUCK_USERNAME",
                                  "no Next on username screen")
                time.sleep(4)
                nodes_chk = parse_dump(dump(f"step{step:02d}c"))
                t = low(nodes_chk)
                if any(k in t for k in ("not available", "isn't available",
                                        "already taken", "try another",
                                        "can't use", "cannot use")):
                    log(f"username taken, trying next candidate")
                    continue
                if classify(nodes_chk) != "USERNAME":
                    STATUS["username_accepted"] = cand
                    log("username accepted (recorded in status.json)")
                    save_status()
                    progressed = True
                    break
                log("still on username screen without error; will retry")
                break
            if progressed:
                continue
            if len(username_tried) >= len(CANDIDATES):
                screenshot("shot_username_fail")
                return finish("USERNAME_FAILED",
                              "all username candidates rejected")
            continue

        if state == "BIRTHDAY":
            if tap_skip(nodes):
                time.sleep(3)
                continue
            fields = edits(nodes)
            if len(fields) >= 3:
                for f, val in zip(fields[:3], ("01", "01", "2000")):
                    tap(*f["center"])
                    type_text(val)
                dismiss_keyboard()
                if tap_next(parse_dump(dump(f"step{step:02d}b"))):
                    time.sleep(4)
                    continue
                return finish("BIRTHDAY_BLOCKED",
                              "birthday fields filled but no Next")
            if len(fields) == 1:
                tap(*fields[0]["center"])
                type_text("01/01/2000")
                dismiss_keyboard()
                if tap_next(parse_dump(dump(f"step{step:02d}b"))):
                    time.sleep(4)
                    continue
                return finish("BIRTHDAY_BLOCKED",
                              "birthday field filled but no Next")
            screenshot("shot_birthday")
            return finish("BIRTHDAY_BLOCKED",
                          "birthday screen has no fields or Skip I could use")

        if state in ("PHOTO", "SAVE_LOGIN", "FIND_PEOPLE", "INTERSTITIAL"):
            key = state
            stuck[key] = stuck.get(key, 0) + 1
            if tap_skip(nodes):
                time.sleep(3)
                continue
            if stuck[key] <= 1 and tap_next(nodes):
                time.sleep(3)
                continue
            screenshot(f"shot_stuck_{state.lower()}")
            return finish(f"STUCK_{state}",
                          f"no Skip/Not-now on {state} screen")

        # UNKNOWN
        if tap_skip(nodes):
            time.sleep(3)
            continue
        screenshot(f"shot_unknown_{step:02d}")
        return finish("UNKNOWN_SCREEN",
                      f"unrecognized screen: {all_text(nodes)[:400]!r}")

    return finish("TOO_MANY_STEPS", "60 steps without reaching the feed")


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
