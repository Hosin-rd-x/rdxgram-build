#!/usr/bin/env python3
"""Rebrand a decoded Instagram APK (apktool output) for a side-by-side install.

Usage: rebrand.py <decoded-dir> <icons-dir> [split-drawables-dir]
       [split-drawables-2k-dir] [--keep-package]

       --keep-package: theme build — keep package com.instagram.android
       and skip the rename-only steps (A, 3, 4, 5); the launch repairs
       (2d/2e/2f/2h/2i/2j/2k) still run. The icons dir is then unused
       (pass any existing dir).

What it does (only these, nothing else):

  A. Manifest (steps 1 / 2a-2c / 2g): package com.instagram.android ->
     com.rdx.gram; provider authorities and custom permissions that
     start with the old package -> same suffix under com.rdx.gram
     (so the twin does not clash with the official app's providers /
     permissions on the same phone). Class names in android:name are
     NEVER touched. Launcher label, literal "Rdx gram" (2g).

  B. Layout value indirection — the part that decides whether the app
     launches (steps 2d / 2d2 / 2e). Stock Instagram 451 does NOT store
     its layouts as files: resources.arsc holds 6,049 layout entries
     and EVERY one is a string value — either a file path
     ("res/2mw.xml") or an indirection code ("L|215F2C|958|AC99").
     At launch the app's own inflater (X.03wi.getLayout) calls
     getString() on the layout id and the returned code tells it which
     real layout to inflate — the main activity's layout
     (0x7f0e0949 layout_activity_main_coordinator_layout) is the code
     "L|215F2C|958|AC99". apktool decodes those codes into
     res/values*/layouts.xml as <item type="layout">L|...</item>, and
     aapt2 refuses a non-reference value for a layout item ("invalid
     value for type 'layout'. Expected a reference"). v1 of this script
     DELETED all ~5,988 such items, and pruned their public.xml
     entries too — the rebuilt APK kept only 66 layouts, and launch
     died with NotFoundException: String resource ID #0x7f0e0949
     (Redroid run 43600558276). So 2d now KEEPS every code: the item
     becomes <item type="layout">@string/rdx_layout_<name></item> and
     the code itself is stored as that string resource (2d2, same
     config as the layouts.xml it came from) — getString() follows
     the reference and returns the exact original code, with the
     original resource id unchanged. 2e never prunes a <public> entry
     for a resource that is defined in a values XML (layouts.xml or
     any other), only for file-based types with neither a file nor a
     values definition on disk.

  C. Dangling @layout references (steps 2f / 2h): only references to
     a layout that has NO file AND NO layouts.xml item are removed
     (from styles.xml, other values XMLs, and <include> / *layout
     attributes in layout/menu/xml files). A layout that exists as a
     layouts.xml item (a kept "L|..." code) counts as defined and its
     references are kept — removing them would break the inflation
     the app itself performs.

  D2. Play-split holes (step 2i): the stock APK is only the BASE apk
     of a Play bundle (it declares requiredSplitTypes='base__density'),
     and a few resources live only in a config split, so their slots
     in the base resources.arsc are holes. Three of them are
     dimensions the launch theme needs, and their style items decode
     as @null — the first one kills launch on ANY sideloaded base
     build (stock included, Redroid run 43603677487): the main
     layout's tab bar and container margins use ?tabBarHeight, and
     Base.Theme.Instagram defines it as a reference to dimen
     0x7f070263, which is absent, so TypedArray.getDimensionPixelSize
     throws "Failed to resolve attribute ... 0x7f040d3e". 2i repairs
     the three dimension holes by creating each missing dimen as a
     REAL dimension resource at its original id (a <dimen> in
     res/values/rdx_split_dimens.xml + a <public> entry) and pointing
     the style item at it by REFERENCE (@dimen/...). The values come
     from the matching style/attribute/dimen mapping in the full
     InstaPro 439 APK (same codebase lineage, complete resources):
     dimen 0x7f070263 tab_bar_height_panorama = 48dp (tabBarHeight),
     0x7f0700e0 circular_avatar_stroke_width = 2px (strokeWidth),
     0x7f07014b direct_in_thread_composer_top_margin = 6dp
     (mediaViewOuterVerticalMargin). A LITERAL in the style item
     would be WRONG: layout inflation (TypedArray) accepts literals,
     but InstagramMainActivity resolves tabBarHeight with
     Theme.resolveAttribute and passes TypedValue.resourceId to
     getDimensionPixelOffset (X/00WF.A0b), and a literal has
     resourceId 0 — 1.2 crashed exactly that way on relaunch
     (Redroid run 43610901393: "Resource ID #0x0"). If a listed
     repair is not found in the decoded tree the script fails —
     a build without it cannot launch.

  D3. Play-split drawables and strings (step 2j): the same split
     also holds drawables and strings the main activity's bundled
     layouts need. The bundled layout loader (layouts.bin) references
     them by resource id, so 2j restores each one at its ORIGINAL id
     (a <public> entry + the file, or the strings.xml value): 1.1
     crashed on Redroid 43606156665 with NotFoundException "Drawable
     (missing name) with resource ID #0x7f0831d1" while inflating
     IgSimpleImageView at line 103 of layout_action_bar_new_title_
     container. The missing ids were found by auditing the bundled
     layouts the main activity inflates (layouts.bin, decompressed
     from assets/layouts.bin.spo, XZ stream verified against
     layouts.bin.sha256) and cross-checking each one against the
     full InstaPro 439 APK (same codebase lineage): the drawable at
     each hole sits between the same alphabetical neighbours in
     both tables, and InstaPro's own bundled layouts show the same
     element with the same name. Restored drawables:
     0x7f0831d1 verified_profile, 0x7f082330 instagram_chevron_down_
     pano_filled_12, 0x7f082a1d instagram_x_pano_outline_8,
     0x7f0822cc instagram_call_pano_filled_12, 0x7f081e6b from_meta_
     attribution, 0x7f082190 instagram (the splash logo, 109dp).
     Their files live in rdxgram-rebrand/split-drawables/ (PNG/WebP
     copied from the full InstaPro 439 APK — Instagram's own icon
     files, same lineage as the base APK). Restored strings are
     server-downloaded (DownloadedIgResources) so their names and
     values are in no APK's resource table; they are restored with
     placeholder names (rdx_split_string_*) and values ('Back' for
     the back button's contentDescription, empty otherwise) — the
     value only has to exist so getText() does not throw, and
     contentDescription strings are never shown on screen.
     NOTE: restoring strings at their original high ids (up to
     0x8fcd) makes aapt2 size every string type-spec chunk for
     ~36,835 entries, in all ~105 string configs, so resources.arsc
     grows by ~12.7 MB (9.0 -> 21.7 MB) and the APK by ~13 MB
     (152 -> 165 MB). That is the price of the original ids, and
     the ids are what the bundled layouts reference, so it stays.

  D4. Play-split XML drawables (step 2k): the 1.3 probe (run
     43612809179) got past the main activity and the signed-out
     Bloks screen, then crashed opening the login modal:
     NotFoundException "Drawable com.rdx.gram:drawable/input_
     background with resource ID #0x7f082186" while a Bloks
     FlexLayout measured the login form. input_background is a
     selector whose two items apktool decoded as @null — but the
     stock APK's own compiled XML references 0x7f082185 (input)
     and 0x7f082188 (input_highlighted), two 9-patches that live
     only in the Play density split; a selector whose items are
     @null cannot load (loadDrawableForCookie throws). apktool
     renders EVERY dangling reference as @null, so the same trap
     hides in all XML drawables. 2k was built from a full audit
     of the 5,484 drawable XML files in the stock APK (androguard
     AXML parse of each, references checked against the stock
     arsc): 1,760 files reference a hole, but only 130 files with
     throwing root types (selector, layer-list, ripple, inset,
     scale, clip, animated-selector, animated-vector, level-list,
     transition, shape) can crash on load — 215 references, 148
     distinct holes. The other 1,630 files are Instagram/Facebook
     custom wrappers (AppFbIconDrawable, PrismSwappingDrawable,
     ...) whose own code tolerates a missing original (the main
     activity already renders with hundreds of them missing), so
     they are left alone. The 148 holes were identified by the
     same alphabetical-neighbour alignment with InstaPro 439 as
     2j (stock ids are alphabetical by name; a gap of N holes
     between two present names maps to the N InstaPro names
     between the same names): 123 identified (119 images, 2
     AppRedrawableDrawable stubs, 2 dimens), 25 unidentified
     (version drift between 439 and 451 breaks the count in
     their gaps — listed in the data file, left @null, to be
     fixed if a probe ever names their file). 2k restores the
     images + stubs + dimens at their original ids (data file
     rdxgram-rebrand/split-restores-2k.json; image files in
     rdxgram-rebrand/split-drawables-2k/) and rewrites the @nulls
     in 131 XML files to @drawable/@dimen references, in document
     order, verified at generation time by a parallel walk of the
     stock compiled XML and the decoded XML. The two
     AppRedrawableDrawable stubs (direct_reply_bar_voice_message_
     indicator, stories_background_color_picker_color_picker_
     noshadow) are server-asset handles, not files: the stub XML
     is all the APK needs to instantiate the class; the bitmap
     itself downloads from Meta's asset server at runtime (or
     shows nothing if it cannot). The two extra dimens are
     direct_composer_background_corner_radius 25dp (0x7f070146)
     and tab_bar_height_whiteout 48dp (0x7f070264).


  D. Label string value (step 3): the shrunk label string's value in
     every res/values*/strings.xml becomes "Rdx gram" (belt-and-
     suspenders for the literal manifest labels of 2g). IG 451 has NO
     app_name string — the label is a shrunk string whose public.xml
     name is "(name removed)" (id 0x7f130009) and whose value is
     "Instagram".

  E. Launcher icons (steps 4 / 5): IG 451 has NO ic_launcher.png —
     the app icon is @mipmap/icon (a PNG per density + an
     adaptive-icon XML in the anydpi config whose background /
     foreground are ig_launcher_background / ig_launcher_foreground
     and whose monochrome layer is IG's own glyph). Copies the
     pre-baked PNGs from <icons-dir> over the decoded
     res/mipmap-* files; strips <monochrome/> from the adaptive-icon
     XMLs so a themed launcher falls back to the normal icon.

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


def _xml_escape(text):
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _value_defined_items(decoded):
    """{type: {names}} defined by <item type=... name=...> in
    res/values*/*.xml, excluding public.xml itself (it declares ids,
    it does not define values). A name listed here is a real
    definition aapt2 can link against, even when no file backs it."""
    defined = {}
    import glob as _g

    item_open_re = re.compile(r"<item\b[^>]*>")
    for vx in _g.glob(os.path.join(decoded, "res", "values*", "*.xml")):
        if os.path.basename(vx) == "public.xml":
            continue
        with open(vx, "r", encoding="utf-8") as fh:
            text = fh.read()
        for tag in item_open_re.findall(text):
            tm = re.search(r'\btype="([^"]+)"', tag)
            nm = re.search(r'\bname="([^"]+)"', tag)
            if tm and nm:
                defined.setdefault(tm.group(1), set()).add(nm.group(1))
    return defined


def _layout_names_defined(decoded):
    """Names of every <item type="layout"> in res/values*/layouts.xml
    — the kept "L|..." codes of step 2d and any file-backed layout
    apktool decoded there."""
    names = set()
    import glob as _g

    for lx in _g.glob(os.path.join(decoded, "res", "values*", "layouts.xml")):
        with open(lx, "r", encoding="utf-8") as fh:
            for m in re.finditer(
                r'<item\b[^>]*\btype="layout"[^>]*\bname="([^"]+)"', fh.read()
            ):
                names.add(m.group(1))
    return names


def _existing_layouts(decoded):
    """Layouts the app can inflate: a layouts.xml item (a kept code)
    or a layout file on disk. Anything else is dangling."""
    names = _layout_names_defined(decoded)
    import glob as _g

    for ld in _g.glob(os.path.join(decoded, "res", "layout*")):
        if not os.path.isdir(ld):
            continue
        for f in os.listdir(ld):
            if f.endswith(".xml"):
                names.add(f[:-4])
    return names


def _insert_public_entry(lines, rtype, name, rid):
    """Insert '<public type=... name=... id=... />' into public.xml
    lines, in id order among the entries of the same type. Returns
    the new list of lines. Raises ValueError on a conflicting entry
    (same id with a different name, or same name with a different
    id); returns the lines unchanged if the exact entry is already
    present (idempotent)."""
    pat = re.compile(
        r'<public\s+type="([^"]+)"\s+name="([^"]+)"\s+id="(0x[0-9a-fA-F]+)"\s*/>'
    )
    entry = (
        '    <public type="%s" name="%s" id="0x%08x" />'
        % (rtype, name, rid)
    )
    same_type = []
    for idx, line in enumerate(lines):
        m = pat.search(line)
        if not m:
            continue
        t, n, i = m.group(1), m.group(2), int(m.group(3), 16)
        if t != rtype:
            continue
        if i == rid and n == name:
            return lines
        if i == rid:
            raise ValueError(
                "public id 0x%08x already used by %s/%s" % (rid, t, n)
            )
        if n == name:
            raise ValueError(
                "public %s/%s already has id 0x%08x" % (t, n, i)
            )
        same_type.append((idx, i))
    insert_at = len(lines)
    for idx, i in reversed(same_type):
        if i < rid:
            insert_at = idx + 1
            break
    else:
        if same_type:
            insert_at = same_type[0][0]
    lines = list(lines)
    lines.insert(insert_at, entry)
    return lines


def main():
    decoded, icons_dir = sys.argv[1], sys.argv[2]
    split_dir = sys.argv[3] if len(sys.argv) > 3 else None
    # 5th argument "--keep-package": theme build — keep the stock
    # package com.instagram.android (replaces the official app) and
    # skip every rename-only step (A: package/authorities/permissions/
    # labels, step 3: label string, steps 4/5: icons). The launch
    # repairs (2d/2e/2f/2h layout indirection, 2i split dimens, 2j
    # split drawables/strings, 2k split XML drawables) still run:
    # without them even the stock APK crashes at launch (see header
    # D2/D3/D4), and the theme build used to skip them.
    keep_package = len(sys.argv) > 5 and sys.argv[5] == "--keep-package"
    manifest_path = os.path.join(decoded, "AndroidManifest.xml")
    if not os.path.isfile(manifest_path):
        print("MANIFEST_MISSING: " + manifest_path)
        return 1
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = fh.read()

    changes = []

    if not keep_package:
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
    else:
        # Keep-package mode (theme build): the stock package is kept
        # (com.instagram.android, replaces the official app), so the
        # manifest is left byte-identical and there is no label string
        # to rewrite in step 3.
        if 'package="' + OLD_PKG + '"' not in manifest:
            print("PACKAGE_ATTR_NOT_FOUND")
            return 1
        _label_name_for_strings = None
        changes.append("package kept: " + OLD_PKG)

    # 2d. Keep the layout indirection codes (see header, section B):
    # apktool decodes every "L|..." layout value into
    # res/values*/layouts.xml as <item type="layout">L|...</item> and
    # aapt2 refuses a non-reference value for a layout item ("invalid
    # value for type 'layout'. Expected a reference"). Deleting them
    # (what v1 did) deletes the app's own layouts — launch dies on
    # getString(0x7f0e0949). Instead each code is moved into a string
    # resource in the SAME config (2d2 below) and the item becomes a
    # reference to it: getString() follows the reference and returns
    # the exact original code, and the layout keeps its original id.
    # Items that already hold a reference are kept untouched; only a
    # truly empty item is removed (there is nothing to keep).
    import glob as _glob
    layout_item_re = re.compile(
        r'<item\b[^>]*\btype="layout"[^>]*>(.*?)</item>', re.DOTALL
    )

    def _existing_string_names(config_dir):
        names = set()
        sp = os.path.join(decoded, "res", config_dir, "strings.xml")
        if os.path.isfile(sp):
            with open(sp, "r", encoding="utf-8") as fh:
                for m in re.finditer(
                    r'<string\s[^>]*\bname="([^"]+)"', fh.read()
                ):
                    names.add(m.group(1))
        return names

    code_strings = {}  # config dir -> [(string_name, code)]
    for lx in sorted(_glob.glob(os.path.join(decoded, "res", "values*", "layouts.xml"))):
        config_dir = os.path.basename(os.path.dirname(lx))
        with open(lx, "r", encoding="utf-8") as fh:
            content = fh.read()
        taken = _existing_string_names(config_dir)
        converted = []
        kept = [0]
        removed = []

        def _fix(m):
            opening = m.group(0).split(">", 1)[0] + ">"
            nm = re.search(r'\bname="([^"]+)"', opening)
            val = m.group(1).strip()
            if val.startswith("@"):
                kept[0] += 1
                return m.group(0)
            if not val or nm is None:
                removed.append(nm.group(1) if nm else val[:80])
                return ""
            lname = nm.group(1)
            base = "rdx_layout_" + lname
            sname = base
            n = 2
            while sname in taken:
                sname = "%s_%d" % (base, n)
                n += 1
            taken.add(sname)
            code_strings.setdefault(config_dir, []).append((sname, val))
            converted.append(lname)
            return opening + "@string/" + sname + "</item>"

        new_content = layout_item_re.sub(_fix, content)
        if converted or removed:
            with open(lx, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            changes.append(
                f"layouts keep-codes {os.path.relpath(lx, decoded)}: "
                f"converted {len(converted)} 'L|...' values to "
                f"@string refs (e.g. {converted[:3]!r}), kept "
                f"{kept[0]} references, removed {len(removed)} empty"
            )

    # 2d2. Materialize the code strings: one <string> per converted
    # layout item, in the same config's strings.xml so the reference
    # from that config's layouts.xml resolves in that config.
    for config_dir in sorted(code_strings):
        sp = os.path.join(decoded, "res", config_dir, "strings.xml")
        if os.path.isfile(sp):
            with open(sp, "r", encoding="utf-8") as fh:
                stext = fh.read()
        else:
            stext = '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n</resources>\n'
        additions = "".join(
            '    <string name="%s">%s</string>\n' % (name, _xml_escape(code))
            for name, code in code_strings[config_dir]
        )
        if "</resources>" in stext:
            stext = stext.replace("</resources>", additions + "</resources>", 1)
        else:
            stext = stext.rstrip() + "\n" + additions + "</resources>\n"
        with open(sp, "w", encoding="utf-8") as fh:
            fh.write(stext)
        changes.append(
            "layout codes stored as strings in res/%s/strings.xml: %d"
            % (config_dir, len(code_strings[config_dir]))
        )

    # 2e. Prune dangling <public> entries: Instagram's resource shrinking
    # strips some files but apktool still writes their names into
    # res/values/public.xml, and aapt2 then fails the link with
    # "no definition for declared symbol 'com.rdx.gram:<type>/<name>'".
    # (Side-by-side run 43136930351 failed exactly on 20 such layouts.)
    # A <public> entry is removed ONLY when no file on disk defines
    # that resource AND no values XML defines it as an <item> — the
    # layouts.xml items (the kept "L|..." codes of 2d) are definitions,
    # and pruning them deletes the app's own layouts (run 43600558276:
    # layout entries fell from 6,049 to 66). Only purely file-based
    # types are candidates (layout, drawable, mipmap, anim, animator,
    # raw, xml, menu, font). Value-based types (string, style, dimen,
    # id, attr, ...) live in values XMLs and are never touched.
    import glob as _glob2
    public_path = os.path.join(decoded, "res", "values", "public.xml")
    if os.path.isfile(public_path):
        with open(public_path, "r", encoding="utf-8") as fh:
            public_lines = fh.read().splitlines(keepends=True)
        # Resources defined by an <item> in any values XML (after 2d)
        # count as defined, whatever their value is.
        value_defined = _value_defined_items(decoded)
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
            if rname in value_defined.get(rtype, set()):
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
    # layouts.xml item (a kept "L|..." code counts as defined — see 2d).
    # This follows the same rule as 2d/2e: the stock APK has no file
    # behind these names, so no live code path in the stock app can
    # inflate them either, and dropping the item lets the theme fall
    # back to its parent/default instead of inventing a fake layout.
    # A stub file would be riskier: if any path ever inflates it, an
    # empty stub returns a blank view (or a cast crash) where removal
    # just leaves the attribute unset.
    # @android:layout/... refs are framework refs and are never touched.
    import glob as _glob3
    existing_layouts = _existing_layouts(decoded)
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
    # Same rule as 2f: a layout with no file on disk and no layouts.xml
    # item (a kept "L|..." code counts as defined) cannot be inflated
    # by any live code path in the stock app either, so removing the
    # reference is safe (far safer than a stub: a stub would render as
    # a blank view or a cast crash if any path ever inflates it).
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

    # 2i. Repair the Play-split dimension holes (see header, section
    # D2): create each missing dimen as a REAL dimension resource at
    # its original id, and point the style item at it by REFERENCE.
    # (1) the dimen values (in res/values/rdx_split_dimens.xml) and
    # their <public> entries; (2) the style items in res/values/
    # styles.xml, scoped to the exact style block so an unrelated
    # style that legitimately sets the same attribute to @null is
    # untouched. A missing repair is fatal: the build cannot launch
    # without it. A LITERAL in the style item would be wrong (see
    # D2): InstagramMainActivity needs the attribute to resolve to a
    # resource id (X/00WF.A0b -> getDimensionPixelOffset).
    split_dimens = [
        # (dimen id, dimen name, literal value, why)
        (0x7F070263, "tab_bar_height_panorama", "48dp",
         "Base.Theme.Instagram tabBarHeight"),
        (0x7F0700E0, "circular_avatar_stroke_width", "2px",
         "Avatar strokeWidth"),
        (0x7F07014B, "direct_in_thread_composer_top_margin", "6dp",
         "BaseNightTheme/Theme.Instagram mediaViewOuterVerticalMargin"),
    ]
    split_repairs = [
        # (style name, attribute name, dimen name, why)
        ("Base.Theme.Instagram", "tabBarHeight",
         "tab_bar_height_panorama",
         "main layout tab bar height + container margins"),
        ("Avatar", "strokeWidth", "circular_avatar_stroke_width",
         "tab-bar profile avatar ring"),
        ("BaseNightTheme", "mediaViewOuterVerticalMargin",
         "direct_in_thread_composer_top_margin",
         "media view outer margin (dark theme)"),
        ("Theme.Instagram", "mediaViewOuterVerticalMargin",
         "direct_in_thread_composer_top_margin",
         "media view outer margin (light theme)"),
    ]
    dimens_path = os.path.join(decoded, "res", "values", "rdx_split_dimens.xml")
    dimens_lines = ['<?xml version="1.0" encoding="utf-8"?>', "<resources>"]
    for _rid, name, value, _why in split_dimens:
        dimens_lines.append('    <dimen name="%s">%s</dimen>' % (name, value))
    dimens_lines.append("</resources>")
    with open(dimens_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(dimens_lines) + "\n")
    public_path = os.path.join(decoded, "res", "values", "public.xml")
    if not os.path.isfile(public_path):
        print("SPLIT_REPAIR_MISSING: res/values/public.xml not found")
        return 1
    with open(public_path, "r", encoding="utf-8") as fh:
        public_lines = fh.read().splitlines()
    for rid, name, _value, _why in split_dimens:
        try:
            public_lines = _insert_public_entry(public_lines, "dimen", name, rid)
        except ValueError as exc:
            print("SPLIT_REPAIR_CONFLICT: %s" % exc)
            return 1
        changes.append("split repair dimen %s -> 0x%08x" % (name, rid))
    with open(public_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(public_lines) + "\n")
    styles_path = os.path.join(decoded, "res", "values", "styles.xml")
    if not os.path.isfile(styles_path):
        print("SPLIT_REPAIR_MISSING: res/values/styles.xml not found")
        return 1
    with open(styles_path, "r", encoding="utf-8") as fh:
        styles_text = fh.read()
    for style_name, attr_name, dimen_name, why in split_repairs:
        ref = "@dimen/" + dimen_name
        block_re = re.compile(
            r'(<style\s+name="' + re.escape(style_name) + r'"[^>]*>)(.*?)(</style>)',
            re.DOTALL,
        )

        def _repair_block(m, attr_name=attr_name, ref=ref):
            head, body, tail = m.group(1), m.group(2), m.group(3)
            item_re = re.compile(
                r'(<item\s+name="' + re.escape(attr_name) + r'"[^>]*>)@null(</item>)'
            )
            new_body, n = item_re.subn(
                lambda im: im.group(1) + ref + im.group(2), body, count=1
            )
            if n == 0:
                return m.group(0)
            _repair_block.done = True
            return head + new_body + tail

        _repair_block.done = False
        styles_text, n_blocks = block_re.subn(_repair_block, styles_text, count=1)
        if not _repair_block.done:
            print(
                "SPLIT_REPAIR_MISSING: <item name=%r>@null</item> not "
                "found in <style name=%r> (%s)"
                % (attr_name, style_name, why)
            )
            return 1
        changes.append(
            "split repair %s/%s -> %s (%s)"
            % (style_name, attr_name, ref, why)
        )
    with open(styles_path, "w", encoding="utf-8") as fh:
        fh.write(styles_text)

    # 2j. Restore the Play-split drawables and strings the main
    # activity's bundled layouts need (see header, section D3).
    # Each resource is restored at its ORIGINAL id, because the
    # bundled layouts reference the ids directly.
    split_drawables = [
        # (resource id, drawable name)
        (0x7F0831D1, "verified_profile"),
        (0x7F082330, "instagram_chevron_down_pano_filled_12"),
        (0x7F082A1D, "instagram_x_pano_outline_8"),
        (0x7F0822CC, "instagram_call_pano_filled_12"),
        (0x7F081E6B, "from_meta_attribution"),
        (0x7F082190, "instagram"),
    ]
    split_strings = [
        # (resource id, placeholder name, placeholder value)
        (0x7F1345B2, "rdx_split_string_back", "Back"),
        (0x7F1345B8, "rdx_split_string_45b8", ""),
        (0x7F131DF7, "rdx_split_string_1df7", ""),
        (0x7F137F67, "rdx_split_string_37f67", ""),
        (0x7F138FCC, "rdx_split_string_8fcc", ""),
        (0x7F138FCD, "rdx_split_string_8fcd", ""),
    ]
    if split_dir is None:
        changes.append("2j SKIPPED: no split-drawables dir given "
                       "(pass it as the 3rd argument)")
    else:
        public_path = os.path.join(decoded, "res", "values",
                                   "public.xml")
        if not os.path.isfile(public_path):
            print("SPLIT_RESTORE_MISSING: res/values/public.xml "
                  "not found")
            return 1
        with open(public_path, "r", encoding="utf-8") as fh:
            public_lines = fh.read().splitlines()
        for rid, name in split_drawables:
            copied = []
            for dens in sorted(os.listdir(split_dir)):
                if not dens.startswith("drawable-"):
                    continue
                for fname in sorted(os.listdir(
                        os.path.join(split_dir, dens))):
                    if fname.rsplit(".", 1)[0] != name:
                        continue
                    src = os.path.join(split_dir, dens, fname)
                    dst_dir = os.path.join(decoded, "res", dens)
                    os.makedirs(dst_dir, exist_ok=True)
                    dst = os.path.join(dst_dir, fname)
                    with open(src, "rb") as fh:
                        blob = fh.read()
                    with open(dst, "wb") as fh:
                        fh.write(blob)
                    copied.append("%s/%s" % (dens, fname))
            if not copied:
                print("SPLIT_RESTORE_MISSING: no file for drawable "
                      "%s (0x%08x) in %s" % (name, rid, split_dir))
                return 1
            try:
                public_lines = _insert_public_entry(
                    public_lines, "drawable", name, rid)
            except ValueError as exc:
                print("SPLIT_RESTORE_CONFLICT: %s" % exc)
                return 1
            changes.append(
                "split restore drawable %s -> 0x%08x (%s)"
                % (name, rid, ", ".join(copied))
            )
        strings_path = os.path.join(decoded, "res", "values",
                                    "strings.xml")
        with open(strings_path, "r", encoding="utf-8") as fh:
            strings_text = fh.read()
        for rid, name, value in split_strings:
            try:
                public_lines = _insert_public_entry(
                    public_lines, "string", name, rid)
            except ValueError as exc:
                print("SPLIT_RESTORE_CONFLICT: %s" % exc)
                return 1
            if ('<string name="%s"' % name) in strings_text:
                print("SPLIT_RESTORE_CONFLICT: string %s already "
                      "defined in res/values/strings.xml" % name)
                return 1
            marker = "</resources>"
            new_item = ('    <string name="%s">%s</string>\n'
                        % (name, _xml_escape(value)))
            if marker not in strings_text:
                print("SPLIT_RESTORE_MISSING: </resources> not found "
                      "in res/values/strings.xml")
                return 1
            strings_text = strings_text.replace(
                marker, new_item + marker, 1)
            changes.append(
                "split restore string %s -> 0x%08x (value %r)"
                % (name, rid, value)
            )
        with open(public_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(public_lines) + "\n")
        with open(strings_path, "w", encoding="utf-8") as fh:
            fh.write(strings_text)

    # 2k. Sweep the Play-split XML drawables (see header, section
    # D4): restore every identified throwing-set hole (images,
    # stubs, dimens) at its original id, and rewrite the @nulls
    # apktool left in 131 XML drawables to real references. The
    # data file split-restores-2k.json (next to this script) is the
    # single source of truth; the image/stub files live in the
    # 4th-argument dir (rdxgram-rebrand/split-drawables-2k). A
    # missing dir or data file skips 2k (the layout-values gate
    # fails the build without the login-modal nine-patches); any
    # listed restore that cannot be applied is fatal.
    split_dir2k = sys.argv[4] if len(sys.argv) > 4 else None
    data_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "split-restores-2k.json",
    )
    if split_dir2k is None or not os.path.isfile(data_path):
        changes.append("2k SKIPPED: no split-drawables-2k dir (4th "
                       "argument) or split-restores-2k.json not found")
    else:
        import json as _json
        with open(data_path, "r", encoding="utf-8") as fh:
            data2k = _json.load(fh)
        public_path = os.path.join(decoded, "res", "values",
                                   "public.xml")
        if not os.path.isfile(public_path):
            print("SPLIT_2K_MISSING: res/values/public.xml not found")
            return 1
        with open(public_path, "r", encoding="utf-8") as fh:
            public_lines = fh.read().splitlines()
        n_draw = n_stub = n_dim = n_xml = 0

        def _drawable_base(fname):
            # "input.9.png" -> "input" (one rsplit gives "input.9",
            # which would miss the 9-patch); plain files keep the
            # usual stem.
            if fname.endswith(".9.png"):
                return fname[:-6]
            return fname.rsplit(".", 1)[0]

        # (a) image drawables: same copy loop as 2j.
        for rid_s, name in sorted(data2k.get("drawables", {}).items()):
            rid = int(rid_s, 16)
            copied = []
            for dens in sorted(os.listdir(split_dir2k)):
                if not dens.startswith("drawable-"):
                    continue
                for fname in sorted(os.listdir(
                        os.path.join(split_dir2k, dens))):
                    if _drawable_base(fname) != name:
                        continue
                    src = os.path.join(split_dir2k, dens, fname)
                    dst_dir = os.path.join(decoded, "res", dens)
                    os.makedirs(dst_dir, exist_ok=True)
                    with open(src, "rb") as fh:
                        blob = fh.read()
                    with open(os.path.join(dst_dir, fname), "wb") as fh:
                        fh.write(blob)
                    copied.append("%s/%s" % (dens, fname))
            if not copied:
                print("SPLIT_2K_MISSING: no file for drawable %s (%s) "
                      "in %s" % (name, rid_s, split_dir2k))
                return 1
            try:
                public_lines = _insert_public_entry(
                    public_lines, "drawable", name, rid)
            except ValueError as exc:
                print("SPLIT_2K_CONFLICT: %s" % exc)
                return 1
            n_draw += 1
            changes.append("2k restore drawable %s -> %s (%s)"
                           % (name, rid_s, ", ".join(copied)))
        # (b) xml stubs (AppRedrawableDrawable): source XML under
        # split_dir2k/drawable/ -> decoded res/drawable/.
        for rid_s, name in sorted(data2k.get("xml_stubs", {}).items()):
            rid = int(rid_s, 16)
            src = os.path.join(split_dir2k, "drawable", name + ".xml")
            if not os.path.isfile(src):
                print("SPLIT_2K_MISSING: no stub for %s (%s)"
                      % (name, rid_s))
                return 1
            with open(src, "rb") as fh:
                blob = fh.read()
            os.makedirs(os.path.join(decoded, "res", "drawable"),
                        exist_ok=True)
            with open(os.path.join(decoded, "res", "drawable",
                                   name + ".xml"), "wb") as fh:
                fh.write(blob)
            try:
                public_lines = _insert_public_entry(
                    public_lines, "drawable", name, rid)
            except ValueError as exc:
                print("SPLIT_2K_CONFLICT: %s" % exc)
                return 1
            n_stub += 1
            changes.append("2k restore xml stub %s -> %s" % (name, rid_s))
        # (c) extra dimens: append to rdx_split_dimens.xml (2i
        # created it) + public entries.
        dimens_path = os.path.join(decoded, "res", "values",
                                   "rdx_split_dimens.xml")
        if os.path.isfile(dimens_path):
            with open(dimens_path, "r", encoding="utf-8") as fh:
                dtext = fh.read()
            if "</resources>" not in dtext:
                print("SPLIT_2K_MISSING: </resources> not found in "
                      "rdx_split_dimens.xml")
                return 1
        else:
            dtext = ('<?xml version="1.0" encoding="utf-8"?>\n'
                     "<resources>\n</resources>\n")
        for rid_s, (name, value) in sorted(
                data2k.get("dimens", {}).items()):
            rid = int(rid_s, 16)
            if ('<dimen name="%s"' % name) not in dtext:
                dtext = dtext.replace(
                    "</resources>",
                    '    <dimen name="%s">%s</dimen>\n</resources>'
                    % (name, value), 1)
            try:
                public_lines = _insert_public_entry(
                    public_lines, "dimen", name, rid)
            except ValueError as exc:
                print("SPLIT_2K_CONFLICT: %s" % exc)
                return 1
            n_dim += 1
            changes.append("2k restore dimen %s -> %s (%s)"
                           % (name, rid_s, value))
        with open(dimens_path, "w", encoding="utf-8") as fh:
            fh.write(dtext)
        with open(public_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(public_lines) + "\n")
        # (d) rewrite the @nulls in the XML drawables. For each
        # file the fixes are applied in document order: the
        # index-th occurrence (0-based, among that attr's @null
        # values) of attr="@null" becomes attr="<new>". Fixes with
        # new=None (unidentified holes) are skipped — the @null
        # stays. After applying, the remaining @null count for each
        # fixed attr must equal the skipped count, or the decoded
        # tree differs from the one the fixes were generated
        # against and the build fails loudly. The attr regex is
        # boundary-anchored (an optional namespace prefix, then
        # the local name) so "width" never matches inside
        # "layout_width".
        for rel, fixes in sorted(data2k.get("xml_fixes", {}).items()):
            fpath = os.path.join(decoded, rel)
            if not os.path.isfile(fpath):
                print("SPLIT_2K_MISSING: xml fix target %s not found"
                      % rel)
                return 1
            with open(fpath, "r", encoding="utf-8") as fh:
                text = fh.read()
            by_attr = {}
            for fx in fixes:
                by_attr.setdefault(fx["attr"], []).append(fx)
            for attr, flist in by_attr.items():
                pat = re.compile(
                    r'(?<![\w.\-])((?:[A-Za-z_][\w.\-]*:)?'
                    + re.escape(attr) + r'\s*=\s*")@null(")')
                matches = list(pat.finditer(text))
                skipped_n = sum(1 for fx in flist if fx["new"] is None)
                # apply from the end so earlier offsets stay valid
                for fx in sorted(flist, key=lambda f: f["index"],
                                 reverse=True):
                    if fx["new"] is None:
                        continue
                    idx = fx["index"]
                    if idx >= len(matches):
                        print("SPLIT_2K_MISMATCH: %s has only %d @null "
                              "values for %s, fix wants index %d"
                              % (rel, len(matches), attr, idx))
                        return 1
                    m = matches[idx]
                    text = (text[:m.start()] + m.group(1) + fx["new"]
                            + m.group(2) + text[m.end():])
                remaining = len(list(pat.finditer(text)))
                if remaining != skipped_n:
                    print("SPLIT_2K_MISMATCH: %s: %d @null values left "
                          "for %s, expected %d (skipped/unidentified)"
                          % (rel, remaining, attr, skipped_n))
                    return 1
            with open(fpath, "w", encoding="utf-8") as fh:
                fh.write(text)
            n_xml += 1
            changes.append(
                "2k xml fix %s: %d replacements (%d left @null)"
                % (rel,
                   sum(1 for fx in fixes if fx["new"] is not None),
                   sum(1 for fx in fixes if fx["new"] is None)))
        changes.append("2k total: %d drawables, %d xml stubs, %d dimens, "
                       "%d xml files fixed" % (n_draw, n_stub, n_dim, n_xml))

    if not keep_package:
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

    if not keep_package:
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
