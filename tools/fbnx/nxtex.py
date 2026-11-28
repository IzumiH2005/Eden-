"""Tegra X1 (Switch) block-linear textures, for block-compressed formats (BC1-BC7: a "texel" is a 4x4 block of 8 or 16 bytes).

A surface is cut in GOBs of 64 bytes x 8 rows (512 bytes); a block is block_height GOBs stacked vertically; blocks run left to right, then down.
Each mip level has its own block height: the surface's, halved while the level is no taller than half of it (as the Switch's own driver does).
Checked on FC 27's player face textures: 512x512 BC1 with 10 mips is 177152 bytes, 512x512 with 16-byte blocks 351744, 256x256 89600.
"""

GOB_W, GOB_H, GOB = 64, 8, 512


def _ceil(a, b): return (a + b - 1) // b


def block_height(rows):
    """the block height (in GOBs) for a level of rows block rows: the smallest power of two covering it, at most 16"""
    bh = 16
    while bh > 1 and rows <= (bh // 2) * GOB_H: bh //= 2
    return bh


def level_dims(w, h, level):
    return max(1, w >> level), max(1, h >> level)


def level_size(w, h, bpb, bh_base=None):
    """bytes of one block-linear level (w, h in texels)"""
    bw, rows = _ceil(w, 4), _ceil(h, 4)
    bh = block_height(rows) if bh_base is None else bh_base
    return _ceil(bw * bpb, GOB_W) * _ceil(rows, GOB_H * bh) * GOB * bh


def chain_size(w, h, bpb, mips):
    return sum(level_size(*level_dims(w, h, m), bpb) for m in range(mips))


def _addr(xb, y, gobs_x, bh):
    """byte offset of byte column xb, block row y"""
    blk = (y // (GOB_H * bh)) * gobs_x + xb // GOB_W
    gob_in_blk = (y % (GOB_H * bh)) // GOB_H
    x, yy = xb % GOB_W, y % GOB_H
    return (blk * bh + gob_in_blk) * GOB + (x // 32) * 256 + (yy // 2) * 64 + ((x % 32) // 16) * 32 + (yy % 2) * 16 + (x % 16)


def swizzle(linear, w, h, bpb):
    """one level, linear rows of blocks -> block-linear bytes"""
    bw, rows = _ceil(w, 4), _ceil(h, 4); bh = block_height(rows); pitch = bw * bpb
    gobs_x = _ceil(pitch, GOB_W)
    out = bytearray(level_size(w, h, bpb))
    for y in range(rows):
        for xb in range(0, pitch, 16):   # 16-byte runs stay together inside a GOB
            a = _addr(xb, y, gobs_x, bh); s = y * pitch + xb; n = min(16, pitch - xb)
            out[a:a + n] = linear[s:s + n]
    return bytes(out)


def unswizzle(data, w, h, bpb):
    bw, rows = _ceil(w, 4), _ceil(h, 4); bh = block_height(rows); pitch = bw * bpb
    gobs_x = _ceil(pitch, GOB_W)
    out = bytearray(pitch * rows)
    for y in range(rows):
        for xb in range(0, pitch, 16):
            a = _addr(xb, y, gobs_x, bh); n = min(16, pitch - xb)
            out[y * pitch + xb:y * pitch + xb + n] = data[a:a + n]
    return bytes(out)


def linear_levels(data, w, h, bpb, mips):
    """a PC (linear) mip chain -> [level bytes]"""
    out, p = [], 0
    for m in range(mips):
        lw, lh = level_dims(w, h, m); n = _ceil(lw, 4) * _ceil(lh, 4) * bpb
        out.append(data[p:p + n]); p += n
    return out


def nx_chain(levels, w, h, bpb):
    """[linear level bytes] from w x h down -> one block-linear chain"""
    return b"".join(swizzle(lv, *level_dims(w, h, m), bpb) for m, lv in enumerate(levels))


def nx_levels(data, w, h, bpb, mips):
    out, p = [], 0
    for m in range(mips):
        lw, lh = level_dims(w, h, m); n = level_size(lw, lh, bpb)
        out.append(unswizzle(data[p:p + n], lw, lh, bpb)); p += n
    return out


if __name__ == "__main__":
    import os
    assert chain_size(512, 512, 8, 10) == 177152 and chain_size(512, 512, 16, 10) == 351744 and chain_size(256, 256, 16, 9) == 89600, \
        (chain_size(512, 512, 8, 10), chain_size(512, 512, 16, 10), chain_size(256, 256, 16, 9))
    for w, bpb, mips in ((512, 8, 10), (512, 16, 10), (256, 16, 9)):
        levels = [os.urandom(_ceil(max(1, w >> m), 4) ** 2 * bpb) for m in range(mips)]
        chain = nx_chain(levels, w, w, bpb)
        assert nx_levels(chain, w, w, bpb, mips) == levels
    print("nxtex: sizes and round trip ok")
