#!/usr/bin/env python3
"""Verify an APK's binary AndroidManifest.xml without the Android SDK.

Why this exists: `aapt dump badging` fails on LSPatch-patched APKs that
went through an apktool rebuild first ("dump failed because no
AndroidManifest.xml found") even though the APK is a valid zip with a
valid manifest — aapt v1's zip reader chokes on the file, while
Android's own installer and Python's zipfile read it fine. So the
final verify step uses this script instead of aapt for the patched APK.

Reads AndroidManifest.xml from the zip, walks every START_ELEMENT and
reports:
  - <manifest> package / versionCode / versionName
  - <application> label + icon
  - every <activity> / <activity-alias> name + label (+ icon when set)
  - every intent-filter action/category (MAIN / LAUNCHER presence)

With --expect-package / --expect-label it exits non-zero on mismatch,
and it always requires at least one MAIN action and one LAUNCHER
category in the manifest (the launcher entry must exist — on IG 451
the MAIN/LAUNCHER filters live on activity-aliases, which aapt
badging does not list at all, so badging cannot prove this either).

It also prints the zip entry details for AndroidManifest.xml
(compress_type / flag_bits) — a diagnostic for the aapt failure above.

Usage:
  verify_apk_manifest.py [--expect-package PKG] [--expect-label LBL] <apk>
"""
import struct
import sys
import zipfile


def read_strings(data):
    ctype, hsize, size = struct.unpack_from("<HHI", data, 0)
    assert ctype == 0x0001, f"not a string pool: {ctype:#x}"
    count, scount, flags, sstart, ststart = struct.unpack_from("<IIIII", data, 8)
    utf8 = bool(flags & 0x100)
    offs = struct.unpack_from(f"<{count}I", data, 28)
    out = []
    for o in offs:
        p = sstart + o
        if utf8:
            def varint(p):
                b = data[p]
                if b & 0x80:
                    return ((b & 0x7F) << 8) | data[p + 1], p + 2
                return b, p + 1
            _, p = varint(p)
            ln, p = varint(p)
            out.append(data[p:p + ln].decode("utf-8", "replace"))
        else:
            ln = struct.unpack_from("<H", data, p)[0]
            p += 2
            if ln & 0x8000:
                ln = ((ln & 0x7FFF) << 16) | struct.unpack_from("<H", data, p)[0]
                p += 2
            out.append(data[p:p + ln * 2].decode("utf-16-le", "replace"))
    return out


def walk_elements(axml):
    """Yield (depth, element_name, attrs_dict) for every start element."""
    pool = axml[8:]
    strings = read_strings(pool)
    p = 8 + struct.unpack_from("<I", pool, 4)[0]
    depth = 0
    while p < len(axml):
        ctype, hsize, size = struct.unpack_from("<HHI", axml, p)
        if ctype == 0x0102:  # START_ELEMENT
            name_idx = struct.unpack_from("<I", axml, p + 20)[0]
            astart, asize, acount = struct.unpack_from("<HHH", axml, p + 24)
            attrs = {}
            for i in range(acount):
                q = p + 16 + astart + i * asize
                ns, nm, raw = struct.unpack_from("<III", axml, q)
                tsize, res0, dtype = struct.unpack_from("<HBB", axml, q + 12)
                tdata = struct.unpack_from("<I", axml, q + 16)[0]
                key = strings[nm]
                if dtype == 0x03:  # string
                    val = strings[tdata]
                elif dtype == 0x01:  # reference
                    val = f"@{tdata:#010x}"
                elif dtype == 0x10:  # int
                    val = str(tdata if tdata < 0x80000000 else tdata - 0x100000000)
                elif dtype == 0x12:  # boolean
                    val = "true" if tdata else "false"
                elif raw != 0xFFFFFFFF:
                    val = strings[raw]
                else:
                    val = f"<type {dtype:#x} data {tdata}>"
                attrs[key] = val
            yield depth, strings[name_idx], attrs
            depth += 1
        elif ctype == 0x0103:  # END_ELEMENT
            depth -= 1
        p += size


def main():
    args = sys.argv[1:]
    expect_package = None
    expect_label = None
    while args and args[0].startswith("--"):
        opt = args.pop(0)
        if opt == "--expect-package":
            expect_package = args.pop(0)
        elif opt == "--expect-label":
            expect_label = args.pop(0)
        else:
            print(f"unknown option: {opt}")
            return 2
    if len(args) != 1:
        print("usage: verify_apk_manifest.py [--expect-package PKG] "
              "[--expect-label LBL] <apk>")
        return 2
    path = args[0]
    with zipfile.ZipFile(path) as zf:
        try:
            info = zf.getinfo("AndroidManifest.xml")
        except KeyError:
            names = zf.namelist()
            print(f"MANIFEST_ENTRY_MISSING: no AndroidManifest.xml in the zip "
                  f"({len(names)} entries; manifest-like: "
                  f"{[n for n in names if 'anifest' in n]!r}; "
                  f"first 10: {names[:10]!r})")
            return 1
        print(f"zip: AndroidManifest.xml compress_type={info.compress_type} "
              f"flag_bits={info.flag_bits} size={info.file_size} "
              f"entries={len(zf.infolist())}")
        axml = zf.read("AndroidManifest.xml")

    manifest = None
    app_label = None
    app_icon = None
    activities = []  # (kind, name, label, icon)
    actions = set()
    categories = set()
    stack = []
    for depth, name, attrs in walk_elements(axml):
        while len(stack) > depth:
            stack.pop()
        stack.append(name)
        if name == "manifest":
            manifest = attrs
        elif name == "application":
            app_label = attrs.get("label")
            app_icon = attrs.get("icon")
        elif name in ("activity", "activity-alias"):
            activities.append((name, attrs.get("name"), attrs.get("label"),
                               attrs.get("icon")))
        elif name == "action" and "intent-filter" in stack:
            if attrs.get("name"):
                actions.add(attrs["name"])
        elif name == "category" and "intent-filter" in stack:
            if attrs.get("name"):
                categories.add(attrs["name"])

    if manifest is None:
        print("MANIFEST_ELEMENT_MISSING")
        return 1
    print(f"package={manifest.get('package')} "
          f"versionCode={manifest.get('versionCode')} "
          f"versionName={manifest.get('versionName')}")
    print(f"application: label={app_label!r} icon={app_icon!r}")
    for kind, aname, alabel, aicon in activities:
        if alabel is not None or aicon is not None:
            print(f"  {kind}: {aname} label={alabel!r} icon={aicon!r}")
    print(f"intent-filter actions: {sorted(actions)}")
    print(f"intent-filter categories: {sorted(categories)}")

    failed = []
    if expect_package is not None and manifest.get("package") != expect_package:
        failed.append(f"PACKAGE_MISMATCH: {manifest.get('package')} != {expect_package}")
    if expect_label is not None and app_label != expect_label:
        failed.append(f"APP_LABEL_MISMATCH: {app_label!r} != {expect_label!r}")
    launcher_labels = [l for _, _, l, _ in activities if l == expect_label]
    if expect_label is not None and not launcher_labels:
        failed.append(f"NO_ACTIVITY_WITH_LABEL: no activity/activity-alias "
                      f"has label {expect_label!r}")
    if "android.intent.action.MAIN" not in actions:
        failed.append("NO_MAIN_INTENT_FILTER")
    if "android.intent.category.LAUNCHER" not in categories:
        failed.append("NO_LAUNCHER_CATEGORY")
    if failed:
        for f in failed:
            print(f)
        return 1
    print("MANIFEST_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
