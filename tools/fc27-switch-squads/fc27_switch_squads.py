#!/usr/bin/env python3
"""EA SPORTS FC 27 squad updates for the Nintendo Switch (and so for Eden).

EA publishes each roster update once per platform family. Its index (rosterupdate.xml) shows two database schemas:
  b41ea024...  pc64, ps5, xbsx, nx2 (Switch 2)     82 tables
  6540b642...  nx (Switch), ps4, xone               81 tables (no xscJ; Vmkr, OIcD, xuka, PViY, DbIl differ)
so a PC squad file (such as the ones xAranaktu/FIFASquadFileDownloader writes) is not the Switch game's database. This tool takes the
Switch's own database from EA's servers (platform "nx"), checks it, and wraps it in the squad file container byte for byte as that
downloader does for PC (FBCHUNKS prefix of 1126 bytes, SaveType_Squads header, the database, the BNRY chunk).

  fetch [--platform nx] [--out DIR]          download the newest roster of that platform: DIR/Squads<date>000000, DIR/switch/INDEX and DATA
  build <roster .bin> <name> [--out DIR]     the same from a roster file already downloaded (name: Squads<YYYYMMDD>000000)
  inspect <file or Eden save zip>            what a squad file or a save export holds (layout, database, tables)
  patch-save <Eden save zip> <squad file> <out zip>
                                             replace the squad slot of a save exported by Eden (Properties > Save data > Export) with the
                                             squad file, keeping everything else; the result imports with Save data > Import

The Switch save keeps each saved item in a folder of its own with two files, INDEX and DATA (community reports). The squad file's
1126-byte prefix (FBCHUNKS, item name, size of the rest) matches what an INDEX would carry and its rest starts with SaveType_Squads, the
string players find at the start of the 10 MB DATA. patch-save checks the export's actual layout before it writes and stops on any other.
"""
import argparse, io, os, struct, sys, urllib.request, xml.etree.ElementTree as ET, zipfile

CONTENT_URL = "https://eafc27.content.easports.com/fc/fltOnlineAssets/27A3C9F1-6B2E-4D7A-8C1F-2E9B5A4D6C7E/2027/"
ROSTER_XML = CONTENT_URL + "fc/fclive/genxtitle/rosterupdate.xml"
FBCHUNKS = b"FBCHUNKS\x01\x00"
SAVETYPE = b"SaveType_Squads\x00"
BNRY = b"\x42\x4E\x52\x59\x00\x00\x00\x02\x4C\x54\x4C\x45\x01\x01\x03\x00\x00\x00\x63\x64\x73\x01\x00\x00\x00\x00\x01\x03\x00\x00\x00\x63\x64\x73"
PREFIX, MAIN, BNRY_SIZE = 1126, 48, 45985


# ---- EA RefPack (QFS): the roster .bin is the database compressed with it
def refpack_unpack(data: bytes) -> bytes:
    if data[:2] != b"\x10\xfb": raise ValueError("not a RefPack stream")
    size = int.from_bytes(data[2:5], "big")
    out = bytearray(size); ipos, opos, last = 5, 0, 0
    while ipos < len(data) and opos < size:
        c = data[ipos]; last = c; ipos += 1
        if not c & 0x80:
            b1 = data[ipos]; ipos += 1; lit = c & 3
            out[opos:opos + lit] = data[ipos:ipos + lit]; ipos += lit; opos += lit
            n = ((c >> 2) & 7) + 3; src = opos - (b1 + ((c & 0x60) << 3) + 1)
        elif not c & 0x40:
            b2, b3 = data[ipos], data[ipos + 1]; ipos += 2; lit = b2 >> 6
            out[opos:opos + lit] = data[ipos:ipos + lit]; ipos += lit; opos += lit
            n = (c & 0x3F) + 4; src = opos - (((b2 & 0x3F) << 8 | b3) + 1)
        elif not c & 0x20:
            b2, b3, b4 = data[ipos], data[ipos + 1], data[ipos + 2]; ipos += 3; lit = c & 3
            out[opos:opos + lit] = data[ipos:ipos + lit]; ipos += lit; opos += lit
            n = b4 + ((c & 0x0C) << 6) + 5; src = opos - ((((c & 0x10) << 12) | (b2 << 8) | b3) + 1)
        else:
            lit = (c & 0x1F) * 4 + 4
            if lit > 0x70: break
            out[opos:opos + lit] = data[ipos:ipos + lit]; ipos += lit; opos += lit
            continue
        for _ in range(n):
            out[opos] = out[src]; opos += 1; src += 1
    t = last & 3
    if t and opos < size:
        e = min(opos + t, size); out[opos:e] = data[ipos:ipos + (e - opos)]; opos = e
    if opos != size: raise ValueError(f"RefPack: {opos} of {size} bytes")
    return bytes(out)


