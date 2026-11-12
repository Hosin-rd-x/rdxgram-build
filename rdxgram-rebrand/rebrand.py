#!/usr/bin/env python3
"""Rebrand a decoded Instagram APK (apktool output) for a side-by-side install.

Usage: rebrand.py <decoded-dir> <icons-dir>

What it does (only these, nothing else):
  1. Manifest package: com.instagram.android -> com.rdx.gram
  2. Provider authorities and custom permissions that start with the old
     package -> same suffix under com.rdx.gram (so the twin does not clash
     with the official app's providers/permissions on the same phone).
     Class names in android:name are NEVER touched.
  3. app_name string -> "Rdx gram" in every res/values*/strings.xml.
  4. Launcher icons: copies the pre-baked PNGs from <icons-dir>
     (mipmap-*/ic_launcher.png) over the decoded res/mipmap-* icons
     (ic_launcher.png and ic_launcher_round.png where present).
  5. Removes adaptive-icon XMLs in res/mipmap-anydpi-v26 (ic_launcher.xml,
     ic_launcher_round.xml) so the launcher uses the PNG icons.

Prints a report to stdout. Exits 1 only if the manifest cannot be read or
the package attribute is not found. app_name / icon problems are reported
as APP_NAME_NOT_FOUND / APP_ICON_NOT_REPLACED markers (the workflow's
verify step gates on the final APK's label and icon sizes instead).
"""
import os
import re
import shutil
import sys

OLD_PKG = "com.instagram.android"
NEW_PKG = "com.rdx.gram"
APP_NAME = "Rdx gram"


def main():
    decoded, icons_dir = sys.argv[1], sys.argv[2]
    manifest_path = os.path.join(decoded, "AndroidManifest.xml")
    if not os.path.isfile(manifest_path):
        print("MANIFEST_MISSING: " + manifest_path)
        return 1
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = fh.read()

    changes = []

    # 1. package attribute
    if 'package="' + OLD_PKG + '"' not in manifest:
        print("PACKAGE_ATTR_NOT_FOUND")
        return 1
    manifest = manifest.replace('package="' + OLD_PKG + '"', 'package="' + NEW_PKG + '"', 1)
    changes.append("manifest package -> " + NEW_PKG)

    # 2a. provider authorities
    def fix_authorities(m):
        value = m.group(1)
        if OLD_PKG in value:
            new = value.replace(OLD_PKG, NEW_PKG)
            changes.append("authority: " + value + " -> " + new)
            return 'android:authorities="' + new + '"'
        return m.group(0)

    manifest = re.sub(r'android:authorities="([^"]*)"', fix_authorities, manifest)

    # 2b. permission names: <permission>, <permission-group> and
    # <uses-permission> android:name="com.instagram.android...">.
    # Line-scoped so class names in android:name are only touched when
    # the element is a permission declaration/use.
    out_lines = []
    for line in manifest.splitlines(keepends=True):
        stripped = line.lstrip()
        if (
            stripped.startswith("<permission ")
            or stripped.startswith("<permission-group ")
            or stripped.startswith("<uses-permission ")
        ):
            new_line = re.sub(
                r'android:name="com\.instagram\.android([^"]*)"',
                lambda m: 'android:name="' + NEW_PKG + m.group(1) + '"',
                line,
            )
            if new_line != line:
                changes.append("permission line: " + line.strip()[:160])
            line = new_line
        # android:permission="com.instagram.android..." uses on components
        new_line = re.sub(
            r'android:permission="com\.instagram\.android([^"]*)"',
            lambda m: 'android:permission="' + NEW_PKG + m.group(1) + '"',
            line,
        )
        if new_line != line:
            changes.append("permission use: " + line.strip()[:160])
        out_lines.append(new_line)
    manifest = "".join(out_lines)

    # 2c. a meta-data value exactly equal to the old package (a package
    # reference, not a class name).
    manifest = re.sub(
        r'android:value="com\.instagram\.android"',
        'android:value="' + NEW_PKG + '"',
        manifest,
    )

    with open(manifest_path, "w", encoding="utf-8") as fh:
        fh.write(manifest)

    # 3. app_name in every values*/strings.xml
    app_name_files = []
    app_name_found = False
    strings_re = re.compile(r'(<string name="app_name"[^>]*>)(.*?)(</string>)', re.DOTALL)
    res_dir = os.path.join(decoded, "res")
    for root, _dirs, files in os.walk(res_dir):
        if os.path.basename(root).startswith("values") and "strings.xml" in files:
            path = os.path.join(root, "strings.xml")
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            new_text, n = strings_re.subn(lambda m: m.group(1) + APP_NAME + m.group(3), text)
            if n:
                app_name_found = True
                app_name_files.append(os.path.relpath(path, decoded) + " x%d" % n)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new_text)
    if app_name_found:
        changes.append("app_name -> %s in: %s" % (APP_NAME, ", ".join(app_name_files)))
    else:
        print("APP_NAME_NOT_FOUND: no <string name=\"app_name\"> in res/values*/strings.xml")

    # 4. launcher icons
    replaced = []
    for density in ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"):
        src = os.path.join(icons_dir, "mipmap-" + density, "ic_launcher.png")
        if not os.path.isfile(src):
            continue
        target_dir = os.path.join(res_dir, "mipmap-" + density)
        for name in ("ic_launcher.png", "ic_launcher_round.png"):
            dst = os.path.join(target_dir, name)
            if os.path.isfile(dst):
                shutil.copyfile(src, dst)
                replaced.append("mipmap-" + density + "/" + name)
    if replaced:
        changes.append("icons replaced: " + ", ".join(replaced))
    else:
        print("APP_ICON_NOT_REPLACED: no res/mipmap-*/ic_launcher.png found")

    # 5. adaptive-icon XMLs: remove so the launcher falls back to the PNGs
    anydpi = os.path.join(res_dir, "mipmap-anydpi-v26")
    removed = []
    for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
        path = os.path.join(anydpi, name)
        if os.path.isfile(path):
            os.remove(path)
            removed.append("mipmap-anydpi-v26/" + name)
    if removed:
        changes.append("adaptive icons removed: " + ", ".join(removed))

    print("REBRAND REPORT")
    for c in changes:
        print("  - " + c)
    print("REBRAND_DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
