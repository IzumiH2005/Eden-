#!/usr/bin/env python3
"""fifamod2nx: PC FC 27 mods (FIFA Editor Tool .fifamod) -> one Switch RomFS mod for Peanuts Native (Mods) or Eden (LayeredFS).

What a mod changes in assets the Switch game has too, under the same name:
  textures (res Texture): the chunk rebuilt in the Switch's layout (facepack2nx's way: the PC mips from the Switch's size down, swizzled
      for the Tegra X1), so its size, format and header stay the game's; skipped when the formats differ or the PC one is smaller
  ebx: the PC asset as it is (EBX is the same on both platforms); the bundle's manifest gets the new size when it changes
New data goes at the end of the small cas file the game always mounts (facepack2nx.CAS); the bundles of the superbundle .tocs and their
own chunk tables point there. Not converted (reported): other res types (meshes, sounds...), assets the Switch game does not have, new
bundles, legacy files (chunkfiles: xml, .big).

  python fifamod2nx.py <analysis folder> <items.zip> <out.zip> <mod.fifamod>... [--base <a mod zip>] [--name "Mod name"] [--no-ebx]

  analysis folder: Peanuts Nova's "Analyse for modding" output unpacked (index.tsv.gz, tables/romfs/<the tocs>)
  items.zip:       Peanuts Nova's "Extract items" output for these assets (and files/<facepack2nx.CAS>)
  --base:          a mod zip made by these tools (facepack2nx, this) to build on: its cas and tocs are the starting point, so one mod
                   holds both (two mods shipping the same cas and tocs would hide each other)
"""
import argparse, os, re, struct, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbblocks, fbtoc, fetm, nxtex
from facepack2nx import CAS, CAS_ID, tex_header, load_index

TEXTURE = "6bde20ba"


class Skip(Exception): pass


def bytes_per_block(h):
    blocks = nxtex._ceil(h["w"], 4) * nxtex._ceil(h["h"], 4)
    return h["mip_sizes"][0] // blocks if blocks else 0


