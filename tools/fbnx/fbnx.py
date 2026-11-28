#!/usr/bin/env python3
"""fbnx: Frostbite game data on the Nintendo Switch (EA SPORTS FC 27, Frostbite 2025.1.2), for modding through Eden's LayeredFS.

Formats after Peanuts Native's dm/gfx/tools/frostbite.py (GPL-3.0-or-later), which reads the same game's RomFS:
  Data/layout.toc        DbObject; installManifest.installChunks: {name 'superbundlelayout/<name>', persistentIndex}
  <Data|Patch>/NX/*.toc  superbundle tables: magic 00 D1 CE 01, body at +0x22c (big-endian): +4 bundle table, +8 bundle count,
                         +0x14 chunk count, +0x18 chunk table. Bundle {u32 name, u32 0x40000000 | size, u64 offset}; its entries
                         {u32 offset, u32 stored size} in a cas file, after an 8-byte cas id when the entry's flag has bit 7 set.
  cas id                 {u8 0, u8 1 = Patch / 0 = Data, u32 install chunk persistentIndex, u16 cas number}
  manifest               entry 0 of a bundle, stored as it is (never compressed): ebx, res (with type hashes), chunks, names
  item data              blocks {u32 BE size, u8 codec (0 stored, 0x19 Oodle Leviathan), u8 0x70|hi, u16 BE stored size}

Steps (each works on a folder extracted with EdEn.claude's "Extract game files", which keeps the romfs/ and exefs/ paths):
  info <extract dir>                       install chunks, superbundles, bundle and chunk counts
  plan-manifests <extract dir> [--toc RE] [--max N]
                                           the EdEn.claude filter lines that extract the bundle manifests (byte ranges of the cas
                                           files) of the superbundles whose path matches RE: the next extraction step
  manifests <extract dir> [--toc RE] [--grep RE]
                                           with those ranges extracted: every ebx / res / chunk name, filtered by RE
"""
import argparse, os, re, struct, sys

TOC_MAGIC, TOC_BODY, BUNDLE_MAGIC = bytes.fromhex("00d1ce01"), 0x22C, 0x9D798ED6


def name_hash(name):
    """Frostbite's type-name hash (res types): name_hash('Texture') = 0x6bde20ba, 'MeshSet' 0x49b156d4"""
    h = 5381
    for c in name.lower().encode(): h = (h * 33 ^ c) & 0xFFFFFFFF
    return h

RES_TYPES = {name_hash(n): n for n in ("Texture", "MeshSet", "CompiledBytecode", "RigidMeshSet", "SkinnedMeshSet", "HavokPhysicsData",
                                         "ShaderBlockDepot", "AnimTrackData", "SwfMovie", "Dx11Texture", "IesResource", "HeightfieldDecal")}


def _leb(d, p):
    v = s = 0
    while True:
        b = d[p]; p += 1; v |= (b & 0x7F) << s; s += 7
        if not b & 0x80: return v, p


def dbobject(d, p):
    t = d[p]; p += 1; name = None
    if not t & 0x80:
        e = d.index(b"\0", p); name = d[p:e].decode(errors="replace"); p = e + 1
    k = t & 0x1F
    if k in (1, 2):
        n, p = _leb(d, p); end = p + n; items = []
        while p < end and d[p]: it, p = dbobject(d, p); items.append(it)
        return (name, dict(items) if k == 2 else [v for _, v in items]), end
    if k == 7: n, p = _leb(d, p); return (name, d[p:p + n - 1].decode(errors="replace")), p + n
    if k == 19: n, p = _leb(d, p); return (name, bytes(d[p:p + n])), p + n
    fixed = {6: ("<?", 1), 8: ("<i", 4), 9: ("<q", 8), 0xB: ("<f", 4), 0xC: ("<d", 8)}
    if k in fixed: return (name, struct.unpack_from(fixed[k][0], d, p)[0]), p + fixed[k][1]
    if k in (0xF, 0x10): n = 16 if k == 0xF else 20; return (name, bytes(d[p:p + n])), p + n
    raise ValueError(f"DbObject: type {t:#x} at {p - 1:#x} is not known")


def install_chunks(root):
    d = open(os.path.join(root, "romfs", "Data", "layout.toc"), "rb").read()
    (_, lay), _ = dbobject(d, TOC_BODY)
    return {c["persistentIndex"] & 0xFFFFFFFF: c["name"] for c in lay["installManifest"]["installChunks"]}


def tocs(root, pattern=None):
    out = []
    for top in ("Data", "Patch"):
        for dp, _, fs in os.walk(os.path.join(root, "romfs", top, "NX")):
            for f in sorted(fs):
                p = os.path.join(dp, f)
                if f.endswith(".toc") and (not pattern or re.search(pattern, os.path.relpath(p, root))): out.append(p)
    return out