# ---- the T3DB database: its header and table directory carry CRC-32/MPEG-2 checksums
_T = []
for _i in range(256):
    _c = _i << 24
    for _ in range(8): _c = ((_c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if _c & 0x80000000 else (_c << 1) & 0xFFFFFFFF
    _T.append(_c)

def crc_mpeg2(b: bytes) -> int:
    c = 0xFFFFFFFF
    for x in b: c = ((c << 8) & 0xFFFFFFFF) ^ _T[((c >> 24) ^ x) & 0xFF]
    return c

def db_info(db: bytes) -> dict:
    """the database's size, tables and whether its header and directory checksums hold; raises when it is not a T3DB"""
    if db[:4] != b"DB\x00\x08": raise ValueError("not a T3DB database")
    size, n, hcrc = struct.unpack_from("<I", db, 8)[0], struct.unpack_from("<I", db, 16)[0], struct.unpack_from("<I", db, 20)[0]
    tables = [db[24 + 8 * i:28 + 8 * i].decode("latin1") for i in range(n)]
    dcrc = struct.unpack_from("<I", db, 24 + 8 * n)[0]
    return {"size": size, "length_ok": size == len(db), "tables": tables, "header_crc_ok": crc_mpeg2(db[:20]) == hcrc,
            "dir_crc_ok": crc_mpeg2(db[24:24 + 8 * n]) == dcrc, "xscJ": "xscJ" in tables}

def schema_of(info: dict) -> str:
    return "PC / PS5 / Xbox Series / Switch 2 (82 tables)" if info["xscJ"] else "Switch / PS4 / Xbox One (81 tables)"


# ---- the squad file container (xAranaktu/FIFASquadFileDownloader save_squads, byte for byte)
def build_squad_file(db: bytes, name: str, author: bytes = b"Aranaktu") -> bytes:
    if db[:4] != b"DB\x00\x08": raise ValueError("not a T3DB database")
    data_size = len(db) + BNRY_SIZE
    p = bytearray(PREFIX)
    p[0:10] = FBCHUNKS
    p[10:14] = (PREFIX - 18).to_bytes(4, "little")
    p[14:18] = (MAIN + 4 + data_size).to_bytes(4, "little")
    nm = ("EA_" + name).encode()[:40]
    p[18:18 + len(nm)] = nm
    p[18 + len(nm) + 7:18 + len(nm) + 7 + len(author)] = author
    m = bytearray(MAIN); m[:len(SAVETYPE)] = SAVETYPE
    return bytes(p) + bytes(m) + data_size.to_bytes(4, "little") + db + BNRY + b"\x00" * (BNRY_SIZE - len(BNRY))

def parse_squad_file(f: bytes):
    """(prefix, rest, database) of a squad file; raises on another layout"""
    if f[:10] != FBCHUNKS: raise ValueError("no FBCHUNKS prefix")
    if int.from_bytes(f[14:18], "little") != len(f) - PREFIX: raise ValueError("the prefix's size is not the file's")
    rest = f[PREFIX:]
    if not rest.startswith(SAVETYPE): raise ValueError("no SaveType_Squads after the prefix")
    d0 = MAIN + 4
    db = rest[d0:d0 + struct.unpack_from("<I", rest, d0 + 8)[0]]
    return f[:PREFIX], rest, db


# ---- EA's roster index
def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r: return r.read()

def roster_entry(platform: str) -> dict:
    root = ET.fromstring(fetch(ROSTER_XML))
    for s in root[0]:
        if s.attrib.get("platform") == platform:
            return {c.tag: c.text for c in s}
    raise SystemExit(f"no platform {platform} in rosterupdate.xml")

def write_outputs(db: bytes, name: str, out: str) -> None:
    info = db_info(db)
    if not (info["length_ok"] and info["header_crc_ok"] and info["dir_crc_ok"]): raise SystemExit(f"the database fails its own checks: {info}")
    f = build_squad_file(db, name)
    os.makedirs(os.path.join(out, "switch"), exist_ok=True)
    open(os.path.join(out, name), "wb").write(f)
    open(os.path.join(out, "switch", "INDEX"), "wb").write(f[:PREFIX])
    open(os.path.join(out, "switch", "DATA"), "wb").write(f[PREFIX:])
    print(f"{name}: {len(f)} bytes, database {len(db)} bytes, {len(info['tables'])} tables ({schema_of(info)}), checksums ok")
    print(f"  {os.path.join(out, name)}\n  {os.path.join(out, 'switch', 'INDEX')} ({PREFIX} bytes) + DATA ({len(f) - PREFIX} bytes)")


# ---- the Switch save's own item format (read from a real FC 27 save: Peanuts Native backup, 2026-11-28)
# The save holds main/<fnv1(name) as 8 hex digits>/ per item, with three files:
#   name    the item's name, no NUL (e.g. Squads20261123000000, UCLTrnmnt20261028060848, Settings20261028031231)
#   INDEX   3 entries of 0x50 bytes: {char name[32], u64 1, u64 size, u64 offset, u64 end, 16 zero bytes}: body, displayname, header
#   DATA    the three sections back to back, displayname, header, body; each {u64 length after these 16 bytes, u64 time (Unix ns), bytes}
#           displayname: the label the game lists, NUL-terminated; header: 0x404 bytes after the 16; body: the 48-byte main header
#           {"SaveType_<kind>\0", u32 zlib CRC-32 of the body from its byte 64 to the end, u32 0x31c, u32 1, zeros}, then the item's data
#           (squads: u32 data size, the T3DB database, the BNRY chunk, as in the PC file)
def fnv1_32(b: bytes) -> int:
    h = 0x811C9DC5
    for x in b: h = ((h * 0x01000193) & 0xFFFFFFFF) ^ x
    return h

def switch_item(squad_file: bytes, name: str, label: str, now_ns: int):
    """{relative path: bytes} of the save item main/<hash>/{name,INDEX,DATA} holding the squad file's database"""
    import zlib
    _, rest, _ = parse_squad_file(squad_file)
    data = rest[MAIN:]                                   # u32 data size, database, BNRY: as the PC file has them after its main header
    main = bytearray(MAIN); main[:len(SAVETYPE)] = SAVETYPE
    struct.pack_into("<III", main, 16, zlib.crc32(data) & 0xFFFFFFFF, 0x31C, 1)
    def section(content: bytes) -> bytes: return struct.pack("<QQ", len(content), now_ns) + content
    disp = section(label.encode() + b"\0"); head = section(bytes(0x404)); body = section(bytes(main) + data)
    blob = disp + head + body
    def entry(nm: bytes, size: int, off: int) -> bytes: return nm.ljust(32, b"\0") + struct.pack("<QQQQ", 1, size, off, off + size) + bytes(16)
    index = entry(b"body", len(body), len(disp) + len(head)) + entry(b"displayname", len(disp), 0) + entry(b"header", len(head), len(disp))
    folder = f"main/{fnv1_32(name.encode()):08x}/"
    return {folder + "name": name.encode(), folder + "INDEX": index, folder + "DATA": blob}

def check_item(files: dict, folder: str) -> str:
    """the same reading the game's items pass: INDEX against DATA, the body's CRC, the folder's hash"""
    import zlib
    idx, data, name = files[folder + "INDEX"], files[folder + "DATA"], files[folder + "name"]
    secs = {}
    for i in range(3):
        nm = idx[0x50 * i:0x50 * i + 32].rstrip(b"\0").decode(); one, size, off, end = struct.unpack_from("<QQQQ", idx, 0x50 * i + 32)
        if one != 1 or off + size != end or end > len(data): raise ValueError(f"{folder}: bad INDEX entry {nm}")
        if struct.unpack_from("<Q", data, off)[0] != size - 16: raise ValueError(f"{folder}: section {nm} length")
        secs[nm] = data[off + 16:end]
    body = secs["body"]
    if struct.unpack_from("<I", body, 16)[0] != zlib.crc32(body[MAIN:]) & 0xFFFFFFFF: raise ValueError(f"{folder}: body CRC")
    if folder.rstrip("/").rsplit("/", 1)[-1] != f"{fnv1_32(name):08x}": raise ValueError(f"{folder}: folder is not fnv1(name)")
    return f"{name.decode()}: {body[:16].rstrip(bytes(1)).decode()} '{secs['displayname'].rstrip(bytes(1)).decode()}', body {len(body)} bytes, ok"


# ---- Eden save exports
def describe(name: str, b: bytes) -> str:
    head = b[:16]
    kind = ("squad file (FBCHUNKS + SaveType_Squads)" if b.startswith(FBCHUNKS) and SAVETYPE in b[PREFIX:PREFIX + 16]
            else "FBCHUNKS prefix" if b.startswith(FBCHUNKS)
            else "SaveType_Squads data" if b.startswith(SAVETYPE)
            else "contains SaveType_Squads at %d" % b.find(SAVETYPE) if SAVETYPE in b[:4096] else "other")
    return f"{name}: {len(b)} bytes, {kind}, head {head.hex()}"

def squad_slots(z: zipfile.ZipFile):
    """[(folder, DATA name, INDEX name or None)] of the folders whose DATA holds squads"""
    names = set(z.namelist()); out = []
    for n in sorted(names):
        if n.rsplit("/", 1)[-1] != "DATA": continue
        with z.open(n) as f: head = f.read(PREFIX + 64)
        if SAVETYPE in head:
            folder = n[:-len("DATA")]
            out.append((folder, n, folder + "INDEX" if folder + "INDEX" in names else None))
    return out

def cmd_inspect(path: str) -> None:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                if i.is_dir(): continue
                with z.open(i) as f: print(describe(i.filename, f.read(PREFIX + 64) if i.file_size > 1 << 20 else f.read()))
            print("squad slots:", squad_slots(z) or "none (make one in the game: Customise > Profile > Save Squads, then export again)")
        return
    b = open(path, "rb").read(); print(describe(path, b))
    try:
        _, _, db = parse_squad_file(b); info = db_info(db)
        print(f"  database {info['size']} bytes, {len(info['tables'])} tables: {schema_of(info)}; checksums {'ok' if info['header_crc_ok'] and info['dir_crc_ok'] else 'BAD'}")
    except ValueError as e: print("  not a whole squad file:", e)

def cmd_patch(src: str, squad: str, dst: str) -> None:
    f = open(squad, "rb").read(); prefix, rest, db = parse_squad_file(f)
    info = db_info(db)
    if info["xscJ"]: raise SystemExit("this squad file holds the PC / PS5 / Xbox Series / Switch 2 database: the Switch game needs the Switch one (fetch --platform nx)")
    with zipfile.ZipFile(src) as z:
        slots = squad_slots(z)
        if not slots: raise SystemExit("no squad slot in this save: in the game, Customise > Profile > Save Squads, then export the save again")
        folder, data_name, index_name = slots[-1]
        old_data = z.read(data_name); old_index = z.read(index_name) if index_name else None
        print(describe(data_name, old_data[:PREFIX + 64])); print(describe(index_name, old_index) if old_index is not None else "no INDEX beside it")
        if old_data.startswith(SAVETYPE) and old_index is not None and old_index.startswith(FBCHUNKS):
            new = {data_name: rest, index_name: prefix}          # the split layout: INDEX = the prefix, DATA = the rest
        elif old_data.startswith(FBCHUNKS):
            new = {data_name: f}                                 # the whole squad file in DATA
        else:
            raise SystemExit("unknown slot layout: nothing written. Send the export (or this output) so the layout can be added")
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as o:
            for i in z.infolist():
                o.writestr(i, new.get(i.filename, z.read(i.filename)) if not i.is_dir() else b"")
    print(f"{dst}: slot {folder} replaced ({', '.join(new)}); {len(slots)} squad slot(s) in the save")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("fetch"); a.add_argument("--platform", default="nx"); a.add_argument("--out", default="out")
    a = sp.add_parser("build"); a.add_argument("bin"); a.add_argument("name"); a.add_argument("--out", default="out")
    a = sp.add_parser("inspect"); a.add_argument("path")
    a = sp.add_parser("patch-save"); a.add_argument("save_zip"); a.add_argument("squad_file"); a.add_argument("out_zip")
    args = ap.parse_args()
    if args.cmd == "fetch":
        e = roster_entry(args.platform); loc = e["dbMajorLoc"]
        print(f"platform {args.platform}: dbMajor {e['dbMajor']}, schema {e['dbSchemaCRC'][:12]}, {loc}")
        db = refpack_unpack(fetch(CONTENT_URL + loc))
        write_outputs(db, "Squads{}000000".format(os.path.basename(loc).split("_")[1]), args.out)
    elif args.cmd == "build":
        write_outputs(refpack_unpack(open(args.bin, "rb").read()), args.name, args.out)
    elif args.cmd == "inspect":
        cmd_inspect(args.path)
    else:
        cmd_patch(args.save_zip, args.squad_file, args.out_zip)


if __name__ == "__main__":
    main()
