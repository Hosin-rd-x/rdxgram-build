#!/usr/bin/env python3
"""Remove the `requiredSplitTypes` attribute from an APK's binary
AndroidManifest.xml, so the APK installs standalone on a clean device.

Why: stock Instagram 451 is a Play-bundle build; its manifest declares
requiredSplitTypes='base__density', and the density config split is not
inside the single base APK. The installer then refuses with
INSTALL_FAILED_MISSING_SPLIT on any device that does not already have
the split (e.g. from an installed official Instagram). The base APK
itself carries the default resources, so Android falls back to them at
runtime; the emulator test is the judge of that.

How: binary edit of the <manifest> START_ELEMENT chunk only — the
attribute's 20 bytes are removed, the attribute count and chunk/file
sizes are decremented. The string pool is untouched, so nothing else
shifts. The ZIP is rewritten at the byte level (only the manifest
entry changes; every other entry is copied verbatim, and any APK
Signing Block is dropped — the APK MUST be re-signed afterwards with
zipalign + apksigner). Byte-level rewriting is used because Python's
zipfile refuses to read LSPatch output (overlapped origin.apk entry).

Usage: strip_required_splits.py <in.apk> <out.apk>
       strip_required_splits.py --check <apk>   (exit 0 if the
       attribute is absent, 1 if present)
Exits 0 when the attribute was removed (or was already absent).
"""
import binascii
import struct
import sys
import zlib

TARGET = "requiredSplitTypes"
MANIFEST = "AndroidManifest.xml"
SIG_BLOCK_MAGIC = b"APK Sig Block 42"


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


def manifest_attr_names(axml):
    """Names of the attributes on the first (<manifest>) START_ELEMENT."""
    pool = axml[8:]
    strings = read_strings(pool)
    p = 8 + struct.unpack_from("<I", pool, 4)[0]
    while p < len(axml):
        ctype, hsize, size = struct.unpack_from("<HHI", axml, p)
        if ctype == 0x0102:
            astart, asize, acount = struct.unpack_from("<HHH", axml, p + 24)
            return [strings[struct.unpack_from("<I", axml, p + 16 + astart + i * asize + 4)[0]]
                    for i in range(acount)]
        p += size
    raise SystemExit("no START_ELEMENT found in AndroidManifest.xml")


def strip_attr(axml):
    pool = axml[8:]
    strings = read_strings(pool)
    p = 8 + struct.unpack_from("<I", pool, 4)[0]
    target_idx = None
    for i, s in enumerate(strings):
        if s == TARGET:
            target_idx = i
            break
    if target_idx is None:
        return axml, False
    while p < len(axml):
        ctype, hsize, size = struct.unpack_from("<HHI", axml, p)
        if ctype == 0x0102:  # START_ELEMENT = <manifest>
            astart, asize, acount = struct.unpack_from("<HHH", axml, p + 24)
            for i in range(acount):
                q = p + 16 + astart + i * asize
                ns, nm, raw = struct.unpack_from("<III", axml, q)
                if nm == target_idx:
                    new = bytearray(axml[:q] + axml[q + asize:])
                    struct.pack_into("<H", new, p + 28, acount - 1)
                    struct.pack_into("<I", new, p + 4, size - asize)
                    fsize = struct.unpack_from("<I", new, 4)[0]
                    struct.pack_into("<I", new, 4, fsize - asize)
                    return bytes(new), True
            return axml, False
        p += size
    raise SystemExit("no START_ELEMENT found in AndroidManifest.xml")


# ---------------- byte-level ZIP rewrite ----------------

def find_eocd(data):
    idx = data.rfind(b"PK\x05\x06")
    if idx < 0:
        raise SystemExit("EOCD not found")
    (disk, cddisk, nrec_disk, nrec, cdsize, cdoff, clen) = struct.unpack_from("<HHHHIIH", data, idx + 4)
    if cdoff == 0xFFFFFFFF or cdsize == 0xFFFFFFFF or nrec == 0xFFFF:
        raise SystemExit("ZIP64 EOCD — unsupported, refusing to rewrite")
    return idx, cdoff, cdsize, nrec, clen


