#!/usr/bin/env python3
"""facepack2nx: a PC FC 27 face pack (FIFA Editor Tool .fifamod) -> a Switch RomFS mod for Peanuts Native (Mods) or Eden (LayeredFS).

For each player the pack and the Switch game both have a face for (the pack's var_1 or var_0, the game's var_0), each face texture
(color, normal, specmask; --hair adds the hair's color and coeff) is rebuilt in the Switch's own layout: the PC mip chain from the Switch's
size down (the Switch keeps half the PC's resolution, same block format), each level swizzled to the Tegra X1's block-linear layout
(nxtex.py), so the chunk keeps exactly the size, format and header the game expects; the game's res header and manifest stay as they are.
The new chunks go, as stored blocks, at the end of a small cas file the game always mounts (its original bytes kept in front); the
superbundle .tocs point there: their own chunk table (where the game looks a chunk up by GUID) and the bundles that list it (fbtoc.py).

  python facepack2nx.py <pack.fifamod> <analysis folder> <items.zip> <out.zip> [--hair] [--only name,name] [--cas <file>]

  analysis folder: Peanuts Nova's "Analyse for modding" output unpacked (index.tsv.gz, and tables.zip unpacked in tables/: romfs/<the tocs>)
  items.zip:       Peanuts Nova's "Extract items" output for these players (the game's texture headers)
  --cas:           the original of CAS below, when items.zip does not hold it (files/<its path>: Extract items' default expression names it)
"""
import argparse, gzip, io, os, re, struct, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbblocks, fbtoc, fetm, nxtex

CAS = "Patch/NX/superbundlelayout/commentaryfull_eng_us/cas_01.cas"   # 4 KiB, install chunk always installed
CAS_ID = fbtoc.cas_id(True, 0x881C4E65, 1)
TITLE = "0100C49025D3E000"
FACE = ("face_{id}_0_{v}_color", "face_{id}_0_{v}_normal", "face_{id}_0_{v}_specmask")
HAIR = ("hair_{id}_0_{v}_color", "hair_{id}_0_{v}_coeff")


def tex_header(b):
    """the fields of a Texture res (184 bytes) both platforms share"""
    fmt, = struct.unpack_from("<I", b, 0x0C)
    w, h, depth, slices = struct.unpack_from("<4H", b, 0x16)
    mips = b[0x1E]
    return {"format": fmt, "w": w, "h": h, "mips": mips, "chunk": b[0x28:0x38].hex(), "mip_sizes": struct.unpack_from("<15I", b, 0x38)}


