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
        new = None
        if value.startswith(OLD_PKG):
            new = NEW_PKG + value[len(OLD_PKG):]
        elif value.startswith("com.instagram."):
            new = NEW_PKG + value[len("com.instagram"):]
        elif value.startswith("com.facebook."):
            new = NEW_PKG + value[len("com.facebook"):]
        if new is not None and new != value:
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

    # 2d. Sanitize values*/layouts.xml: apktool decodes some <item
    # type="layout"> entries to non-reference values (dead entries whose
    # layout file was stripped by Instagram's resource shrinking) and
    # aapt2 refuses them ("invalid value for type 'layout'. Expected a
    # reference"). Remove those items; entries with a real @reference
    # value are kept. Report what the invalid values looked like.
    import glob as _glob
    layout_item_re = re.compile(
        r'<item\s+type="layout"[^>]*>(.*?)</item>', re.DOTALL
    )
    for lx in sorted(_glob.glob(os.path.join(decoded, "res", "values*", "layouts.xml"))):
        with open(lx, "r", encoding="utf-8") as fh:
            content = fh.read()
        removed = []
        kept = [0]
        def _fix(m):
            val = m.group(1).strip()
            if val.startswith("@"):
                kept[0] += 1
                return m.group(0)
            removed.append(val[:80])
            return ""
        new_content = layout_item_re.sub(_fix, content)
        if removed:
            with open(lx, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            changes.append(
                f"layouts sanitize {os.path.relpath(lx, decoded)}: "
                f"removed {len(removed)} non-reference layout items "
                f"(e.g. {removed[:3]!r}), kept {kept[0]}"
            )

    # 2e. Prune dangling <public> entries: Instagram's resource shrinking
    # strips some layout XML files but apktool still writes their names
    # into res/values/public.xml, and aapt2 then fails the link with
    # "no definition for declared symbol 'com.rdx.gram:layout/<name>'".
    # (Side-by-side run 43136930351 failed exactly on 20 such layouts:
    # ac_transition_top_banner, account_row, action_bar, ... — the
    # previous run 43136423466 had failed one layer earlier on the
    # layouts.xml items that 2d now removes.) A <public> entry is
    # removed ONLY when no file on disk defines that resource, and
    # only for purely file-based types (layout, drawable, mipmap, anim,
    # animator, raw, xml, menu, font). Value-based types (string,
    # style, dimen, id, attr, ...) live in values XMLs and are never
    # touched. The freed IDs simply go unused: the stock APK's table
    # also has no file behind them, so no live code path can inflate
    # them, and the remaining ~29k entries keep their original IDs.
    import glob as _glob2
    public_path = os.path.join(decoded, "res", "values", "public.xml")
    if os.path.isfile(public_path):
        with open(public_path, "r", encoding="utf-8") as fh:
            public_lines = fh.read().splitlines(keepends=True)
        # layout names still defined by a kept @-reference item in
        # values*/layouts.xml (after 2d) count as defined.
        ref_layouts = set()
        for lx in sorted(_glob2.glob(os.path.join(decoded, "res", "values*", "layouts.xml"))):
            with open(lx, "r", encoding="utf-8") as fh:
                for m in re.finditer(r'<item\s+type="layout"\s+name="([^"]+)"[^>]*>@', fh.read()):
                    ref_layouts.add(m.group(1))
        file_type_dirs = {
            "layout": ("layout", (".xml",)),
            "drawable": ("drawable", (".xml", ".png", ".jpg", ".jpeg", ".webp", ".9.png")),
            "mipmap": ("mipmap", (".xml", ".png", ".jpg", ".jpeg", ".webp")),
            "anim": ("anim", (".xml",)),
            "animator": ("animator", (".xml",)),
            "raw": ("raw", None),
            "xml": ("xml", (".xml",)),
            "menu": ("menu", (".xml",)),
            "font": ("font", None),
        }
        public_re = re.compile(r'<public\s+type="([^"]+)"\s+name="([^"]+)"')
        pruned = []
        kept_lines = []
        for line in public_lines:
            m = public_re.search(line)
            if not m or m.group(1) not in file_type_dirs:
                kept_lines.append(line)
                continue
            rtype, rname = m.group(1), m.group(2)
            if rtype == "layout" and rname in ref_layouts:
                kept_lines.append(line)
                continue
            prefix, exts = file_type_dirs[rtype]
            found = False
            for d in _glob2.glob(os.path.join(decoded, "res", prefix + "*")):
                if not os.path.isdir(d):
                    continue
                if exts is None:
                    if any(os.path.isfile(os.path.join(d, f)) and os.path.splitext(f)[0] == rname for f in os.listdir(d)):
                        found = True
                        break
                elif any(os.path.isfile(os.path.join(d, rname + e)) for e in exts):
                    found = True
                    break
            if found:
                kept_lines.append(line)
            else:
                pruned.append(rtype + "/" + rname)
        if pruned:
            with open(public_path, "w", encoding="utf-8") as fh:
                fh.writelines(kept_lines)
            changes.append(
                "public.xml pruned %d dangling %s (e.g. %s)"
                % (len(pruned), "entries", ", ".join(pruned[:5]))
            )

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
