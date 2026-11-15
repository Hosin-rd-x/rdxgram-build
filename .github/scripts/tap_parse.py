#!/usr/bin/env python3
"""Parse a uiautomator UI dump and print tap targets for the probe.

Usage: tap_parse.py <ui.xml> [target1,target2,...]

Prints a node listing (text/desc/clickable/bounds) and, when found:
  FILL_USER <x> <y>   centre of the username EditText (content-desc starts
                      with "Username")
  FILL_PASS <x> <y>   centre of the password EditText (content-desc starts
                      with "Password")
  TARGET '<text>'     which target text was matched
  TAP <x> <y>         centre of the first target node (clickable preferred)

Target matching uses the text node's bounds regardless of its clickable
flag: the clickable container is usually the parent, and tapping the text
centre hits it. The target list defaults to "Log in".
"""
import re
import sys


def main():
    xml_path = sys.argv[1]
    targets = sys.argv[2].split(",") if len(sys.argv) > 2 else ["Log in"]
    try:
        xml = open(xml_path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print("NO_UI_XML", e)
        return 0
    nodes = re.findall(r"<node[^>]*>", xml)
    print(f"nodes={len(nodes)}")
    for n in nodes:
        t = re.search(r'text="([^"]*)"', n)
        d = re.search(r'content-desc="([^"]*)"', n)
        c = re.search(r'clickable="(true|false)"', n)
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', n)
        cls = re.search(r'class="([^"]*)"', n)
        if (t and t.group(1)) or (d and d.group(1)):
            print(
                f"  clickable={c.group(1) if c else '?'} "
                f"class={cls.group(1) if cls else '?'} "
                f"text={t.group(1) if t else ''!r} "
                f"desc={d.group(1) if d else ''!r} "
                f"bounds={b.groups() if b else None}"
            )

    def centre(n):
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', n)
        if not b:
            return None
        x1, y1, x2, y2 = map(int, b.groups())
        return (x1 + x2) // 2, (y1 + y2) // 2

    # credential fields (login form): EditText by content-desc prefix
    for label, prefix in (("FILL_USER", "Username"), ("FILL_PASS", "Password")):
        for n in nodes:
            d = re.search(r'content-desc="([^"]*)"', n)
            cls = re.search(r'class="([^"]*)"', n)
            if (
                d
                and d.group(1).startswith(prefix)
                and cls
                and cls.group(1).endswith("EditText")
            ):
                c = centre(n)
                if c:
                    print(f"{label} {c[0]} {c[1]}")
                break

    for want in targets:
        best = None
        for n in nodes:
            t = re.search(r'text="([^"]*)"', n)
            c = re.search(r'clickable="([^"]*)"', n)
            if t and t.group(1) == want:
                p = centre(n)
                if not p:
                    continue
                if c and c.group(1) == "true":
                    best = p
                    break
                if best is None:
                    best = p
        if best is not None:
            print(f"TARGET {want!r}")
            print(f"TAP {best[0]} {best[1]}")
            break
    else:
        print("NO_TARGET_FOUND")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
