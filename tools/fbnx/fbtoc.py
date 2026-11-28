"""Frostbite NX superbundle .toc (FC 27 on Switch): read and rewrite where a bundle's items are.

File: magic 00D1CE01, an RSA signature and its key text, the body at 0x22C (big-endian). Body header u32[16]: [1] the bundle table's
offset, [2] the bundle count, ... [14] where the bundle blocks start; they run to the end of the file.
Bundle table: 16 bytes per bundle {u32 ?, u32 0x40000000 | block size, u64 block offset (from the body)}.
Bundle block: u32[9] {0, 0, flags offset, n, 36, 36, 36, 0, n}, then the records, then one flag byte per item. A record is
{cas id (8 bytes, only where the item's flag has 0x80: the first item and each change of cas file), u32 offset, u32 stored size};
item 0 is the bundle's manifest (flag 0x84), then its ebx, res and chunks in the manifest's order.
A cas id: {0, 1 if Patch else 0, u32 install chunk persistentIndex, u16 cas number} -> <Data|Patch>/NX/<install chunk name>/cas_<nn>.cas.
"""
import struct

TOC_MAGIC, BODY = bytes.fromhex("00d1ce01"), 0x22C


def header(d): return struct.unpack_from(">16I", d, BODY)


def table_pos(d, bi): return BODY + header(d)[1] + 16 * bi


def nbundles(d): return header(d)[2]


def read_block(d, bi):
    """[(cas id, offset, stored, flag)] of bundle bi"""
    _, sz, off = struct.unpack_from(">IIQ", d, table_pos(d, bi))
    s = BODY + off
    z0, z1, fo, n, p, p2, p3, z2, n2 = struct.unpack_from(">9I", d, s)
    p += s; fo += s; cas, out = None, []
    for k in range(n):
        f = d[fo + k]
        if f & 0x80 or cas is None: cas = bytes(d[p:p + 8]); p += 8
        o, z = struct.unpack_from(">II", d, p); p += 8
        out.append((cas, o, z, f))
    return out


def encode_block(items):
    """items [(cas id, offset, stored, flag)] -> a bundle block, the 0x80 flag (and its cas id) set exactly where the cas file changes"""
    recs, flags, cur = bytearray(), bytearray(), None
    for k, (cas, o, z, f) in enumerate(items):
        if k == 0 or cas != cur:
            f |= 0x80; recs += cas; cur = cas
        else:
            f &= ~0x80 & 0xFF
        recs += struct.pack(">II", o, z); flags.append(f)
    n = len(items); fo = 36 + len(recs)
    return struct.pack(">9I", 0, 0, fo, n, 36, 36, 36, 0, n) + bytes(recs) + bytes(flags)


def replace_block(d, bi, items):
    """d with bundle bi's items replaced: the block rewritten in place when it is no larger, else appended at the end of the file"""
    d = bytearray(d); tp = table_pos(d, bi)
    a, sz, off = struct.unpack_from(">IIQ", d, tp)
    blk = encode_block(items)
    if len(blk) <= (sz & 0x3FFFFFFF):
        d[BODY + off:BODY + off + len(blk)] = blk; new_off = off
    else:
        while len(d) % 4: d.append(0)
        new_off = len(d) - BODY; d += blk
    struct.pack_into(">IIQ", d, tp, a, (sz & 0xC0000000) | len(blk), new_off)
    return bytes(d)


def cas_id(patch, persistent_index, n):
    return struct.pack(">BBIH", 0, 1 if patch else 0, persistent_index & 0xFFFFFFFF, n)


def cas_path(cid, chunk_names):
    pi, n = struct.unpack_from(">IH", cid, 2)
    return f"{'Patch' if cid[1] else 'Data'}/NX/{chunk_names[pi]}/cas_{n:02d}.cas"
