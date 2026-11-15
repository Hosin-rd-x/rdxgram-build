#!/usr/bin/env python3
"""Verify the layout indirection table of a (re)built RdxGram APK.

Why this exists: stock Instagram 451 stores its layouts as string
values in resources.arsc — 6,049 layout entries, every one a value
that is either a file path ("res/2mw.xml") or an indirection code
("L|215F2C|958|AC99"). At launch the app's own inflater calls
getString() on the layout id and the returned code tells it which
real layout to inflate. A rebuild that drops those codes (what
rebrand v1 did) keeps only ~66 layouts and launch dies with
NotFoundException: String resource ID #0x7f0e0949 (Redroid run
43600558276). This script reads resources.arsc with the standard
library only and asserts, for a rebuilt or LSPatch-patched APK:

  - layout entry 0x7f0e0949 (layout_activity_main_coordinator_layout)
    is present and getString() resolves it to a value starting "L|"
    (in a rebuilt APK the value is reached through a @string
    reference to the rdx_layout_* string rebrand.py stored the code
    in, so the check follows one reference hop);
  - at least 6,000 layout entries are present (stock: 6,049);
  - at least 5,900 of them resolve to "L|..." codes (stock: 5,988);
  - the app label string 0x7f130009 resolves to the expected label
    ("Rdx gram" by default; the theme build passes --expect-label
    Instagram, since it keeps the stock package and label);
  - attr 0x7f040d3e (tabBarHeight) is present;
  - the Play-split dimension repairs (rebrand step 2i) are present
    as REAL dimension resources at their original ids, with the
    style items pointing at them by reference: dimen 0x7f070263
    tab_bar_height_panorama = 48dp (Base.Theme.Instagram
    tabBarHeight), 0x7f0700e0 circular_avatar_stroke_width = 2px
    (Avatar strokeWidth), 0x7f07014b direct_in_thread_composer_
    top_margin = 8dp (BaseNightTheme and Theme.Instagram
    mediaViewOuterVerticalMargin). (1.8: the 6dp in the 1.1-1.7
    checks was the InstaPro 439 guess — the real 451 density split
    says 8dp.) A literal in the style item
    would be WRONG: InstagramMainActivity resolves tabBarHeight
    with Theme.resolveAttribute and passes TypedValue.resourceId
    to getDimensionPixelOffset, and a literal has resourceId 0
    (1.2 crashed that way on relaunch, Redroid 43610901393).
  - the Play-split drawable/string restores (rebrand step 2j) are
    present at their ORIGINAL ids: the seven drawables the main
    activity's bundled layouts need (verified_profile,
    instagram_chevron_down_pano_filled_12, instagram_x_pano_
    outline_8, instagram_call_pano_filled_12, from_meta_
    attribution at 0x7f081e6a, from_meta_gradient at 0x7f081e6b,
    instagram) and the six placeholder strings;
  - the Play-split XML-drawable sweep (rebrand step 2k) is present
    at its ORIGINAL ids, driven by the same split-restores-2k.json
    the rebrand reads: the 119 image drawables and 2 XML stubs
    resolve to a file path containing their name, and the 2 extra
    dimens resolve to their values (direct_composer_background_
    corner_radius 25dp, tab_bar_height_whiteout 48dp). The login
    modal's input_background selector depends on three of the
    images (input, input_highlighted, input_night).

Usage: verify_layout_values.py [--expect-label LABEL] <apk>
Exits 0 when every check passes, 1 otherwise.
"""
import collections
import json
import os
import re
import struct
import sys
import zipfile


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


