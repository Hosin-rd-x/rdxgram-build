#!/usr/bin/env python3
"""Rebrand a decoded Instagram APK (apktool output) for a side-by-side install.

Usage: rebrand.py <decoded-dir> <icons-dir>

What it does (only these, nothing else):
  1. Manifest package: com.instagram.android -> com.rdx.gram
  2. Provider authorities and custom permissions that start with the old
     package -> same suffix under com.rdx.gram (so the twin does not clash
     with the official app's providers/permissions on the same phone).
     Class names in android:name are NEVER touched.
     2d. prune dead (non-reference) <item type="layout"> entries from
     values*/layouts.xml; 2e. prune dangling <public> entries for
     file-based types with no file on disk; 2f. prune dangling
     @layout refs inside values*/styles.xml (run 43155415001 failed
     exactly on those 10 layouts); 2h. prune dangling @layout refs
     inside res/layout*/menu*/xml* files (<include> elements and
     *layout attributes) and <item>@layout</item> in other values
     XMLs (the run after 2f failed exactly on 18 such layouts from
     3 layout files — aapt2 reports only the first ~20 errors, so
     each fix reveals the next batch). 2g. launcher label, literal
     "Rdx gram" in the manifest (see below).
  3. Label string value in every res/values*/strings.xml: IG 451 has
     NO app_name string — the label is a shrunk string whose public.xml
     name is "(name removed)" (id 0x7f130009) and whose value is
     "Instagram". Rewrite that value to "Rdx gram" (belt-and-suspenders
     for the literal manifest labels of 2g); an app_name entry, if it
     ever exists, is rewritten too.
  4. Launcher icons: IG 451 has NO ic_launcher.png at all — the app
     icon is @mipmap/icon (a PNG per density + an adaptive-icon XML
     in the anydpi config whose background/foreground are
     ig_launcher_background / ig_launcher_foreground and whose
     monochrome layer is IG's own glyph). Copies the pre-baked PNGs
     from <icons-dir> over the decoded res/mipmap-* files:
     ic_launcher.png -> icon.png, ig_launcher_background.png,
     ig_launcher_foreground.png, and internal_icon (icon of the
     disabled InternalLauncher alias) in its stock per-density format
     (webp mdpi/hdpi/xhdpi, png xxhdpi/xxxhdpi).
  5. Adaptive icon XMLs (res/mipmap-*/icon.xml): strip the
     <monochrome .../> element so a themed launcher falls back to the
     normal icon instead of IG's glyph. Legacy removal of
     ic_launcher.xml / ic_launcher_round.xml in mipmap-anydpi-v26
     is kept.

NOTE: the workflow strips requiredSplitTypes from the stock APK
_before_ apktool decodes it (see strip_required_splits.py) — the
stock Instagram is a Play-bundle build whose manifest declares
requiredSplitTypes='base__density', and the density split is NOT
inside the single APK; without the strip a clean device refuses the
install with INSTALL_FAILED_MISSING_SPLIT.

Prints a report to stdout. Exits 1 only if the manifest cannot be read or
the package attribute is not found. Label/icon problems are reported
as markers in the report (the workflow's verify step gates on the
final APK's label and icon sizes instead).
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

    # 2g. Launcher label, literal "Rdx gram" (runs before the manifest
    # is written — it edits the manifest text). IG 451 has NO app_name
    # string: android:label is a shrunk string id everywhere
    # (application, LauncherActivity, InstagramMainActivity, and the
    # MainTabActivity / InternalLauncher / themed-icon aliases):
    # public.xml says <public type="string" name="(name removed)"
    # id="0x7f130009"> and the strings.xml value is "Instagram".
    # Replace every such reference with the literal label. The
    # application tag is forced to carry a literal label too (inserted
    # if the tag has none at all). The string's value is rewritten in
    # step 3 as a belt-and-suspenders fallback.
    label_id = "0x7f130009"
    label_name = None
    label_public_path = os.path.join(decoded, "res", "values", "public.xml")
    if os.path.isfile(label_public_path):
        with open(label_public_path, "r", encoding="utf-8") as fh:
            _pub = fh.read()
        _m = re.search(
            r'<public[^>]+type="string"[^>]+name="([^"]+)"[^>]+id="0x7f130009"',
            _pub,
        ) or re.search(
            r'<public[^>]+id="0x7f130009"[^>]+name="([^"]+)"', _pub
        )
        if _m:
            label_name = _m.group(1)
    _refs = []
    if label_name:
        _refs.append("@string/" + label_name)
    _refs.append("@" + label_id)
    _label_n = 0
    for _ref in _refs:
        manifest, _n = re.subn(
            r'android:label="' + re.escape(_ref) + '"',
            'android:label="' + APP_NAME + '"',
            manifest,
        )
        _label_n += _n
    _app = re.search(r"<application\b[^>]*>", manifest)
    if _app:
        _tag = _app.group(0)
        if "android:label=" in _tag:
            _newtag = re.sub(
                r'android:label="[^"]*"',
                'android:label="' + APP_NAME + '"',
                _tag,
            )
        else:
            _newtag = _tag[:-1] + ' android:label="' + APP_NAME + '">'
        if _newtag != _tag:
            manifest = manifest[: _app.start()] + _newtag + manifest[_app.end():]
            _label_n += 1
    changes.append(
        "label literal 'Rdx gram': %d manifest label(s) replaced "
        "(refs %r, string name %r)"
        % (_label_n, _refs, label_name)
    )
    # Keep the label name for step 3 (strings.xml value patch).
    _label_name_for_strings = label_name

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

    # 2f. Prune dangling @layout refs inside styles.xml: Instagram's
    # resource shrinking strips some layout XML files but leaves style
    # items pointing at them, and aapt2 then fails the link with
    # "resource layout/<name> not found" (side-by-side run 43155415001
    # failed exactly on 10 such layouts in styles.xml: the 3 framework
    # select_dialog_*_material, bottom_sheet_*_text_view,
    # direct_blocker_composer, igds_search_row, branding_view and the
    # two igvr_ variants). Remove ONLY an <item> whose value is exactly
    # @layout/<name> with no file on disk (any res/layout* dir) and no
    # kept @-reference in layouts.xml. This follows the same rule as
    # 2d/2e: the stock APK has no file behind these names, so no live
    # code path in the stock app can inflate them either, and dropping
    # the item lets the theme fall back to its parent/default instead
    # of inventing a fake layout. A stub file would be riskier: if any
    # path ever inflates it, an empty stub returns a blank view (or a
    # cast crash) where removal just leaves the attribute unset.
    # @android:layout/... refs are framework refs and are never touched.
    import glob as _glob3
    # Layout names kept as @-references in layouts.xml (recomputed here
    # so 2f does not depend on public.xml existing, unlike 2e's local).
    ref_layouts_2f = set()
    for lx in sorted(_glob3.glob(os.path.join(decoded, "res", "values*", "layouts.xml"))):
        with open(lx, "r", encoding="utf-8") as fh:
            for m in re.finditer(r'<item\s+type="layout"\s+name="([^"]+)"[^>]*>@', fh.read()):
                ref_layouts_2f.add(m.group(1))
    existing_layouts = set(ref_layouts_2f)
    for _ld in _glob3.glob(os.path.join(decoded, "res", "layout*")):
        if not os.path.isdir(_ld):
            continue
        for _f in os.listdir(_ld):
            if _f.endswith(".xml"):
                existing_layouts.add(_f[:-4])
    style_item_re = re.compile(
        r'<item\s+name="([^"]+)"[^>]*>\s*@layout/([A-Za-z0-9_]+)\s*</item>'
    )
    for sx in sorted(_glob3.glob(os.path.join(decoded, "res", "values*", "styles.xml"))):
        with open(sx, "r", encoding="utf-8") as fh:
            scontent = fh.read()
        removed_styles = []
        def _fix_style(m):
            if m.group(2) in existing_layouts:
                return m.group(0)
            removed_styles.append(m.group(2))
            return ""
        new_scontent = style_item_re.sub(_fix_style, scontent)
        if removed_styles:
            with open(sx, "w", encoding="utf-8") as fh:
                fh.write(new_scontent)
            changes.append(
                "styles sanitize %s: removed %d dangling @layout items (%s)"
                % (os.path.relpath(sx, decoded), len(removed_styles),
                   ", ".join(sorted(set(removed_styles))))
            )

    # 2h. Prune dangling @layout references in layout/menu/xml resource
    # files. The aapt2 link in the run right after 2f was added failed
    # on exactly these (18 unique layouts, e.g. action_bar,
    # bottom_sheet_container, the layout_tagging_* set) referenced from
    # res/layout/*.xml — aapt2 reports only the first ~20 errors, so
    # each fix reveals the next batch (2d -> 2e -> 2f -> this one).
    # Same rule as 2f: a layout with no file on disk and no kept
    # @-reference in layouts.xml cannot be inflated by any live code
    # path in the stock app either, so removing the reference is safe
    # (far safer than a stub: a stub would render as a blank view or a
    # cast crash if any path ever inflates it).
    #  - values XMLs other than layouts.xml: drop <item>@layout/X</item>
    #    where X is missing (2f did this only for styles.xml).
    #  - layout/menu/xml files: drop a whole <include layout="@layout/X">
    #    element where X is missing, and drop any *layout="@layout/X"
    #    attribute where X is missing (ViewStub / fragment /
    #    preference android:layout / widgetLayout / actionLayout).
    import glob as _glob4
    dangling_layouts_2h = set()
    item_re_2h = re.compile(
        r'<item\s+name="([^"]+)"[^>]*>\s*@layout/([A-Za-z0-9_]+)\s*</item>'
    )
    for vx in sorted(_glob4.glob(os.path.join(decoded, "res", "values*", "*.xml"))):
        if os.path.basename(vx) == "layouts.xml":
            continue
        with open(vx, "r", encoding="utf-8") as fh:
            vcontent = fh.read()
        removed_v = []
        def _fix_v(m):
            if m.group(2) in existing_layouts:
                return m.group(0)
            removed_v.append(m.group(2))
            return ""
        new_v = item_re_2h.sub(_fix_v, vcontent)
        if removed_v:
            with open(vx, "w", encoding="utf-8") as fh:
                fh.write(new_v)
            dangling_layouts_2h.update(removed_v)
            changes.append(
                "values sanitize %s: removed %d dangling @layout items (%s)"
                % (os.path.relpath(vx, decoded), len(removed_v),
                   ", ".join(sorted(set(removed_v))))
            )
    include_re_2h = re.compile(
        r'<include\b[^>]*?(?:/>|>.*?</include>)', re.DOTALL
    )
    layout_attr_re_2h = re.compile(
        r'([\s][\w:]*(?:[Ll]ayout))="@layout/([A-Za-z0-9_]+)"'
    )
    for sub in ("layout", "menu", "xml"):
        for _f in sorted(_glob4.glob(os.path.join(decoded, "res", sub + "*", "*.xml"))):
            with open(_f, "r", encoding="utf-8") as fh:
                content = fh.read()
            removed_inc = []
            def _fix_inc(m):
                tag = m.group(0)
                lm = re.search(r'layout="@layout/([A-Za-z0-9_]+)"', tag.split(">", 1)[0])
                if lm is None:
                    return tag
                if lm.group(1) in existing_layouts:
                    return tag
                removed_inc.append(lm.group(1))
                return ""
            content = include_re_2h.sub(_fix_inc, content)
            removed_attr = []
            def _fix_attr(m):
                if m.group(2) in existing_layouts:
                    return m.group(0)
                removed_attr.append(m.group(2))
                return ""
            content = layout_attr_re_2h.sub(_fix_attr, content)
            gone = sorted(set(removed_inc + removed_attr))
            if gone:
                with open(_f, "w", encoding="utf-8") as fh:
                    fh.write(content)
                dangling_layouts_2h.update(gone)
                changes.append(
                    "layout sanitize %s: removed %d dangling @layout ref(s) (%s)"
                    % (os.path.relpath(_f, decoded), len(gone), ", ".join(gone))
                )
    if dangling_layouts_2h:
        changes.append(
            "2h total: %d distinct dangling layout names pruned from resource XMLs"
            % len(dangling_layouts_2h)
        )

    # 3. Label string value in every values*/strings.xml
    # (belt-and-suspenders for the literal manifest labels of 2g):
    # rewrite the shrunk label string's value to "Rdx gram" so any
    # label reference the manifest pass missed still reads the new
    # name. Also rewrite app_name if it ever exists (it does not on
    # IG 451 — the missing app_name is expected, not a failure).
    res_dir = os.path.join(decoded, "res")
    label_value_files = []
    label_value_n = 0
    if _label_name_for_strings:
        label_value_re = re.compile(
            r'(<string name="' + re.escape(_label_name_for_strings) + r'"[^>]*>)(.*?)(</string>)',
            re.DOTALL,
        )
        for root, _dirs, files in os.walk(res_dir):
            if os.path.basename(root).startswith("values") and "strings.xml" in files:
                path = os.path.join(root, "strings.xml")
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
                new_text, n = label_value_re.subn(
                    lambda m: m.group(1) + APP_NAME + m.group(3), text
                )
                if n:
                    label_value_n += n
                    label_value_files.append(os.path.relpath(path, decoded) + " x%d" % n)
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(new_text)
    if label_value_n:
        changes.append(
            "label string value -> %s (%d) in: %s"
            % (APP_NAME, label_value_n, ", ".join(label_value_files))
        )
    else:
        print(
            "LABEL_STRING_NOT_PATCHED: no <string name=%r> in res/values*/strings.xml"
            % (_label_name_for_strings,)
        )
    app_name_files = []
    app_name_found = False
    strings_re = re.compile(r'(<string name="app_name"[^>]*>)(.*?)(</string>)', re.DOTALL)
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
        print("APP_NAME_ABSENT (expected on IG 451): no <string name=\"app_name\"> — literal manifest labels (2g) cover the name")

    # 4. launcher icons. IG 451 has NO ic_launcher.png at all — the
    # app icon is @mipmap/icon (a PNG per density + an adaptive-icon
    # XML in the anydpi config whose background/foreground are
    # ig_launcher_background / ig_launcher_foreground and whose
    # monochrome layer is IG's own glyph). Replace all three PNG names
    # per density from the pre-baked <icons-dir> files, plus
    # internal_icon (icon of the disabled InternalLauncher alias) in
    # its stock per-density format. Keep the legacy ic_launcher*.png
    # copy too (no-op on IG 451).
    replaced = []
    for density in ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"):
        target_dir = os.path.join(res_dir, "mipmap-" + density)
        for src_name, dst_name in (
            ("ic_launcher.png", "icon.png"),
            ("ig_launcher_background.png", "ig_launcher_background.png"),
            ("ig_launcher_foreground.png", "ig_launcher_foreground.png"),
        ):
            src = os.path.join(icons_dir, "mipmap-" + density, src_name)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(target_dir, dst_name)
            if os.path.isfile(dst):
                shutil.copyfile(src, dst)
                replaced.append("mipmap-" + density + "/" + dst_name)
        # internal_icon keeps its stock per-density format
        int_name = "internal_icon.webp" if density in ("mdpi", "hdpi", "xhdpi") else "internal_icon.png"
        src = os.path.join(icons_dir, "mipmap-" + density, int_name)
        dst = os.path.join(target_dir, int_name)
        if os.path.isfile(src) and os.path.isfile(dst):
            shutil.copyfile(src, dst)
            replaced.append("mipmap-" + density + "/" + int_name)
    if replaced:
        changes.append("icons replaced: " + ", ".join(replaced))
    else:
        print("APP_ICON_NOT_REPLACED: no res/mipmap-*/icon.png or layer PNGs found")

    # 5. Adaptive icon XMLs (res/mipmap-*/icon.xml, the anydpi config):
    # strip the <monochrome .../> element so a themed launcher falls
    # back to the normal icon instead of IG's glyph; leave the
    # background/foreground references alone (their PNGs were replaced
    # in step 4). Legacy removal of ic_launcher.xml /
    # ic_launcher_round.xml in mipmap-anydpi-v26 is kept.
    mono_removed = []
    for root, _dirs, files in os.walk(res_dir):
        if os.path.basename(root).startswith("mipmap") and "icon.xml" in files:
            path = os.path.join(root, "icon.xml")
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                txt = fh.read()
            if "adaptive-icon" not in txt:
                continue
            new_txt, n = re.subn(r"<monochrome\b[^>]*/>", "", txt)
            if n:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new_txt)
                mono_removed.append(os.path.relpath(path, decoded))
    if mono_removed:
        changes.append("adaptive icons: monochrome removed from: " + ", ".join(mono_removed))
    else:
        print("MONOCHROME_NOT_FOUND: no <monochrome> in res/mipmap-*/icon.xml (already clean?)")
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
