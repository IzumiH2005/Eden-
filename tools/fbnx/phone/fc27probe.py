#!/usr/bin/env python3
"""fc27probe: reads EA SPORTS FC 27's Frostbite data where it is, on the phone (Termux), from Peanuts Native's .nup (or a dump folder), and writes the
small parts modding work needs, so nothing of the 31.8 GB game has to leave the phone but them.

  python fc27probe.py tables <game.nup | dump folder> <out folder>
      the package list, listing.tsv (every RomFS file, its size and how the .nup stores it), Data/layout.toc, Patch/layout.toc, every superbundle .toc
  python fc27probe.py index <game.nup | dump folder> <out folder>
      index.tsv.gz: every bundle's manifest (stored uncompressed in the cas files): each ebx / res / chunk with its name or GUID, size, res type and
      where its stored bytes are (cas file, offset, stored size). Reads the cas files forward, one pass each.
  python fc27probe.py all <game.nup | dump folder> <out folder>
      tables and index (one thread per core), then modding.zip holding both: what Peanuts Nova's "Analyse for modding" runs
  python fc27probe.py extract <game.nup | dump folder> <out folder> <regex>
      the stored bytes (still Oodle-compressed blocks) of every ebx / res whose name matches regex, and of the chunks their bundles list, as found in
      index.tsv.gz (made first when out has none): items/<kind>/<name>.blocks, each matching bundle's manifest (items/manifest/), items.tsv,
      and every RomFS file whose path (Data/..., Patch/...) matches, up to 64 MiB each: files/<path>

The .nup is read with Peanuts Native's own reader (nup.py, beside this file, GPL-3.0-or-later), which needs a zstd module: Python 3.14's
compression.zstd, else `pip install backports.zstd`. Frostbite formats after Peanuts Native's dm/gfx/tools/frostbite.py.
"""
import gzip, os, re, struct, sys, zipfile

TOC_MAGIC, TOC_BODY, BUNDLE_MAGIC = bytes.fromhex("00d1ce01"), 0x22C, 0x9D798ED6


# ---- the game's RomFS: a .nup package (its highest update: a full RomFS) or a dump folder's romfs
class Source:
    def __init__(self, path):
        self.path = path
        if os.path.isdir(path):
            cands = [os.path.join(path, "romfs")] + [os.path.join(path, "updates", v, "romfs") for v in sorted(os.listdir(os.path.join(path, "updates")), key=int)] \
                if os.path.isdir(os.path.join(path, "updates")) else [os.path.join(path, "romfs"), os.path.join(path, "base", "romfs")]
            self.root = next((c for c in reversed(cands) if os.path.isdir(c)), None)
            if not self.root: sys.exit(f"{path}: no romfs folder")
            self.nup = None; self.desc = f"folder {self.root}"
        else:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import nup
            self.nup = nup.Nup(path)
            pk = self.nup.default()
            self.desc = f"{path}: {pk!r} ({', '.join(repr(p) for p in self.nup.packages)})"
            self.romfs = self.nup.find("romfs", ("pkg", pk.index))
            self.exefs = self.nup.find("exefs", ("pkg", pk.index)) if pk.exefs != 0xFFFFFFFF else None

    def files(self):
        """[(path under romfs/, size, how it is stored)]"""
        out = []
        if self.nup is None:
            for dp, _, fs in os.walk(self.root):
                for f in fs:
                    p = os.path.join(dp, f); out.append((os.path.relpath(p, self.root).replace(os.sep, "/"), os.path.getsize(p), "file"))
            return sorted(out)
        for rel, _, fs in self.nup.walk(self.romfs):
            for f in fs:
                k = self.nup.find(f"{rel}/{f}" if rel else f, self.romfs)
                size, _, stored, _, codec = self.nup.record(k)
                out.append((f"{rel}/{f}" if rel else f, size, "raw" if codec == 0 else f"zstd {stored}"))
        return sorted(out)

    def open(self, rel):
        if self.nup is None: return open(os.path.join(self.root, rel), "rb")
        return self.nup.open(self.nup.find(rel, self.romfs))

    def read(self, rel):
        with self.open(rel) as f: return f.read()

    def exists(self, rel):
        try: self.open(rel).close(); return True
        except (FileNotFoundError, OSError): return False


# ---- Frostbite
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
    raise ValueError(f"DbObject: type {t:#x} at {p - 1:#x}")

def install_chunks(src):
    (_, lay), _ = dbobject(src.read("Data/layout.toc"), TOC_BODY)
    return {c["persistentIndex"] & 0xFFFFFFFF: c["name"] for c in lay["installManifest"]["installChunks"]}