def load_index(path, bundles=None):
    """(toc, bundle) -> [row] for every row of those bundles (all when bundles is None)"""
    out = {}
    with gzip.open(path, "rt") as f:
        next(f)
        for l in f:
            p = l.rstrip("\n").split("\t")
            k = (p[0], int(p[1]))
            if bundles is None or k in bundles: out.setdefault(k, []).append(p)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack"); ap.add_argument("analysis"); ap.add_argument("items"); ap.add_argument("out")
    ap.add_argument("--cas", help="the original " + CAS)
    ap.add_argument("--hair", action="store_true", help="the hair's textures too (they fit the pack's hair mesh, which stays the game's)")
    ap.add_argument("--only", default="", help="players (folder names, e.g. bukayo_saka_246669), comma-separated")
    ap.add_argument("--tocs", default="Patch,Data", help="which superbundle .toc copies to point at the new chunks (Patch, Data or both)")
    ap.add_argument("--name", default="FC27 Visages PC")
    a = ap.parse_args()

    mod = fetm.Mod(a.pack)
    z = zipfile.ZipFile(a.items)
    names = set(z.namelist())
    def game_item(kind, name):
        k = f"items/{kind}/{name.replace('/', '~')}.blocks"
        if k not in names: return None
        b, _ = fbblocks.decode(z.read(k)); return b

    # the pack's players and their variation
    players = {}
    for e in mod.res:
        m = re.match(r"(content/character/player/player_\d+/([^/]+))/var_(\d+)/face_(\d+)_0_\d+_color$", e["name"])
        if m: players[m.group(2)] = (m.group(1), m.group(3), m.group(4))
    only = set(filter(None, a.only.split(",")))
    if only: players = {k: v for k, v in players.items() if k in only}
    kinds = FACE + (HAIR if a.hair else ())

    # the game's side: the texture headers from items.zip, the bundles listing them from the index
    todo, wanted_bundles = [], set()
    items_rows = [l.split("\t") for l in z.read("items.tsv").decode().splitlines()]
    where = {}
    for r in items_rows: where.setdefault((r[2], r[3]), set()).add((r[0], int(r[1])))
    for folder, (base, var, pid) in sorted(players.items()):
        for k in kinds:
            pc_name = f"{base}/var_{var}/" + k.format(id=pid, v=var)
            nx_name = f"{base}/var_0/" + k.format(id=pid, v=0)
            pc = mod.res_by_name.get(pc_name); nxh = game_item("res", nx_name)
            if pc is None: continue
            if nxh is None: print(f"  {folder}: {k.split('_', 1)[0]}.. not in items.zip ({nx_name}), skipped"); continue
            todo.append((folder, pc_name, nx_name, pc, tex_header(nxh)))
            wanted_bundles |= where.get(("res", nx_name), set())
    print(f"{len(players)} players in the pack, {len(todo)} textures to convert")
    index = load_index(os.path.join(a.analysis, "index.tsv.gz"), wanted_bundles)

    if a.cas: cas = bytearray(open(a.cas, "rb").read())
    elif "files/" + CAS in names: cas = bytearray(z.read("files/" + CAS))
    else: raise SystemExit(f"items.zip has no files/{CAS}: extract it too, or give it with --cas")
    relocate = {}   # (toc, bundle) -> {record index: (offset, stored)}
    new_chunks = {}   # GUID -> (offset, stored) in the cas
    done = 0
    for folder, pc_name, nx_name, pc, nx in todo:
        pch = tex_header(mod.data(pc))
        ch = mod.chunk_by_id.get(pch["chunk"])
        if ch is None or "off" not in ch: print(f"  {nx_name}: the pack has no data for its chunk, skipped"); continue
        pcd = mod.data(ch)
        bpb = pch["mip_sizes"][0] // (nxtex._ceil(pch["w"], 4) * nxtex._ceil(pch["h"], 4))
        if pch["w"] < nx["w"] or pch["w"] % nx["w"] or pch["h"] * nx["w"] != nx["h"] * pch["w"]:
            print(f"  {nx_name}: PC {pch['w']}x{pch['h']} for Switch {nx['w']}x{nx['h']}, skipped"); continue
        k = (pch["w"] // nx["w"]).bit_length() - 1
        if k + nx["mips"] > pch["mips"]: print(f"  {nx_name}: the pack has {pch['mips']} mips, {k + nx['mips']} needed, skipped"); continue
        levels = nxtex.linear_levels(pcd, pch["w"], pch["h"], bpb, pch["mips"])[k:k + nx["mips"]]
        data = nxtex.nx_chain(levels, nx["w"], nx["h"], bpb)
        # where the game lists that chunk, and its size there: it must be ours
        locs = []
        for key, rows in index.items():
            for i, r in enumerate(rows):
                if r[2] == "chunk" and r[3] == nx["chunk"]:
                    if int(r[4]) != len(data):
                        raise SystemExit(f"{nx_name}: the game's chunk is {r[4]} bytes, the rebuilt one {len(data)} (format {pch['format']:#x} -> {nx['format']:#x})")
                    locs.append((key, i + 1))
        locs = [(key, i) for key, i in locs if key[0].split("/")[0] in a.tocs.split(",")]
        if not locs: print(f"  {nx_name}: its chunk is in no bundle of the index, skipped"); continue
        stored = fbblocks.encode_stored(data)
        while len(cas) % 16: cas.append(0)
        off = len(cas); cas += stored
        for key, i in locs: relocate.setdefault(key, {})[i] = (off, len(stored))
        new_chunks[nx["chunk"]] = (off, len(stored))
        done += 1
        print(f"  {folder}: {nx_name.rsplit('/', 1)[1]} {nx['w']}x{nx['h']} {nx['mips']} mips, format PC {pch['format']:#x} / Switch {nx['format']:#x} -> {len(locs)} bundle(s)")

    tocs = {}
    rd = next(p for p in (os.path.join(a.analysis, "romfs"), os.path.join(a.analysis, "tables", "romfs")) if os.path.isdir(p))
    # the superbundles' own chunk tables: where the game really looks a chunk up (by GUID); every .toc that lists one is rewritten
    n_tab = 0
    for dp, _, fs in os.walk(rd):
        for f in fs:
            if not f.endswith(".toc") or f == "layout.toc": continue
            toc = os.path.relpath(os.path.join(dp, f), rd).replace(os.sep, "/")
            if toc.split("/")[0] not in a.tocs.split(","): continue
            d = open(os.path.join(dp, f), "rb").read()
            if len(d) < fbtoc.BODY + 0x40: continue
            tab = fbtoc.chunk_table(d); hit = [g for g in new_chunks if g in tab]
            if not hit: continue
            d = bytearray(tocs.get(toc, d))
            for g in hit:
                off, st = new_chunks[g]; fbtoc.set_chunk(d, tab[g], CAS_ID, off, st); n_tab += 1
            tocs[toc] = bytes(d)
    print(f"{n_tab} chunk table records in {len(tocs)} tocs")
    for (toc, bi), recs in sorted(relocate.items()):
        if toc not in tocs: tocs[toc] = open(os.path.join(rd, toc), "rb").read()
        items = fbtoc.read_block(tocs[toc], bi)
        for i, (off, st) in recs.items(): items[i] = (CAS_ID, off, st, items[i][3])
        tocs[toc] = fbtoc.replace_block(tocs[toc], bi, items)
    root = f"{a.name}/romfs/"
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as o:
        o.writestr(root + CAS, bytes(cas))
        for toc, b in tocs.items(): o.writestr(root + toc, b)
    print(f"{done} textures in {len(relocate)} bundles; {len(cas) >> 20} MiB cas; {len(tocs)} tocs -> {a.out}")


if __name__ == "__main__":
    main()