def parse_cd(data, cdoff, nrec):
    entries = []
    p = cdoff
    for _ in range(nrec):
        assert data[p:p + 4] == b"PK\x01\x02", "bad central-directory record"
        (vmade, vneed, flags, method, mtime, mdate, crc, csize, usize,
         fnlen, extralen, comlen, disk, iattr, eattr, lho) = struct.unpack_from("<HHHHHHIIIHHHHHII", data, p + 4)
        name = data[p + 46:p + 46 + fnlen]
        extra = data[p + 46 + fnlen:p + 46 + fnlen + extralen]
        comment = data[p + 46 + fnlen + extralen:p + 46 + fnlen + extralen + comlen]
        entries.append({"cd_off": p, "vmade": vmade, "vneed": vneed,
                        "flags": flags, "method": method, "mtime": mtime,
                        "mdate": mdate, "crc": crc, "csize": csize,
                        "usize": usize, "name": name, "extra": extra,
                        "comment": comment, "disk": disk, "iattr": iattr,
                        "eattr": eattr, "lho": lho})
        p += 46 + fnlen + extralen + comlen
    return entries


def sig_block_start(data, cdoff):
    """Start offset of the APK Signing Block, or cdoff if absent."""
    if cdoff >= 24 and data[cdoff - 16:cdoff] == SIG_BLOCK_MAGIC:
        (block_size,) = struct.unpack_from("<Q", data, cdoff - 24)
        start = cdoff - 24 - block_size
        if start >= 0 and struct.unpack_from("<Q", data, start)[0] == block_size:
            return start
    return cdoff


