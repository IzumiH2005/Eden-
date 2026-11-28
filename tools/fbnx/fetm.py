"""FIFA Editor Tool mods (.fifamod, magic "FETM", version 3), as written for FC 27 (reverse-engineered on ViP3eR's AIO FacePack V2 1.3.0).

  "FETM" u8 3, then 7-bit-length strings: game ("FC27"), 7 bytes, title, author, 2 bytes, category, then description, links...; a JPEG thumbnail (7-bit
  length first); u64, 6 zero bytes, u32 data base (absolute), u32 file size, 6 zero bytes; then four tables, each "u16 count, u8 0" then its entries:
  bundles  [u8 len][name][u64 hash][u32 handler]                     the bundles the mod adds
  ebx      name, u8 flags, sha1[20], varint offset, stored, size;    flags 0x04: u32 handler + linked asset name;
           then varint n + n x u64 bundle hashes (the bundles the asset goes in)
           then one more list: varint n + n x u64 (bundles... of the mod's own, 133 here)
  res      name, u8 flags, sha1[20], offset, stored, size, (0x04: u32 + name), bundle list,
           then u32 res type + u64 rid when the bundle list is not empty, 16 bytes res meta, (0x80: varint n + n x {u64, varint})
  chunks   guid[16], sha1[20], u8 flags, (0x80: varint), then (0x20) offset, stored, size, 8 bytes (h32 + first mip...),
           bundle list, (0x04: u32 handler); without 0x20 {u8, u32, varint, varint}
  then the handler (legacy) entries, and the data: every item's stored blocks (fbblocks) at data base + offset, end to end.
Offsets checked: the ebx, res and chunk data run end to end and finish exactly at the end of the file.
"""
import struct


class R:
    def __init__(s, d, p): s.d = d; s.p = p
    def u8(s): v = s.d[s.p]; s.p += 1; return v
    def vi(s):
        r = sh = 0
        while True:
            b = s.u8(); r |= (b & 0x7F) << sh; sh += 7
            if b < 0x80: return r
    def raw(s, n): v = s.d[s.p:s.p + n]; s.p += n; return bytes(v)
    def s7(s): return s.raw(s.vi()).decode("utf-8", "replace")
    def count(s): n = struct.unpack_from("<H", s.d, s.p)[0]; s.p += 3; return n


class Mod:
    def __init__(self, path):
        self.d = d = open(path, "rb").read()
        if d[:4] != b"FETM": raise ValueError(f"{path}: not a FETM .fifamod")
        r = R(d, 5)
        self.game = r.s7(); r.p += 7   # then 7 bytes (the game's version...)
        self.title = r.s7(); self.author = r.s7(); r.p += 2; self.category = r.s7()
        jpg = d.find(b"\xff\xd8\xff", r.p)   # the thumbnail, after a 7-bit length: the strings before it vary (links)
        for k in range(1, 5):
            n = R(d, jpg - k).vi()
            if d[jpg + n - 2:jpg + n] == b"\xff\xd9": break
        else: raise ValueError(f"{path}: no thumbnail length")
        end = jpg + n   # then u64, 6 zero bytes, u32 data base, u32 file size, 6 zero bytes
        self.base, self.size = struct.unpack_from("<II", d, end + 14)
        if self.size != len(d): raise ValueError(f"{path}: size field {self.size} for {len(d)} bytes")
        r.p = end + 28
        self.bundles = []
        for _ in range(r.count()):
            self.bundles.append({"name": r.raw(r.u8()).decode(), "hash": r.raw(8).hex(), "handler": r.raw(4).hex()})
        self.ebx = [self._ebx(r) for _ in range(r.count())]
        self.extra = [r.raw(8).hex() for _ in range(r.vi())]
        self.res = [self._res(r) for _ in range(r.count())]
        self.chunks = [self._chunk(r) for _ in range(r.count())]
        self.tail = r.p
        self.res_by_name = {e["name"]: e for e in self.res}
        self.ebx_by_name = {e["name"]: e for e in self.ebx}
        self.chunk_by_id = {c["id"]: c for c in self.chunks}

    @staticmethod
    def _bundles(r): return [r.raw(8).hex() for _ in range(r.vi())]

    def _ebx(self, r):
        e = {"name": r.s7(), "flags": r.u8()}
        if e["flags"] & ~0x34: raise ValueError(f"ebx flags {e['flags']:#x} at {r.p:#x}")
        if e["flags"] & 0x10: e["sha1"] = r.raw(20).hex(); e["off"] = r.vi(); e["stored"] = r.vi(); e["size"] = r.vi()
        if e["flags"] & 0x04: e["handler"] = r.raw(4).hex(); e["link"] = r.s7()
        e["bundles"] = self._bundles(r)
        return e

    def _res(self, r):
        e = {"name": r.s7(), "flags": r.u8()}
        if e["flags"] & ~0xB4: raise ValueError(f"res flags {e['flags']:#x} at {r.p:#x}")
        e["sha1"] = r.raw(20).hex(); e["off"] = r.vi(); e["stored"] = r.vi(); e["size"] = r.vi()
        if e["flags"] & 0x04: e["handler"] = r.raw(4).hex(); e["link"] = r.s7()
        e["bundles"] = self._bundles(r)
        if e["bundles"]: e["type"] = struct.unpack("<I", r.raw(4))[0]; e["rid"] = r.raw(8)[::-1].hex()
        e["meta"] = r.raw(16).hex()
        if e["flags"] & 0x80: e["deps"] = [(r.raw(8).hex(), r.vi()) for _ in range(r.vi())]
        return e

    def _chunk(self, r):
        c = {"id": r.raw(16).hex(), "sha1": r.raw(20).hex(), "flags": r.u8()}
        c["first_mip"] = r.vi() if c["flags"] & 0x80 else None
        if not c["flags"] & 0x20:
            c["ref"] = (r.u8(), r.raw(4).hex(), r.vi(), r.vi()); return c
        c["off"] = r.vi(); c["stored"] = r.vi(); c["size"] = r.vi(); c["x"] = r.raw(8).hex()
        c["bundles"] = self._bundles(r)
        if c["flags"] & 0x04: c["handler"] = r.raw(4).hex()
        return c

    def data(self, e):
        """an entry's bytes (decoded)"""
        import fbblocks
        b, _ = fbblocks.decode(self.d, self.base + e["off"], e["stored"])
        if len(b) != e["size"]: raise ValueError(f"{e.get('name', e.get('id'))}: {len(b)} bytes for {e['size']}")
        return b


if __name__ == "__main__":
    import sys, collections
    m = Mod(sys.argv[1])
    print(f"{m.game} {m.title!r} by {m.author}: {len(m.bundles)} bundles, {len(m.ebx)} ebx, {len(m.res)} res, {len(m.chunks)} chunks")
    spans = sorted((e["off"], e["stored"]) for e in m.ebx + m.res + m.chunks if "off" in e)
    print("data ends at the file's end:", m.base + spans[-1][0] + spans[-1][1] == len(m.d))
    print("res types:", collections.Counter(f"{e.get('type', 0):08x}" for e in m.res).most_common())