class _StringPool:
    def __init__(self, data, off):
        self.utf8 = bool(_u32(data, off + 16) & 0x100)
        self.count = _u32(data, off + 8)
        self.strings_start = _u32(data, off + 20)
        self.off = off
        self.data = data
        self.offsets = [
            _u32(data, off + 28 + 4 * i) for i in range(self.count)
        ]

    def get(self, idx):
        if idx >= self.count:
            return None
        o = self.off + self.strings_start + self.offsets[idx]
        if self.utf8:
            b0 = self.data[o]
            if b0 & 0x80:
                ln = ((b0 & 0x7F) << 8) | self.data[o + 1]
                o += 2
            else:
                ln = b0
                o += 1
            b1 = self.data[o]
            o += 2 if b1 & 0x80 else 1
            return self.data[o:o + ln].decode("utf-8", "replace")
        ln = _u16(self.data, o)
        if ln & 0x8000:
            ln = ((ln & 0x7FFF) << 16) | _u16(self.data, o + 2)
            o += 4
        else:
            o += 2
        return self.data[o:o + ln * 2].decode("utf-16-le", "replace")


def parse_arsc(arsc):
    """Return (main_string_pool, entries, style_bags) where entries maps
    (type_id, entry_id) -> (type_name, key_name, data_type, data), and
    style_bags maps (style type_id, style entry_id) -> a list of
    (attr_res_id, data_type, data) for the style's bag items."""
    main_sp = None
    entries = {}
    style_bags = {}
    off = 12  # skip ResTable_header
    while off < len(arsc):
        ctype = _u16(arsc, off)
        csize = _u32(arsc, off + 4)
        if csize == 0:
            break
        if ctype == 0x0001 and main_sp is None:
            main_sp = _StringPool(arsc, off)
        elif ctype == 0x0200:  # ResTable_package
            hdr = _u16(arsc, off + 2)
            type_sp = _StringPool(arsc, off + _u32(arsc, off + hdr - 20))
            key_sp = _StringPool(arsc, off + _u32(arsc, off + hdr - 12))
            poff = off + hdr
            while poff < off + csize:
                ttype = _u16(arsc, poff)
                tsize = _u32(arsc, poff + 4)
                if tsize == 0:
                    break
                if ttype == 0x0201:  # ResTable_type
                    tid = arsc[poff + 8]
                    entry_count = _u32(arsc, poff + 12)
                    entries_start = _u32(arsc, poff + 16)
                    header_size = _u16(arsc, poff + 2)
                    tname = type_sp.get(tid - 1)
                    for eid in range(entry_count):
                        o = _u32(arsc, poff + header_size + 4 * eid)
                        if o == 0xFFFFFFFF:
                            continue
                        key = (tid, eid)
                        if key in entries:
                            continue
                        eo = poff + entries_start + o
                        kidx = _u32(arsc, eo + 4)
                        flags = _u16(arsc, eo + 2)
                        if flags & 1:  # complex: a bag (style map)
                            count = _u32(arsc, eo + 12)
                            items = []
                            for i in range(count):
                                mo = eo + 16 + i * 12
                                aname = _u32(arsc, mo)
                                mdtype = arsc[mo + 7]
                                mvdata = _u32(arsc, mo + 8)
                                items.append((aname, mdtype, mvdata))
                            style_bags[key] = items
                            dtype, vdata = None, None
                        else:
                            dtype = arsc[eo + 11]
                            vdata = _u32(arsc, eo + 12)
                        entries[key] = (
                            tname, key_sp.get(kidx), dtype, vdata,
                        )
                poff += tsize
        off += csize
    return main_sp, entries, style_bags


# Android complex dimension decoding (Res_value TYPE_DIMENSION):
# data = mantissa<<8 | radix<<4 | unit; value = mantissa * RADIX[radix].
_DIM_RADIX = [1.0, 1.0 / 256, 1.0 / 65536, 1.0 / 16777216]
_DIM_UNITS = {0: "px", 1: "dp", 2: "sp", 3: "pt", 4: "in", 5: "mm"}


def decode_dimension(data):
    unit = data & 0xF
    radix = (data >> 4) & 0x3
    mantissa = data >> 8
    if mantissa & 0x800000:
        mantissa -= 0x1000000
    return mantissa * _DIM_RADIX[radix], _DIM_UNITS.get(unit, "?")