def rewrite_zip(data, new_manifest):
    eocd_idx, cdoff, cdsize, nrec, clen = find_eocd(data)
    entries = parse_cd(data, cdoff, nrec)
    man = next((e for e in entries if e["name"].decode("utf-8", "replace") == MANIFEST), None)
    if man is None:
        raise SystemExit("AndroidManifest.xml not in central directory")
    if man["method"] not in (0, 8):
        raise SystemExit(f"manifest method {man['method']} — refusing")
    if man["flags"] & 0x08:
        raise SystemExit("manifest uses a data descriptor — refusing")
    lho = man["lho"]
    assert data[lho:lho + 4] == b"PK\x03\x04", "bad local header"
    (lver, lflags, lmethod, ltime, ldate, lcrc, lcsize, lusize,
     lfnlen, lexlen) = struct.unpack_from("<HHHHHIIIHH", data, lho + 4)
    hdr_len = 30 + lfnlen + lexlen
    data_start = lho + hdr_len
    # End of the manifest's local span: next entry's local header, the
    # signing block, or the central directory — whichever comes first.
    later = [e["lho"] for e in entries if e["lho"] > lho]
    sig_start = sig_block_start(data, cdoff)
    span_end = min(later + [sig_start, cdoff])
    assert data_start + man["csize"] <= span_end, "manifest data overruns its span"
    block_len = cdoff - sig_start  # 0 when no signing block

    new_crc = binascii.crc32(new_manifest) & 0xFFFFFFFF
    new_size = len(new_manifest)
    old_local_total = span_end - lho  # header + data (+ descriptor, none)
    # New local header: same fields, fresh CRC/sizes, method STORED
    # (the new manifest is written uncompressed), data-descriptor
    # flag cleared.
    new_lh = bytearray(data[lho:data_start])
    struct.pack_into("<H", new_lh, 6, lflags & ~0x08)
    struct.pack_into("<H", new_lh, 8, 0)
    struct.pack_into("<I", new_lh, 14, new_crc)
    struct.pack_into("<I", new_lh, 18, new_size)
    struct.pack_into("<I", new_lh, 22, new_size)
    new_local_total = len(new_lh) + new_size
    delta = new_local_total - old_local_total  # negative (manifest shrank)

    out = bytearray()
    out += data[:lho]                 # everything before the manifest
    out += new_lh                     # new local header
    out += new_manifest               # new manifest data
    out += data[span_end:sig_start]   # entries after the manifest, verbatim
    # Central directory: same records, adjusted offsets/sizes.
    cd_start = len(out)
    for e in entries:
        off = e["lho"] + delta if e["lho"] > lho else e["lho"]
        crc, csize, usize = e["crc"], e["csize"], e["usize"]
        method = e["method"]
        if e is man:
            crc, csize, usize, method = new_crc, new_size, new_size, 0
        rec = struct.pack("<HHHHHHIIIHHHHHII", e["vmade"], e["vneed"],
                          e["flags"] & ~0x08 if e is man else e["flags"],
                          method, e["mtime"], e["mdate"],
                          crc, csize, usize, len(e["name"]), len(e["extra"]),
                          len(e["comment"]), e["disk"], e["iattr"],
                          e["eattr"], off)
        out += b"PK\x01\x02" + rec + e["name"] + e["extra"] + e["comment"]
    cd_end = len(out)
    # EOCD: same comment, updated CD offset/size.
    out += data[eocd_idx:eocd_idx + 4]
    out += struct.pack("<HHHHIIH", 0, 0, nrec, nrec, cd_end - cd_start,
                       cd_start, clen)
    out += data[eocd_idx + 22:eocd_idx + 22 + clen]
    assert len(out) == cd_end + 22 + clen
    return bytes(out)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        with open(sys.argv[2], "rb") as fh:
            data = fh.read()
        eocd_idx, cdoff, cdsize, nrec, clen = find_eocd(data)
        entries = parse_cd(data, cdoff, nrec)
        man = next(e for e in entries
                   if e["name"].decode("utf-8", "replace") == MANIFEST)
        lho = man["lho"]
        (lver, lflags, lmethod, ltime, ldate, lcrc, lcsize, lusize,
         lfnlen, lexlen) = struct.unpack_from("<HHHHHIIIHH", data, lho + 4)
        raw = data[lho + 30 + lfnlen + lexlen:
                   lho + 30 + lfnlen + lexlen + man["csize"]]
        axml = zlib.decompress(raw, -15) if man["method"] == 8 else raw
        names = manifest_attr_names(axml)
        if TARGET in names:
            print(f"CHECK FAIL: {TARGET} still present in {sys.argv[2]}")
            raise SystemExit(1)
        print(f"CHECK OK: no {TARGET} in {sys.argv[2]}")
        return
    if len(sys.argv) != 3:
        sys.stderr.write("usage: strip_required_splits.py <in.apk> <out.apk>\n"
                         "       strip_required_splits.py --check <apk>\n")
        raise SystemExit(2)
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, "rb") as fh:
        data = fh.read()
    # Locate + strip the manifest attribute (in-memory copy of the entry).
    eocd_idx, cdoff, cdsize, nrec, clen = find_eocd(data)
    entries = parse_cd(data, cdoff, nrec)
    man = next(e for e in entries if e["name"].decode("utf-8", "replace") == MANIFEST)
    lho = man["lho"]
    (lver, lflags, lmethod, ltime, ldate, lcrc, lcsize, lusize,
     lfnlen, lexlen) = struct.unpack_from("<HHHHHIIIHH", data, lho + 4)
    raw = data[lho + 30 + lfnlen + lexlen: lho + 30 + lfnlen + lexlen + man["csize"]]
    if man["method"] == 8:
        axml = zlib.decompress(raw, -15)
    elif man["method"] == 0:
        axml = raw
    else:
        raise SystemExit(f"manifest method {man['method']} — refusing")
    new_axml, removed = strip_attr(axml)
    names = manifest_attr_names(new_axml)
    assert TARGET not in names, "attribute still present after strip"
    out = rewrite_zip(data, new_axml)
    with open(dst, "wb") as fh:
        fh.write(out)
    print(f"requiredSplitTypes removed: {removed}")
    print(f"wrote {dst}: {len(data)} -> {len(out)} bytes "
          f"(manifest {len(axml)} -> {len(new_axml)})")


if __name__ == "__main__":
    main()