def toc_bundles(d, what="toc"):
    if d[:4] != TOC_MAGIC: raise ValueError(f"{what}: not a Frostbite toc")
    if len(d) < TOC_BODY + 0x20: return []
    B = TOC_BODY; bo, nb = struct.unpack_from(">II", d, B + 4)
    out = []
    for i in range(nb):
        _, sz, off = struct.unpack_from(">IIQ", d, B + bo + 16 * i)
        s = B + off
        fo, n, p = struct.unpack_from(">III", d, s + 8)
        p += s; fo += s; cas, ents = None, []
        for k in range(n):
            if d[fo + k] & 0x80 or cas is None: cas = bytes(d[p:p + 8]); p += 8
            ents.append((cas,) + struct.unpack_from(">II", d, p)); p += 8
        out.append(ents)
    return out

def cas_rel(cid, chunks):
    pi, n = struct.unpack_from(">IH", cid, 2)
    return f"{'Patch' if cid[1] else 'Data'}/NX/{chunks[pi]}/cas_{n:02d}.cas"

def manifest(d):
    hl = struct.unpack_from(">I", d, 0)[0]; magic, tot, ne, nr, nc, so = struct.unpack_from("<6I", d, 4)
    if magic != BUNDLE_MAGIC: raise ValueError("no bundle manifest")
    h = 4; p = h + 0x20 + 20 * tot
    ebx = [struct.unpack_from("<II", d, p + 8 * i) for i in range(ne)]; p += 8 * ne
    res = [struct.unpack_from("<II", d, p + 8 * i) for i in range(nr)]; p += 8 * nr
    types = struct.unpack_from(f"<{nr}I", d, p); p += 4 * nr + 24 * nr
    ch = [struct.unpack_from("<16sII", d, p + 24 * i) for i in range(nc)]
    def name(o):
        a = h + so + o; return bytes(d[a:d.find(b"\0", a)]).decode(errors="replace")
    return [(name(a), s) for a, s in ebx], [(name(a), s, t) for (a, s), t in zip(res, types)], ch

def tocs(src):
    return [f for f, _, _ in src.files() if f.endswith(".toc") and f.split("/")[1:2] == ["NX"]]