def resolve(entries, main_sp, tid, eid, depth=0):
    """getString() semantics for one entry: a plain string value is
    returned as-is; a reference is followed one hop."""
    e = entries.get((tid, eid))
    if e is None:
        return None
    _tname, _kname, dtype, data = e
    if dtype == 0x03:  # TYPE_STRING
        return main_sp.get(data)
    if dtype == 0x01 and depth < 3:  # TYPE_REFERENCE
        return resolve(entries, main_sp, (data >> 16) & 0xFF,
                       data & 0xFFFF, depth + 1)
    return None


def _find_2k_json():
    """Locate rdxgram-rebrand/split-restores-2k.json: repo layout
    first (script lives in .github/scripts/), then the local
    rdxgram-push copy, then next to this script."""
    cands = [
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            "rdxgram-rebrand", "split-restores-2k.json"),
        os.path.expanduser(
            "~/workspace/rdxgram-push/rdxgram-rebrand/"
            "split-restores-2k.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "split-restores-2k.json"),
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def main():
    args = sys.argv[1:]
    expect_label = "Rdx gram"
    while args and args[0].startswith("--"):
        opt = args.pop(0)
        if opt == "--expect-label":
            if not args:
                print("usage: verify_layout_values.py "
                      "[--expect-label LABEL] <apk>")
                return 2
            expect_label = args.pop(0)
        else:
            print(f"unknown option: {opt}")
            return 2
    if len(args) != 1:
        print("usage: verify_layout_values.py [--expect-label LABEL] <apk>")
        return 2
    path = args[0]
    with zipfile.ZipFile(path) as zf:
        arsc = zf.read("resources.arsc")
    main_sp, entries, style_bags = parse_arsc(arsc)
    per_type = collections.Counter(v[0] for v in entries.values())
    layout_entries = [v for k, v in entries.items() if k[0] == 0x0E]
    layout_codes = sum(
        1 for k, v in entries.items()
        if k[0] == 0x0E
        and (resolve(entries, main_sp, k[0], k[1]) or "").startswith("L|")
    )
    main_layout = resolve(entries, main_sp, 0x0E, 0x0949)
    label = resolve(entries, main_sp, 0x13, 0x0009)
    print(f"total entries: {len(entries)}")
    print(f"layout entries: {len(layout_entries)} "
          f"(resolving to 'L|...' codes: {layout_codes})")
    print(f"0x7f0e0949 layout_activity_main_coordinator_layout -> "
          f"{main_layout!r}")
    print(f"0x7f130009 label -> {label!r}")
    print(f"0x7f040d3e attr/tabBarHeight present: "
          f"{(0x04, 0x0D3E) in entries}")
    print(f"per-type counts: {dict(per_type)}")

    # The Play-split dimension repairs (rebrand step 2i): each
    # style item must be a REFERENCE to the restored dimen id (a
    # literal would give resourceId 0 through resolveAttribute),
    # and the dimen id itself must hold the literal value.
    # style (type 0x14) name -> {attr name: (value, unit)} or
    # ("ref", hex id); dimen entries are (type 0x07) with dtype
    # 0x05 (TYPE_DIMENSION) and the complex value.
    style_attrs = {}
    for (tid, eid), items in style_bags.items():
        tname, sname, _d, _v = entries[(tid, eid)]
        if tname != "style":
            continue
        attrs = {}
        for aname, mdtype, mvdata in items:
            attr_entry = entries.get(((aname >> 16) & 0xFF, aname & 0xFFFF))
            attr_name = attr_entry[1] if attr_entry else None
            if mdtype == 0x05:  # TYPE_DIMENSION
                value, unit = decode_dimension(mvdata)
                attrs[attr_name] = (value, unit)
            elif mdtype == 0x01:  # TYPE_REFERENCE
                attrs[attr_name] = ("ref", hex(mvdata))
            else:
                attrs[attr_name] = (f"type {mdtype:#x}", mvdata)
        style_attrs[sname] = attrs
    repairs = [
        # (style, attr, dimen entry id, value, unit)
        ("Base.Theme.Instagram", "tabBarHeight", 0x0263, 48.0, "dp"),
        ("Avatar", "strokeWidth", 0x00E0, 2.0, "px"),
        ("BaseNightTheme", "mediaViewOuterVerticalMargin", 0x014B, 8.0, "dp"),
        ("Theme.Instagram", "mediaViewOuterVerticalMargin", 0x014B, 8.0, "dp"),
    ]
    repair_values = {}
    dimen_values = {}
    for style_name, attr_name, did, _want, _unit in repairs:
        got = style_attrs.get(style_name, {}).get(attr_name)
        repair_values[(style_name, attr_name)] = got
        print(f"split repair {style_name}/{attr_name} -> {got!r}")
        if did not in dimen_values:
            e = entries.get((0x07, did))
            if e is None or e[2] != 0x05:
                dimen_values[did] = None
            else:
                dimen_values[did] = decode_dimension(e[3])
            print(f"split repair dimen 0x7f07{did:04x} "
                  f"{e[1] if e else None} -> {dimen_values[did]!r}")

    # The Play-split drawable/string restores (rebrand step 2j):
    # each id must exist at its ORIGINAL id and resolve to the
    # restored file path / string value.
    split_drawables = [
        # entry ids (the 0x7f08 type prefix is added by resolve())
        (0x31D1, "verified_profile"),
        (0x2330, "instagram_chevron_down_pano_filled_12"),
        (0x2A1D, "instagram_x_pano_outline_8"),
        (0x22CC, "instagram_call_pano_filled_12"),
        (0x1E6A, "from_meta_attribution"),
        # 1.8: from_meta_attribution was checked at 0x1E6B here since
        # 1.1 — wrong by one. The real 451 split puts it at 0x1E6A
        # (code references 0x7f081e6a); 0x1E6B is from_meta_gradient.
        (0x1E6B, "from_meta_gradient"),
        (0x2190, "instagram"),
    ]
    split_strings = [
        # entry ids (the 0x7f13 type prefix is added by resolve())
        (0x45B2, "rdx_split_string_back", "Back"),
        (0x45B8, "rdx_split_string_45b8", ""),
        (0x1DF7, "rdx_split_string_1df7", ""),
        (0x7F67, "rdx_split_string_37f67", ""),
        (0x8FCC, "rdx_split_string_8fcc", ""),
        (0x8FCD, "rdx_split_string_8fcd", ""),
    ]
    restore_values = {}
    for eid, name in split_drawables:
        got = resolve(entries, main_sp, 0x08, eid)
        restore_values[("drawable", eid)] = got
        print(f"split restore drawable 0x7f08{eid:04x} {name} -> "
              f"{got!r}")
    for eid, name, _want in split_strings:
        got = resolve(entries, main_sp, 0x13, eid)
        restore_values[("string", eid)] = got
        print(f"split restore string 0x7f13{eid:04x} {name} -> "
              f"{got!r}")

    # The Play-split XML-drawable sweep (rebrand step 2k): every
    # identified hole must exist at its ORIGINAL id — images and
    # stubs resolve to a file path containing their name, dimens to
    # their value. The data file is the same JSON the rebrand reads.
    json_path = _find_2k_json()
    if json_path is None:
        print("SPLIT_2K_JSON_MISSING: split-restores-2k.json not found")
        return 1
    with open(json_path, "r", encoding="utf-8") as fh:
        data2k = json.load(fh)
    restore2k_draw = {}
    for rid_s, name in sorted(data2k.get("drawables", {}).items()):
        rid = int(rid_s, 16)
        got = resolve(entries, main_sp, 0x08, rid & 0xFFFF)
        restore2k_draw[rid] = (name, got)
        print(f"2k restore drawable {rid_s} {name} -> {got!r}")
    restore2k_stub = {}
    for rid_s, name in sorted(data2k.get("xml_stubs", {}).items()):
        rid = int(rid_s, 16)
        got = resolve(entries, main_sp, 0x08, rid & 0xFFFF)
        restore2k_stub[rid] = (name, got)
        print(f"2k restore xml stub {rid_s} {name} -> {got!r}")
    restore2k_dim = {}
    for rid_s, (name, want_s) in sorted(data2k.get("dimens", {}).items()):
        rid = int(rid_s, 16)
        e = entries.get((0x07, rid & 0xFFFF))
        got = (decode_dimension(e[3])
               if e is not None and e[2] == 0x05 else None)
        m = re.match(r"^([0-9.]+)(px|dp|sp|pt|in|mm)$", want_s)
        want = (float(m.group(1)), m.group(2)) if m else None
        restore2k_dim[rid] = (name, got, want)
        print(f"2k restore dimen {rid_s} {name} -> {got!r} "
              f"(expected {want!r})")

    failures = []
    if main_layout is None or not main_layout.startswith("L|"):
        failures.append(
            "MAIN_LAYOUT_CODE_MISSING: 0x7f0e0949 does not resolve to "
            f"an 'L|...' code (got {main_layout!r}) — the app will die "
            "at launch with NotFoundException for this id"
        )
    if len(layout_entries) < 6000:
        failures.append(
            f"LAYOUT_COUNT_LOW: {len(layout_entries)} layout entries "
            "(stock: 6049) — the layout indirection table was pruned"
        )
    if layout_codes < 5900:
        failures.append(
            f"LAYOUT_CODES_LOW: {layout_codes} layouts resolve to "
            "'L|...' codes (stock: 5988)"
        )
    if label != expect_label:
        failures.append(f"LABEL_WRONG: 0x7f130009 resolves to {label!r} "
                        f"(expected {expect_label!r})")
    if (0x04, 0x0D3E) not in entries:
        failures.append("ATTR_TABBARHEIGHT_MISSING: 0x7f040d3e absent")
    for style_name, attr_name, did, want, unit in repairs:
        got = repair_values[(style_name, attr_name)]
        want_ref = ("ref", f"0x7f07{did:04x}")
        if got != want_ref:
            failures.append(
                f"SPLIT_REPAIR_WRONG: {style_name}/{attr_name} is "
                f"{got!r}, expected a reference {want_ref!r} — a "
                "literal here gives resourceId 0 through "
                "Theme.resolveAttribute and the relaunch dies with "
                "'Resource ID #0x0'"
            )
        got_dim = dimen_values[did]
        if got_dim is None or got_dim != (want, unit):
            failures.append(
                f"SPLIT_REPAIR_WRONG: dimen 0x7f07{did:04x} is "
                f"{got_dim!r}, expected ({want}, {unit!r}) — the "
                "base APK is missing this Play-split dimension and "
                "launch will fail resolving it"
            )
    for eid, name in split_drawables:
        got = restore_values[("drawable", eid)]
        if not got or name not in got:
            failures.append(
                f"SPLIT_RESTORE_WRONG: drawable 0x7f08{eid:04x} "
                f"({name}) resolves to {got!r} — the bundled layouts "
                "reference this id directly and launch will fail "
                "with NotFoundException"
            )
    for eid, name, want in split_strings:
        got = restore_values[("string", eid)]
        if got != want:
            failures.append(
                f"SPLIT_RESTORE_WRONG: string 0x7f13{eid:04x} "
                f"({name}) resolves to {got!r}, expected "
                f"{want!r} — a bundled layout calls getText() on "
                "this id at inflation"
            )
    for rid, (name, got) in restore2k_draw.items():
        if not got or name not in got:
            failures.append(
                f"SPLIT_2K_WRONG: drawable 0x{rid:08x} ({name}) "
                f"resolves to {got!r} — an XML drawable that "
                "references this id cannot load and the app dies "
                "with NotFoundException when it is inflated"
            )
    for rid, (name, got) in restore2k_stub.items():
        if not got or name not in got:
            failures.append(
                f"SPLIT_2K_WRONG: xml stub 0x{rid:08x} ({name}) "
                f"resolves to {got!r} — a layer-list that "
                "references this id cannot load"
            )
    for rid, (name, got, want) in restore2k_dim.items():
        if got is None or got != want:
            failures.append(
                f"SPLIT_2K_WRONG: dimen 0x{rid:08x} ({name}) is "
                f"{got!r}, expected {want!r} — a shape or "
                "layer-list that references this id cannot load"
            )
    if failures:
        for f in failures:
            print(f)
        return 1
    print("LAYOUT_VALUES_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