def toc_bundles(d, what="toc"):
    """[[(cas id, offset, stored size), …] per bundle], entry 0 its manifest"""
    if d[:4] != TOC_MAGIC: raise ValueError(f"{what}: not a Frostbite toc")
    if len(d) < TOC_BODY + 0x20: return []
    B = TOC_BODY; bo, nb = struct.unpack_from(">II", d, B + 4)
    out = []
    for i in range(nb):
        _, sz, off = struct.unpack_from(">IIQ", d, B + bo + 16 * i)
        s = B + off; end = s + (sz & 0xFFFFFF)
        fo, n, p = struct.unpack_from(">III", d, s + 8)
        p += s; fo += s; cas, ents = None, []
        for k in range(n):
            if d[fo + k] & 0x80 or cas is None: cas = bytes(d[p:p + 8]); p += 8
            ents.append((cas,) + struct.unpack_from(">II", d, p)); p += 8
        if p != fo: raise ValueError(f"{what}: bundle {i}: entries end at {p - s:#x}, flags at {fo - s:#x}")
        out.append(ents)
    return out


def toc_chunk_count(d):
    return struct.unpack_from(">I", d, TOC_BODY + 0x14)[0] if len(d) >= TOC_BODY + 0x20 else 0


def cas_rel(cid, chunks):
    """The cas file a cas id names, as an extraction path (romfs/…)"""
    pi, n = struct.unpack_from(">IH", cid, 2)
    return f"romfs/{'Patch' if cid[1] else 'Data'}/NX/{chunks[pi]}/cas_{n:02d}.cas"


def manifest(d, off=0):
    hl = struct.unpack_from(">I", d, off)[0]; magic, tot, ne, nr, nc, so = struct.unpack_from("<6I", d, off + 4)
    if magic != BUNDLE_MAGIC: raise ValueError(f"no bundle manifest at {off:#x}")
    h = off + 4; p = h + 0x20 + 20 * tot
    ebx = [struct.unpack_from("<II", d, p + 8 * i) for i in range(ne)]; p += 8 * ne
    res = [struct.unpack_from("<II", d, p + 8 * i) for i in range(nr)]; p += 8 * nr
    types = struct.unpack_from(f"<{nr}I", d, p); p += 4 * nr + 24 * nr
    ch = [struct.unpack_from("<16sII", d, p + 24 * i) for i in range(nc)]
    def name(o):
        a = h + so + o; return bytes(d[a:d.find(b"\0", a)]).decode(errors="replace")
    return ([(name(a), s) for a, s in ebx], [(name(a), s, t) for (a, s), t in zip(res, types)], ch)


def cmd_info(root):
    chunks = install_chunks(root)
    print(f"{len(chunks)} install chunks")
    nb = nc = 0
    for t in tocs(root):
        d = open(t, "rb").read(); b = toc_bundles(d, t); c = toc_chunk_count(d); nb += len(b); nc += c
        print(f"  {os.path.relpath(t, root)}: {len(b)} bundles, {c} chunks")
    print(f"{nb} bundles, {nc} chunks in all")


def cmd_plan(root, pattern, cap):
    chunks = install_chunks(root); lines = []
    for t in tocs(root, pattern):
        for ents in toc_bundles(open(t, "rb").read(), t):
            cid, off, size = ents[0]
            lines.append(f"{cas_rel(cid, chunks)}@{off:#x}+{size:#x}")
    lines = sorted(set(lines))
    if cap and len(lines) > cap: print(f"# {len(lines)} manifests, the first {cap} kept (--max)", file=sys.stderr); lines = lines[:cap]
    print("\n".join(lines))
    print(f"# {len(lines)} manifest ranges", file=sys.stderr)


def cmd_manifests(root, pattern, grep):
    chunks = install_chunks(root); rx = re.compile(grep) if grep else None
    for t in tocs(root, pattern):
        for ents in toc_bundles(open(t, "rb").read(), t):
            cid, off, size = ents[0]
            p = os.path.join(root, f"{cas_rel(cid, chunks)}@{off:#x}+{size:#x}")
            if not os.path.exists(p): continue
            ebx, res, ch = manifest(open(p, "rb").read())
            for n, s in ebx:
                if not rx or rx.search(n): print(f"ebx\t{n}\t{s}")
            for n, s, ty in res:
                if not rx or rx.search(n): print(f"res\t{n}\t{s}\t{RES_TYPES.get(ty, hex(ty))}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("info"); a.add_argument("root")
    a = sp.add_parser("plan-manifests"); a.add_argument("root"); a.add_argument("--toc"); a.add_argument("--max", type=int, default=0)
    a = sp.add_parser("manifests"); a.add_argument("root"); a.add_argument("--toc"); a.add_argument("--grep")
    a = ap.parse_args()
    if a.cmd == "info": cmd_info(a.root)
    elif a.cmd == "plan-manifests": cmd_plan(a.root, a.toc, a.max)
    else: cmd_manifests(a.root, a.toc, a.grep)


if __name__ == "__main__":
    main()