# ---- steps
def cmd_tables(src, out):
    os.makedirs(out, exist_ok=True)
    files = src.files()
    with open(os.path.join(out, "listing.tsv"), "w") as f:
        f.write(f"# {src.desc}\n")
        for p, s, how in files: f.write(f"{p}\t{s}\t{how}\n")
    want = ["Data/layout.toc", "Patch/layout.toc"] + tocs(src)
    with zipfile.ZipFile(os.path.join(out, "tables.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(out, "listing.tsv"), "listing.tsv")
        for rel in want:
            if src.exists(rel): z.writestr("romfs/" + rel, src.read(rel))
    print(f"{len(files)} files; {len(want)} tables -> {os.path.join(out, 'tables.zip')}")

def cmd_index(src, out):
    os.makedirs(out, exist_ok=True)
    chunks = install_chunks(src)
    jobs = {}   # cas file -> [(offset, size, toc, bundle index, entries)]
    for t in tocs(src):
        for bi, ents in enumerate(toc_bundles(src.read(t), t)):
            cid, off, size = ents[0]
            jobs.setdefault(cas_rel(cid, chunks), []).append((off, size, t, bi, ents))
    n = 0
    with gzip.open(os.path.join(out, "index.tsv.gz"), "wt") as o:
        o.write("toc\tbundle\tkind\tname\tsize\ttype\tcas\toffset\tstored\n")
        for cas in sorted(jobs):
            js = sorted(jobs[cas]); print(f"{cas}: {len(js)} manifests", flush=True)
            with src.open(cas) as f:
                for off, size, t, bi, ents in js:
                    f.seek(off); m = f.read(size)
                    try: ebx, res, ch = manifest(m)
                    except ValueError: o.write(f"{t}\t{bi}\tbad\t\t{size}\t\t{cas}\t{off}\t{size}\n"); continue
                    items = [("ebx", nm, s, "") for nm, s in ebx] + [("res", nm, s, f"{ty:08x}") for nm, s, ty in res] + [("chunk", g.hex(), ls, "") for g, lo, ls in ch]
                    for (kind, nm, s, ty), (c, eo, es) in zip(items, ents[1:]):
                        o.write(f"{t}\t{bi}\t{kind}\t{nm}\t{s}\t{ty}\t{cas_rel(c, chunks)}\t{eo}\t{es}\n")
                    n += 1
    print(f"{n} bundles -> {os.path.join(out, 'index.tsv.gz')}")

def cmd_all(src, out):
    """tables, then the index read with one thread per core (each cas file its own stream; zstd and pread run outside the GIL), then one zip of both"""
    import concurrent.futures, time
    t0 = time.time()
    cmd_tables(src, out)
    chunks = install_chunks(src)
    jobs = {}
    for t in tocs(src):
        for bi, ents in enumerate(toc_bundles(src.read(t), t)):
            cid, off, size = ents[0]
            jobs.setdefault(cas_rel(cid, chunks), []).append((off, size, t, bi, ents))
    total = sum(len(v) for v in jobs.values()); done = [0]
    print(f"progress 0 {total} index", flush=True)
    def one(cas):
        lines = []
        with src.open(cas) as f:
            for off, size, t, bi, ents in sorted(jobs[cas]):
                f.seek(off); m = f.read(size)
                try: ebx, res, ch = manifest(m)
                except ValueError: lines.append(f"{t}\t{bi}\tbad\t\t{size}\t\t{cas}\t{off}\t{size}\n"); continue
                items = [("ebx", nm, s, "") for nm, s in ebx] + [("res", nm, s, f"{ty:08x}") for nm, s, ty in res] + [("chunk", g.hex(), ls, "") for g, lo, ls in ch]
                for (kind, nm, s, ty), (c, eo, es) in zip(items, ents[1:]):
                    lines.append(f"{t}\t{bi}\t{kind}\t{nm}\t{s}\t{ty}\t{cas_rel(c, chunks)}\t{eo}\t{es}\n")
        return cas, lines, len(jobs[cas])
    workers = max(1, os.cpu_count() or 1)
    with gzip.open(os.path.join(out, "index.tsv.gz"), "wt") as o, concurrent.futures.ThreadPoolExecutor(workers) as ex:
        o.write("toc\tbundle\tkind\tname\tsize\ttype\tcas\toffset\tstored\n")
        for cas, lines, n in ex.map(one, sorted(jobs, key=lambda c: -len(jobs[c]))):
            o.writelines(lines); done[0] += n
            print(f"progress {done[0]} {total} index {cas}", flush=True)
    with zipfile.ZipFile(os.path.join(out, "modding.zip"), "w", zipfile.ZIP_STORED) as z:
        z.write(os.path.join(out, "tables.zip"), "tables.zip"); z.write(os.path.join(out, "index.tsv.gz"), "index.tsv.gz")
    print(f"done: {total} bundles, {workers} threads, {time.time() - t0:.0f} s -> {os.path.join(out, 'modding.zip')}", flush=True)


def cmd_extract(src, out, rx):
    """streams index.tsv.gz twice (it has millions of rows: never all in memory); runs `all` first when out has no index"""
    rx = re.compile(rx); idx = os.path.join(out, "index.tsv.gz")
    if not os.path.isfile(idx):
        print("no index.tsv.gz yet: reading the game's archives first", flush=True); cmd_all(src, out)
    def rows():
        with gzip.open(idx, "rt") as f:
            next(f)
            for l in f: yield l.rstrip("\n").split("\t")
    hit = set()
    for r in rows():
        if r[2] in ("ebx", "res") and rx.search(r[3]): hit.add((r[0], r[1]))
    want = [r for r in rows() if (r[0], r[1]) in hit and (r[2] == "chunk" or rx.search(r[3]))]
    print(f"{len(hit)} bundles, {len(want)} items match", flush=True)
    seen, total = set(), len(want)
    with zipfile.ZipFile(os.path.join(out, "items.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for i, r in enumerate(sorted(want, key=lambda r: (r[6], int(r[7])))):
            key = (r[2], r[3])
            if key not in seen:
                seen.add(key)
                with src.open(r[6]) as f:
                    f.seek(int(r[7])); z.writestr(f"items/{r[2]}/{r[3].replace('/', '~')}.blocks", f.read(int(r[8])))
            if i % 20 == 0: print(f"progress {i} {total} extract", flush=True)
        chunks = install_chunks(src); tocd = {}
        for t, bi in sorted(hit):
            if t not in tocd: tocd[t] = toc_bundles(src.read(t), t)
            cid, off, size = tocd[t][int(bi)][0]
            with src.open(cas_rel(cid, chunks)) as f:
                f.seek(off); z.writestr(f"items/manifest/{t.replace('/', '~')}~{bi}.bin", f.read(size))
        nf = 0
        for rel, size, _ in src.files():   # RomFS files the expression names too (by their path: Data/..., Patch/...), up to 64 MiB each
            if rx.search(rel) and (rel.startswith("Data/") or rel.startswith("Patch/")) and size <= 64 << 20:
                z.writestr(f"files/{rel}", src.read(rel)); nf += 1
        print(f"{nf} RomFS files", flush=True)
        z.writestr("items.tsv", "".join("\t".join(r) + "\n" for r in want))
        z.writestr("regex.txt", rx.pattern)
    print(f"progress {total} {total} extract", flush=True)
    print(f"{len(seen)} items, {len(hit)} manifests -> {os.path.join(out, 'items.zip')}", flush=True)


def main():
    if len(sys.argv) < 4 or sys.argv[1] not in ("tables", "index", "all", "extract") or (sys.argv[1] == "extract" and len(sys.argv) < 5):
        sys.exit(__doc__)
    src = Source(sys.argv[2]); print(src.desc, flush=True)
    {"tables": lambda: cmd_tables(src, sys.argv[3]), "index": lambda: cmd_index(src, sys.argv[3]), "all": lambda: cmd_all(src, sys.argv[3]),
     "extract": lambda: cmd_extract(src, sys.argv[3], sys.argv[4])}[sys.argv[1]]()


if __name__ == "__main__":
    main()
