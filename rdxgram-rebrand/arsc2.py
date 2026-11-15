"""Minimal correct resources.arsc parser (stdlib only).

Recreated 2026-11-14 after /tmp was wiped; logic copied from the
proven parse_arsc in verify_layout_values.py (same offsets, same
rules). Rules that matter:
- the entry-offsets array is at type_chunk_start + headerSize
  (NOT at entriesStart);
- each entry struct is at type_chunk_start + entriesStart + offset;
- the Res_value is at entry+8 (dtype at entry+11, data at entry+12);
- dtype 0x03 = string, 0x01 = reference, 0x05 = dimension.
parse(apk) -> (main_string_pool, entries) where entries maps
(type_id, entry_id) -> {'type','name','dtype','data'}.
val() resolves a string/reference value one hop at a time.
"""
import struct
import zipfile


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


UTF8 = 0x100


class SP:
    def __init__(self, data, off):
        self.utf8 = bool(u32(data, off + 16) & UTF8)
        self.count = u32(data, off + 8)
        self.ss = u32(data, off + 20)
        self.off = off
        self.data = data
        self.offsets = [u32(data, off + 28 + 4 * i) for i in range(self.count)]

    def get(self, idx):
        if idx >= self.count:
            return None
        o = self.off + self.ss + self.offsets[idx]
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
        ln = u16(self.data, o)
        if ln & 0x8000:
            ln = ((ln & 0x7FFF) << 16) | u16(self.data, o + 2)
            o += 4
        else:
            o += 2
        return self.data[o:o + ln * 2].decode("utf-16-le", "replace")


def parse(apk):
    with zipfile.ZipFile(apk) as z:
        arsc = z.read("resources.arsc")
    main_sp = None
    entries = {}
    off = 12
    while off < len(arsc):
        ct = u16(arsc, off)
        cs = u32(arsc, off + 4)
        if cs == 0:
            break
        if ct == 0x0001 and main_sp is None:
            main_sp = SP(arsc, off)
        if ct == 0x0200:  # ResTable_package
            hdr = u16(arsc, off + 2)
            tso = off + u32(arsc, off + hdr - 20)
            kso = off + u32(arsc, off + hdr - 12)
            tp = SP(arsc, tso)
            kp = SP(arsc, kso)
            poff = off + hdr
            while poff < off + cs:
                tt = u16(arsc, poff)
                ts = u32(arsc, poff + 4)
                if ts == 0:
                    break
                if tt == 0x0201:  # ResTable_type
                    tid = arsc[poff + 8]
                    header_size = u16(arsc, poff + 2)
                    entry_count = u32(arsc, poff + 12)
                    entries_start = u32(arsc, poff + 16)
                    tname = tp.get(tid - 1)
                    for eid in range(entry_count):
                        o = u32(arsc, poff + header_size + 4 * eid)
                        if o == 0xFFFFFFFF:
                            continue
                        key = (tid, eid)
                        if key in entries:
                            continue
                        eo = poff + entries_start + o
                        kidx = u32(arsc, eo + 4)
                        flags = u16(arsc, eo + 2)
                        if flags & 1:  # complex bag
                            dtype, vdata = None, None
                        else:
                            dtype = arsc[eo + 11]
                            vdata = u32(arsc, eo + 12)
                        entries[key] = {
                            'type': tname,
                            'name': kp.get(kidx),
                            'dtype': dtype,
                            'data': vdata,
                        }
                poff += ts
        off += cs
    return main_sp, entries


def val(entries, main_sp, tid, eid, depth=0):
    """getString()-like resolve: plain string returned as-is; a
    reference is followed one hop (up to 3). Returns None for
    dimensions and other non-string values."""
    e = entries.get((tid, eid))
    if e is None:
        return None
    dtype, data = e['dtype'], e['data']
    if dtype == 0x03:  # TYPE_STRING
        return main_sp.get(data)
    if dtype == 0x01 and depth < 3:  # TYPE_REFERENCE
        return val(entries, main_sp, (data >> 16) & 0xFF,
                   data & 0xFFFF, depth + 1)
    return None


_DIM_RADIX = [1.0, 1.0 / 256, 1.0 / 65536, 1.0 / 16777216]
_DIM_UNITS = {0: "px", 1: "dp", 2: "sp", 3: "pt", 4: "in", 5: "mm"}


def decode_dimension(data):
    unit = data & 0xF
    radix = (data >> 4) & 0x3
    mantissa = data >> 8
    if mantissa & 0x800000:
        mantissa -= 0x1000000
    return mantissa * _DIM_RADIX[radix], _DIM_UNITS.get(unit, "?")
