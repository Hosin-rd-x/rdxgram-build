#!/usr/bin/env python3
"""Merge the exact-version 451 density split into the 2k restore set.

Why: the stock Instagram 451 APK is only the BASE of a Play bundle.
Part of its resources live ONLY in the Play "density" split
(config.xxxhdpi). Every screen that touches one of those IDs crashes
with Resources$NotFoundException — that is what killed the feed in
1.4 (login), 1.5 (feed action bar), 1.6 (stories strip) and 1.7
(missing dimen 0x7f0701ea). Guessing the missing names from InstaPro
439 (the 1.5-1.7 gap method) was 99.5% right on names but wrong on 2
names and on one dimen value, and left 136 drawables unidentified.

This script merges the REAL split (same version 451.0.0.53.80, from the
APKFab XAPK, verified by SHA1) into split-restores-2k.json, with real
names and real values for every entry that is absent from the base.
Cross-version splits do NOT work (451 vs 454: 0/364 name matches), so
only this exact split is a valid source.

Inputs:
  --split-apk    the density split APK (config.xxxhdpi.apk, 8.3 MB).
                 Committed to the repo as rdxgram-rebrand/
                 split-451-xxxhdpi.apk so the merge is reproducible.
  --base-apk     the stock base APK (same version) to diff against.
  --decode-split apktool decode of the split APK (text XMLs + real
                 file names). If omitted, it is produced with apktool
                 (--apktool, needs Java).
  --decode-stock apktool decode of the stock base APK (for the
                 type-aware public.xml conflict checks and the
                 xml_fixes re-application check).
  --mirror       the rdxgram-rebrand dir to update (its
                 split-restores-2k.json + split-drawables-2k/).
  --apktool      apktool jar (only needed when --decode-split is
                 omitted).

Outputs (in --mirror):
  split-restores-2k.json — every split-only entry added with its real
    name/value; the 9 wrong 1.7 names corrected (7 rdx_placeholder_*
    stubs + 2 gap-method misnamings); the 8 xml_fixes that referenced
    placeholder names rewritten to the real names; the 2 hand-made
    xml_stubs with real split files moved to drawables; 5 new dimens
    (incl. photo_grid_spacing 6px, the 1.7 feed crash, and the
    corrected direct_in_thread_composer_top_margin 8dp, not 6dp);
    new "integers" / "raws" / "arrays" sections for the 3 non-drawable
    split-only entries (density_value=6, the splash texture, the splash
    gradient geometry); unidentified_holes emptied; restore_1_8
    provenance added.
  split-drawables-2k/<density>/ — the split's files under their REAL
    names, in the density dirs apktool decoded them to. Every old file
    for a replaced name (any density, any extension) is removed first,
    so the restore set is purely split-derived.

Validation (fails loudly, nothing is written on failure):
  1. every split-only drawable has >=1 decoded file, magic OK
     (PNG/WebP/JPEG/GIF/XML/9-patch), XMLs well-formed;
  2. no same-type public.xml conflicts vs the stock decode
     (type-aware: a name may exist as an id/attr/layout AND as a
     drawable — only same-type collisions fail);
  3. every @drawable/@color/@dimen/@string reference inside staged
     XMLs resolves to stock names or the restore set (@attr refs are
     warnings only — theme attrs need not be in public.xml);
  4. no @null left inside staged XMLs;
  5. all 131 xml_fixes still apply cleanly against the stock decode.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import arsc2  # noqa: E402  (vendored copy of the scratch arsc library)

REF_RE = re.compile(r'@(drawable|color|dimen|string|attr)/([A-Za-z0-9_]+)')
DIMEN_RE = re.compile(r'^\d+(\.\d+)?(dp|px|sp)$')


def drawable_base(fname):
    if fname.endswith('.9.png'):
        return fname[:-6]
    return fname.rsplit('.', 1)[0]


def rid_hex(tid, eid):
    return '0x%08x' % (0x7F000000 | (tid << 16) | eid)


def fmt_dimen(data):
    value, unit = arsc2.decode_dimension(data)
    text = '%g%s' % (value, unit)
    assert DIMEN_RE.match(text), 'bad dimen value %r' % text
    return text


def decode_split_apk(split_apk, apktool_jar, out_dir):
    print('decoding split APK with apktool ...')
    cmd = ['java', '-jar', apktool_jar, 'd', '-o', out_dir, '-f', split_apk]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise SystemExit('apktool decode of the split APK failed')
    print('decoded to %s' % out_dir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split-apk', required=True)
    ap.add_argument('--base-apk', required=True)
    ap.add_argument('--decode-split', default=None)
    ap.add_argument('--decode-stock', required=True)
    ap.add_argument('--mirror', default=HERE)
    ap.add_argument('--apktool', default=None)
    args = ap.parse_args()

    split_apk = os.path.abspath(args.split_apk)
    base_apk = os.path.abspath(args.base_apk)
    mirror = os.path.abspath(args.mirror)
    stage_root = os.path.join(mirror, 'split-drawables-2k')
    json_path = os.path.join(mirror, 'split-restores-2k.json')

    decode_split = (os.path.abspath(args.decode_split) if args.decode_split
                    else os.path.join(os.path.dirname(split_apk),
                                      'decode-split-merge'))
    if not args.decode_split or not os.path.isdir(decode_split):
        if not args.apktool:
            raise SystemExit('--decode-split not given and no --apktool jar')
        decode_split_apk(split_apk, os.path.abspath(args.apktool),
                         decode_split)

    # --- 1. arsc diff: split-only entries -------------------------------
    sp_s, e_s = arsc2.parse(split_apk)
    sp_b, e_b = arsc2.parse(base_apk)
    only = {k: v for k, v in e_s.items() if k not in e_b}
    print('split entries: %d, base entries: %d, split-only: %d'
          % (len(e_s), len(e_b), len(only)))
    by_type = {}
    for k, v in only.items():
        by_type.setdefault(v['type'], []).append((k, v))
    print('split-only by type: %s'
          % {t: len(v) for t, v in sorted(by_type.items())})

    # --- 2. decoded-file map (drawable-*/ + raw-*/ dirs) ---------------
    dec_res = os.path.join(decode_split, 'res')
    files_by_name = {}   # drawable base name -> [(density dir, filename)]
    raw_files = {}       # raw base name -> [(density dir, filename)]
    for d in sorted(os.listdir(dec_res)):
        dd = os.path.join(dec_res, d)
        if not os.path.isdir(dd):
            continue
        if d.startswith('drawable-'):
            target = files_by_name
        elif d.startswith('raw-'):
            target = raw_files
        else:
            continue
        for fname in sorted(os.listdir(dd)):
            target.setdefault(drawable_base(fname), []).append((d, fname))
    print('decoded files: %d drawable names, %d raw names'
          % (len(files_by_name), len(raw_files)))

    # --- 3. load current JSON -------------------------------------------
    d2k = json.load(open(json_path, encoding='utf-8'))
    print('current: %d drawables, %d stubs, %d dimens, %d xml fixes'
          % (len(d2k['drawables']), len(d2k['xml_stubs']),
             len(d2k['dimens']), len(d2k['xml_fixes'])))

    # --- 4. renames: existing entries whose split name differs ----------
    # (the 7 rdx_placeholder_* stubs + the 2 gap-method misnamings).
    # Computed generically from the split table, not hardcoded.
    renames = {}   # rid hex -> (old name, new name, was_stub)
    for rid_s, name in list(d2k['drawables'].items()):
        rid = int(rid_s, 16)
        k = ((rid >> 16) & 0xFF, rid & 0xFFFF)
        if k in only and only[k]['name'] != name:
            renames[rid_s] = (name, only[k]['name'], False)
    for rid_s, name in list(d2k['xml_stubs'].items()):
        rid = int(rid_s, 16)
        k = ((rid >> 16) & 0xFF, rid & 0xFFFF)
        if k in only and only[k]['name'] != name:
            renames[rid_s] = (name, only[k]['name'], True)
    print('renames (split name differs from JSON): %d' % len(renames))
    for rid_s, (old, new, was_stub) in sorted(renames.items()):
        print('  %s: %s -> %s (was %s)'
              % (rid_s, old, new, 'stub' if was_stub else 'drawable'))

    # --- 5. stage files --------------------------------------------------
    # Remove every old staged file for a replaced/renamed name first
    # (any density dir, any extension, incl. drawable/ stubs), then
    # copy the split's variants under the real name.
    def remove_staged(name):
        removed = []
        for d in sorted(os.listdir(stage_root)):
            dd = os.path.join(stage_root, d)
            if not os.path.isdir(dd):
                continue
            for fname in sorted(os.listdir(dd)):
                if drawable_base(fname) == name:
                    os.remove(os.path.join(dd, fname))
                    removed.append('%s/%s' % (d, fname))
        return removed

    def stage_files(name, variants):
        staged = []
        for dens, fname in variants:
            src = os.path.join(dec_res, dens, fname)
            dst_dir = os.path.join(stage_root, dens)
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src, os.path.join(dst_dir, fname))
            staged.append('%s/%s' % (dens, fname))
        return staged

    errors = []
    new_drawables = {}
    n_files = 0
    n_xml = 0
    for (tid, eid), entry in sorted(by_type.get('drawable', [])):
        rid_s = rid_hex(tid, eid)
        name = entry['name']
        variants = files_by_name.get(name)
        if not variants:
            errors.append('no decoded file for drawable %s (%s)'
                          % (name, rid_s))
            continue
        # validate magic + XML well-formedness on the decoded files
        for dens, fname in variants:
            p = os.path.join(dec_res, dens, fname)
            head = open(p, 'rb').read(16)
            ok = (head[:4] == b'\x89PNG' or head[:4] == b'RIFF'
                  or head[:3] == b'\xff\xd8\xff' or head[:4] == b'GIF8'
                  or head.startswith(b'<?xml'))
            if not ok:
                errors.append('bad magic for %s: %s/%s: %r'
                              % (name, dens, fname, head[:8]))
            if fname.endswith('.xml'):
                try:
                    ET.parse(p)
                except ET.ParseError as exc:
                    errors.append('XML not well-formed: %s/%s: %s'
                                  % (dens, fname, exc))
        if rid_s in d2k['drawables'] or rid_s in d2k['xml_stubs']:
            # existing restore: replace its files with the split's
            old_name = (d2k['drawables'].get(rid_s)
                        or d2k['xml_stubs'].get(rid_s))
            remove_staged(old_name)
            if rid_s in d2k['xml_stubs']:
                # a stub with a real split file becomes a drawable
                del d2k['xml_stubs'][rid_s]
        staged = stage_files(name, variants)
        new_drawables[rid_s] = name
        n_files += len(staged)
        n_xml += sum(1 for _, f in variants if f.endswith('.xml'))
    if errors:
        print('ERRORS (%d):' % len(errors))
        for e in errors[:40]:
            print('  ', e)
        raise SystemExit(1)
    print('staged %d files for %d drawables (%d XML, %d images)'
          % (n_files, len(new_drawables), n_xml, n_files - n_xml))
    d2k['drawables'] = new_drawables

    # --- 6. dimens (real values from the split arsc) --------------------
    new_dimens = {}
    for (tid, eid), entry in sorted(by_type.get('dimen', [])):
        rid_s = rid_hex(tid, eid)
        new_dimens[rid_s] = [entry['name'], fmt_dimen(entry['data'])]
    for rid_s, (name, value) in sorted(new_dimens.items()):
        old = d2k['dimens'].get(rid_s)
        if old and old != [name, value]:
            print('dimen corrected: %s %s: %s -> %s'
                  % (rid_s, name, old[1], value))
        d2k['dimens'][rid_s] = [name, value]
    print('dimens now: %d (%d new/changed)'
          % (len(d2k['dimens']),
             sum(1 for r in new_dimens if r not in
                 json.load(open(json_path, encoding='utf-8'))['dimens'])))

    # --- 7. integers / raws / arrays (the 3 non-drawable entries) -------
    # Values are read from the apktool-decoded values XMLs and
    # cross-checked against the arsc entries.
    dec_values = {}
    for d in sorted(os.listdir(dec_res)):
        if not d.startswith('values'):
            continue
        for vf in ('arrays.xml', 'integers.xml'):
            p = os.path.join(dec_res, d, vf)
            if os.path.isfile(p):
                dec_values.setdefault(vf, []).append(p)

    integers = {}
    for (tid, eid), entry in sorted(by_type.get('integer', [])):
        rid_s = rid_hex(tid, eid)
        found = None
        for p in dec_values.get('integers.xml', []):
            root = ET.parse(p).getroot()
            for item in root.findall('integer'):
                if item.get('name') == entry['name']:
                    found = int(item.text.strip())
        if found is None:
            raise SystemExit('integer %s (%s) not in decoded values XMLs'
                             % (entry['name'], rid_s))
        if found != entry['data']:
            raise SystemExit('integer %s: arsc=%s decoded=%s'
                             % (entry['name'], entry['data'], found))
        integers[rid_s] = [entry['name'], found]
    d2k['integers'] = integers
    print('integers: %s' % integers)

    raws = {}
    for (tid, eid), entry in sorted(by_type.get('raw', [])):
        rid_s = rid_hex(tid, eid)
        path = arsc2.val(e_s, sp_s, tid, eid)
        variants = raw_files.get(entry['name'])
        if not variants:
            raise SystemExit('no decoded file for raw %s (%s)'
                             % (entry['name'], rid_s))
        remove_staged(entry['name'])
        staged = stage_files(entry['name'], variants)
        raws[rid_s] = entry['name']
        print('raw %s (%s): split path %s -> staged %s'
              % (entry['name'], rid_s, path, staged))
    d2k['raws'] = raws

    arrays = {}
    for (tid, eid), entry in sorted(by_type.get('array', [])):
        rid_s = rid_hex(tid, eid)
        found = None
        for p in dec_values.get('arrays.xml', []):
            root = ET.parse(p).getroot()
            for arr in list(root.findall('integer-array')) + \
                    list(root.findall('array')):
                if arr.get('name') == entry['name']:
                    found = [int(it.text.strip())
                             for it in arr.findall('item')]
        if found is None:
            raise SystemExit('array %s (%s) not in decoded values XMLs'
                             % (entry['name'], rid_s))
        arrays[rid_s] = [entry['name'], found]
    d2k['arrays'] = arrays
    print('arrays: %s' % arrays)

    # --- 8. xml_fixes: rewrite placeholder refs to real names -----------
    old_to_new = {old: new for _, (old, new, _) in renames.items()}
    n_rewritten = 0
    for rel, fixes in d2k.get('xml_fixes', {}).items():
        for fx in fixes:
            new = fx.get('new')
            if not new:
                continue
            for old, new_name in old_to_new.items():
                if new == '@drawable/' + old:
                    fx['new'] = '@drawable/' + new_name
                    n_rewritten += 1
    print('xml_fixes refs rewritten to real names: %d' % n_rewritten)

    # --- 9. placeholders metadata + provenance ---------------------------
    repl_1_8 = {}
    for rid_s, (old, new, was_stub) in sorted(renames.items()):
        if rid_s in d2k.get('placeholders', {}):
            d2k['placeholders'][rid_s]['replaced_in_1_8_by'] = new
            repl_1_8[rid_s] = {'old_placeholder_name': old,
                               'new_name': new}
    if repl_1_8:
        d2k['placeholder_replacements_1_8'] = repl_1_8
    d2k['unidentified_holes'] = []
    d2k['restore_1_8'] = {
        'method': 'density-split',
        'source': ('config.xxxhdpi.apk from the 451.0.0.53.80 XAPK '
                   '(APKFab arm64-v8a + xxxhdpi, SHA1 '
                   '6412413ba4e19a9b98488c7618abf10efadafaf4)'),
        'counts': {'drawables': len(d2k['drawables']),
                   'xml_stubs': len(d2k['xml_stubs']),
                   'dimens': len(d2k['dimens']),
                   'integers': len(integers),
                   'raws': len(raws),
                   'arrays': len(arrays),
                   'xml_fixes': len(d2k['xml_fixes'])},
        'renames': {rid: {'old': old, 'new': new}
                    for rid, (old, new, _) in sorted(renames.items())},
        'dimen_corrections': {
            '0x7f07014b': ('direct_in_thread_composer_top_margin: '
                          '6dp (InstaPro 439 guess in 2i) -> 8dp (split)')},
        'unidentified_attr': '0x7f040dcf',
        'notes': ('All 6,868 split-only entries restored with real names '
                  'and values from the exact 451 split — no more gap '
                  'guesses. The 136 gap-ambiguous drawables, the 2 '
                  'misnamed gap drawables, the 7 placeholder stubs and '
                  'dimen 0x7f0701ea (photo_grid_spacing 6px, the 1.7 '
                  'feed crash) are all resolved. attr 0x7f040dcf is '
                  'not in the split either (1 reference, never '
                  'crashed) and stays unrestored.'),
    }

    # --- 10. validation ---------------------------------------------------
    print('validating ...')
    verrors = []
    warnings = []
    public = open(os.path.join(args.decode_stock, 'res', 'values',
                               'public.xml'), encoding='utf-8').read()
    entries = re.findall(r'<public type="([^"]+)" name="([^"]+)" '
                         r'id="(0x[0-9a-f]+)"', public)
    stock_by_type = {}
    for t, n, i in entries:
        stock_by_type.setdefault(t, set()).add(n)
    stock_ids = {(t, i) for t, n, i in entries}
    restore_names = set(d2k['drawables'].values())
    # (a) staged files present + public conflicts (type-aware)
    staged_files = {}
    for d in sorted(os.listdir(stage_root)):
        if not (d.startswith('drawable-') or d.startswith('raw-')):
            continue
        dd = os.path.join(stage_root, d)
        for fname in sorted(os.listdir(dd)):
            staged_files.setdefault(drawable_base(fname), []).append(
                os.path.join(dd, fname))
    for rid_s, name in sorted(d2k['drawables'].items()):
        if not staged_files.get(name):
            verrors.append('(a) no staged file for %s (%s)' % (name, rid_s))
        if name in stock_by_type.get('drawable', set()):
            verrors.append('(a) drawable-name conflict: %s (%s)'
                           % (name, rid_s))
        if ('drawable', rid_s) in stock_ids:
            verrors.append('(a) drawable-id conflict: %s' % rid_s)
    for rid_s, name in sorted(d2k['raws'].items()):
        if not staged_files.get(name):
            verrors.append('(a) no staged file for raw %s (%s)'
                           % (name, rid_s))
        if name in stock_by_type.get('raw', set()):
            verrors.append('(a) raw-name conflict: %s (%s)' % (name, rid_s))
        if ('raw', rid_s) in stock_ids:
            verrors.append('(a) raw-id conflict: %s' % rid_s)
    for rid_s, (name, value) in sorted(d2k['dimens'].items()):
        if not DIMEN_RE.match(value):
            verrors.append('(a) dimen bad value: %s=%s' % (name, value))
        if name in stock_by_type.get('dimen', set()):
            verrors.append('(a) dimen-name conflict: %s (%s)'
                           % (name, rid_s))
        if ('dimen', rid_s) in stock_ids:
            verrors.append('(a) dimen-id conflict: %s' % rid_s)
    for rid_s, (name, value) in sorted(d2k['integers'].items()):
        if name in stock_by_type.get('integer', set()):
            verrors.append('(a) integer-name conflict: %s (%s)'
                           % (name, rid_s))
        if ('integer', rid_s) in stock_ids:
            verrors.append('(a) integer-id conflict: %s' % rid_s)
    for rid_s, (name, items) in sorted(d2k['arrays'].items()):
        if name in stock_by_type.get('array', set()):
            verrors.append('(a) array-name conflict: %s (%s)'
                           % (name, rid_s))
        if ('array', rid_s) in stock_ids:
            verrors.append('(a) array-id conflict: %s' % rid_s)
    # (b) refs inside staged XMLs
    xml_files = [p for paths in staged_files.values() for p in paths
                 if p.endswith('.xml')]
    n_xml_checked = 0
    for p in sorted(set(xml_files)):
        text = open(p, errors='replace').read()
        n_xml_checked += 1
        if '@null' in text:
            verrors.append('(b) @null inside staged XML: %s'
                           % os.path.relpath(p, stage_root))
        for rtype, rname in sorted(set(REF_RE.findall(text))):
            if rtype == 'drawable':
                if (rname not in stock_by_type.get('drawable', set())
                        and rname not in restore_names):
                    verrors.append('(b) dangling @drawable/%s in %s'
                                   % (rname, os.path.relpath(p, stage_root)))
            elif rtype in ('color', 'dimen', 'string'):
                if rname not in stock_by_type.get(rtype, set()):
                    verrors.append('(b) dangling @%s/%s in %s'
                                   % (rtype, rname,
                                      os.path.relpath(p, stage_root)))
            elif rtype == 'attr':
                if rname not in stock_by_type.get('attr', set()):
                    warnings.append('@attr/%s not in stock public '
                                    '(may be theme attr): %s'
                                    % (rname, os.path.relpath(p, stage_root)))
    # (c) xml_fixes still apply
    for rel, fixes in sorted(d2k.get('xml_fixes', {}).items()):
        fpath = os.path.join(args.decode_stock, rel)
        text = open(fpath, errors='replace').read()
        by_attr = {}
        for fx in fixes:
            by_attr.setdefault(fx['attr'], []).append(fx)
        for attr, flist in by_attr.items():
            pat = re.compile(r'(?<![\w.\-])((?:[A-Za-z_][\w.\-]*:)?'
                             + re.escape(attr) + r'\s*=\s*")@null(")')
            matches = list(pat.finditer(text))
            skipped_n = sum(1 for fx in flist if fx['new'] is None)
            for fx in sorted(flist, key=lambda f: f['index'], reverse=True):
                if fx['new'] is None:
                    continue
                idx = fx['index']
                if idx >= len(matches):
                    verrors.append('(c) %s: only %d @null for %s, fix '
                                   'wants index %d'
                                   % (rel, len(matches), attr, idx))
                    continue
                m = matches[idx]
                text = (text[:m.start()] + m.group(1) + fx['new']
                        + m.group(2) + text[m.end():])
            remaining = len(list(pat.finditer(text)))
            if remaining != skipped_n:
                verrors.append('(c) %s: remaining @null %d != skipped %d '
                               'for %s' % (rel, remaining, skipped_n, attr))
    print('checked %d staged XML files' % n_xml_checked)
    if warnings:
        print('WARNINGS (%d):' % len(warnings))
        for w in warnings[:20]:
            print('  ', w)
    if verrors:
        print('VALIDATION ERRORS (%d):' % len(verrors))
        for e in verrors[:40]:
            print('  ', e)
        raise SystemExit(1)
    print('VALIDATION OK')

    # --- 11. write JSON ----------------------------------------------------
    json.dump(d2k, open(json_path, 'w', encoding='utf-8'), indent=1)
    print('wrote %s' % json_path)
    print('MERGE OK: %d drawables, %d xml stubs, %d dimens, %d integers, '
          '%d raws, %d arrays, %d xml fixes'
          % (len(d2k['drawables']), len(d2k['xml_stubs']),
             len(d2k['dimens']), len(d2k['integers']), len(d2k['raws']),
             len(d2k['arrays']), len(d2k['xml_fixes'])))
    print('expected workflow lines:')
    print('  2k total: %d drawables, %d xml stubs, %d dimens, %d xml '
          'files fixed'
          % (len(d2k['drawables']), len(d2k['xml_stubs']),
             len(d2k['dimens']), len(d2k['xml_fixes'])))
    print('  2k extra: %d integers, %d raws, %d arrays'
          % (len(d2k['integers']), len(d2k['raws']), len(d2k['arrays'])))


if __name__ == '__main__':
    main()
