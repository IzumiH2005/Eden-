"""Frostbite stored items: runs of blocks {u32 BE size (low 24 bits), u8 codec (0 stored, 0x19 Oodle Leviathan), u8 0x70 | size bits 16-19, u16 BE stored
size}. Decoding Oodle needs ooz (github.com/powzix/ooz) built as a shared library exporting
    int ooz_decompress(const uint8_t *src, size_t src_len, uint8_t *dst, size_t dst_len)
(see README.md), found at $FBNX_OOZ or libooz.so beside this file. Writing uses stored blocks (codec 0), which the game reads too."""
import ctypes, os, struct

_lib = None
BLOCK = 0x10000


def _ooz():
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL(os.environ.get("FBNX_OOZ") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "libooz.so"))
    return _lib


def oodle(comp, size):
    dst = ctypes.create_string_buffer(size + 64)
    r = _ooz().ooz_decompress(comp, len(comp), dst, size)
    if r != size: raise ValueError(f"ooz: {r} of {size}")
    return dst.raw[:size]


def decode(d, off=0, stored=None, want=None):
    """the item's bytes and the stored bytes consumed (stops after `stored` bytes, or once `want` bytes are out)"""
    o, end, out = off, (off + stored if stored is not None else len(d)), bytearray()
    while o < end and (want is None or len(out) < want):
        n = struct.unpack_from(">I", d, o)[0] & 0xFFFFFF; codec = d[o + 4]; hi = d[o + 5]
        c = (hi & 0xF) << 16 | struct.unpack_from(">H", d, o + 6)[0]
        if hi & 0xF0 != 0x70: raise ValueError(f"bad block at {o:#x}: {bytes(d[o:o + 8]).hex()}")
        blk = bytes(d[o + 8:o + 8 + c])
        if codec == 0: out += blk[:n]
        elif codec == 0x19: out += oodle(blk, n)
        else: raise ValueError(f"codec {codec:#x} at {o:#x}")
        o += 8 + c
    return bytes(out), o - off


def encode_stored(data):
    """data as stored (uncompressed) blocks of at most 64 KiB"""
    out = bytearray()
    for p in range(0, len(data), BLOCK):
        b = data[p:p + BLOCK]; n = len(b)
        out += struct.pack(">IBBH", n, 0, 0x70 | (n >> 16 & 0xF), n & 0xFFFF) + b
    return bytes(out)


if __name__ == "__main__":
    for n in (0, 1, 1000, BLOCK, BLOCK + 1, 3 * BLOCK + 5):
        x = os.urandom(n); e = encode_stored(x); y, used = decode(e)
        assert y == x and used == len(e), n
    print("fbblocks: stored round trip ok")