def convert_texture(pch, pcd, nx):
    """a PC texture's chunk (pch its header, pcd its data) -> the chunk for the Switch header nx"""
    if pch["format"] != nx["format"]: raise Skip(f"format PC {pch['format']:#x}, Switch {nx['format']:#x}")
    bpb = bytes_per_block(pch)
    if bpb not in (8, 16): raise Skip(f"{bpb} bytes per block")
    if pch["w"] < nx["w"] or pch["w"] % nx["w"] or pch["h"] * nx["w"] != nx["h"] * pch["w"]:
        raise Skip(f"PC {pch['w']}x{pch['h']}, Switch {nx['w']}x{nx['h']}")
    k = (pch["w"] // nx["w"]).bit_length() - 1
    if k + nx["mips"] > pch["mips"]: raise Skip(f"PC {pch['mips']} mips, {k + nx['mips']} needed")
    levels = nxtex.linear_levels(pcd, pch["w"], pch["h"], bpb, pch["mips"])[k:k + nx["mips"]]
    return nxtex.nx_chain(levels, nx["w"], nx["h"], bpb)


def manifest_set_size(raw, kind, i, size):
    """a bundle manifest (as stored: u32 BE length, then the body) with the size of its i-th ebx or res changed"""
    b = bytearray(raw); h = 4
    magic, total, ne, nr = struct.unpack_from("<4I", b, h)
    if magic != 0x9D798ED6: raise ValueError("not a bundle manifest")
    p = h + 32 + 20 * total + 8 * (i if kind == "ebx" else ne + i) + 4
    struct.pack_into("<I", b, p, size)
    return bytes(b)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("analysis"); ap.add_argument("items"); ap.add_argument("out"); ap.add_argument("mods", nargs="+")
    ap.add_argument("--base"); ap.add_argument("--name", default="FC27 Mod PC")
    ap.add_argument("--no-ebx", action="store_true", help="textures only")
    ap.add_argument("--skip", default="", help="regex: assets of the mods to leave out")
    ap.add_argument("--rename", action="append", default=[], help="PATTERN=>REPLACEMENT (re.sub) from a mod's names to the game's")
    ap.add_argument("--tocs", default="Patch,Data")
    a = ap.parse_args()
    tocsel = a.tocs.split(","); skip = re.compile(a.skip) if a.skip else None
    renames = [(re.compile(x.split("=>")[0]), x.split("=>")[1]) for x in a.rename]
    def game_name(n):
        for rx, to in renames: n = rx.sub(to, n)
        return n.lower()
    mods = [fetm.Mod(p) for p in a.mods]
    wanted = {("ebx", game_name(e["name"])) for m in mods for e in m.ebx} | {("res", game_name(e["name"])) for m in mods for e in m.res}
    in_game = set()   # which of them the Switch game has (the analysis' index)
    import gzip
    with gzip.open(os.path.join(a.analysis, "index.tsv.gz"), "rt") as f:
        for l in f:
            p = l.split("\t", 4)
            if (p[2], p[3].lower()) in wanted: in_game.add((p[2], p[3].lower()))

    z = zipfile.ZipFile(a.items); names = z.namelist()
    item_key = {}
    for n in names:
        m = re.match(r"items/(ebx|res|chunk)/(.+)\.blocks$", n)
        if m: item_key[(m.group(1), m.group(2).replace("~", "/").lower())] = n
    def game_item(kind, name):
        k = item_key.get((kind, name.lower()))
        return fbblocks.decode(z.read(k))[0] if k else None
    rows = [l.split("\t") for l in z.read("items.tsv").decode().splitlines()]
    where, rtype = {}, {}
    for r in rows:
        where.setdefault((r[2], r[3].lower()), set()).add((r[0], int(r[1])))
        if r[2] == "res": rtype[r[3].lower()] = r[5]

    # what each mod changes, later mods over earlier ones
    chunk_ops, ebx_ops, report = {}, {}, []   # GUID -> data; name -> data; (mod, kind, name, what)
    for mod in mods:
        t = mod.title
        used_chunks = set()
        for e in mod.res:
            n = game_name(e["name"])
            if skip and skip.search(n): continue
            ty = rtype.get(n)
            if ty is None:
                report.append((t, "res", n, "absent du jeu Switch" if ("res", n) not in in_game else "pas dans items.zip")); continue
            if ty != TEXTURE: report.append((t, "res", n, f"type {ty} (pas une texture) : non converti")); continue
            nx = tex_header(game_item("res", n)); pch = tex_header(mod.data(e)); used_chunks.add(pch["chunk"])
            ch = mod.chunk_by_id.get(pch["chunk"])
            if ch is None or "off" not in ch: report.append((t, "res", n, "le mod n'a pas les données de la texture")); continue
            try: chunk_ops[nx["chunk"]] = (convert_texture(pch, mod.data(ch), nx), n)
            except Skip as x: report.append((t, "res", n, f"texture non convertie : {x}")); continue
            report.append((t, "res", n, f"texture {nx['w']}x{nx['h']} ok"))
        for c in mod.chunks:
            if c["id"] in used_chunks: continue
            what = f"fichier legacy {c['legacy']}" if "legacy" in c else "chunk sans texture"
            report.append((t, "chunk", c["id"], what + " : non converti"))
        if a.no_ebx: continue
        for e in mod.ebx:
            n = game_name(e["name"])
            if skip and skip.search(n): continue
            sw = game_item("ebx", n)
            if sw is None:
                report.append((t, "ebx", n, "absent du jeu Switch" if ("ebx", n) not in in_game else "pas dans items.zip")); continue
            pc = mod.data(e)
            if pc[:4] != sw[:4] or pc[8:16] != sw[8:16]: report.append((t, "ebx", n, "en-tête EBX différent : non converti")); continue
            ebx_ops[n] = pc
            same = len(pc) == len(sw)
            diff = sum(x != y for x, y in zip(pc, sw)) if same else None
            report.append((t, "ebx", n, f"ebx ok ({'même taille, %d octets changés' % diff if same else '%d -> %d octets' % (len(sw), len(pc))})"))

    # where the game lists them
    want = set()
    for n in ebx_ops: want |= where.get(("ebx", n), set())
    for g in chunk_ops: want |= where.get(("chunk", g), set())
    want = {k for k in want if k[0].split("/")[0] in tocsel}
    index = load_index(os.path.join(a.analysis, "index.tsv.gz"), want)

    base = zipfile.ZipFile(a.base) if a.base else None
    tocs = {}
    if base:
        root = next(n.split("/romfs/")[0] + "/romfs/" for n in base.namelist() if "/romfs/" in n)
        cas = bytearray(base.read(root + CAS))
        for n in base.namelist():
            if n.endswith(".toc"): tocs[n[len(root):]] = base.read(n)
    elif "files/" + CAS in names: cas = bytearray(z.read("files/" + CAS))
    else: raise SystemExit(f"items.zip has no files/{CAS}")
    rd = next(p for p in (os.path.join(a.analysis, "romfs"), os.path.join(a.analysis, "tables", "romfs")) if os.path.isdir(p))
    def toc(t):
        if t not in tocs: tocs[t] = open(os.path.join(rd, t), "rb").read()
        return tocs[t]
    def put(data):
        while len(cas) % 16: cas.append(0)
        off = len(cas); cas.extend(data); return off, len(data)

    placed = {}
    for g, (data, n) in chunk_ops.items(): placed[("chunk", g)] = put(fbblocks.encode_stored(data))
    for n, data in ebx_ops.items(): placed[("ebx", n)] = put(fbblocks.encode_stored(data))
    nb = 0
    for (t, bi), brows in sorted(index.items()):
        items = fbtoc.read_block(toc(t), bi); man = None; ne = sum(r[2] == "ebx" for r in brows); hit = False
        for i, r in enumerate(brows):
            key = (r[2], r[3].lower())
            if key not in placed: continue
            if r[2] == "chunk":
                if int(r[4]) != len(chunk_ops[r[3]][0]):
                    raise SystemExit(f"{chunk_ops[r[3]][1]}: the game's chunk is {r[4]} bytes, the rebuilt one {len(chunk_ops[r[3]][0])}")
            elif int(r[4]) != len(ebx_ops[key[1]]):
                if man is None:
                    mk = f"items/manifest/{t.replace('/', '~')}~{bi}.bin"
                    if mk not in names: raise SystemExit(f"{r[3]}: changes size, and items.zip has no manifest for {t} {bi}")
                    man = z.read(mk)
                man = manifest_set_size(man, "ebx", i, len(ebx_ops[key[1]]))
            off, st = placed[key]; items[i + 1] = (CAS_ID, off, st, items[i + 1][3]); hit = True
        if man is not None:
            off, st = put(man); items[0] = (CAS_ID, off, st, items[0][3])
        if hit: tocs[t] = fbtoc.replace_block(toc(t), bi, items); nb += 1
    # the superbundles' own chunk tables
    n_tab = 0
    for dp, _, fs in os.walk(rd):
        for f in fs:
            if not f.endswith(".toc") or f == "layout.toc": continue
            t = os.path.relpath(os.path.join(dp, f), rd).replace(os.sep, "/")
            if t.split("/")[0] not in tocsel: continue
            d = tocs.get(t) or open(os.path.join(dp, f), "rb").read()
            if len(d) < fbtoc.BODY + 0x40: continue
            tab = fbtoc.chunk_table(d); hit = [g for g in chunk_ops if g in tab]
            if not hit: continue
            d = bytearray(d)
            for g in hit: fbtoc.set_chunk(d, tab[g], CAS_ID, *placed[("chunk", g)]); n_tab += 1
            tocs[t] = bytes(d)
    root = f"{a.name}/romfs/"
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as o:
        o.writestr(root + CAS, bytes(cas))
        for t, b in sorted(tocs.items()): o.writestr(root + t, b)
    rep = os.path.splitext(a.out)[0] + "-rapport.tsv"
    with open(rep, "w") as f:
        for r in report: f.write("\t".join(r) + "\n")
    print(f"{len(chunk_ops)} textures, {len(ebx_ops)} ebx in {nb} bundles; {n_tab} chunk table records; {len(cas) >> 20} MiB cas; "
          f"{len(tocs)} tocs -> {a.out} (report: {rep})")


if __name__ == "__main__":
    main()
