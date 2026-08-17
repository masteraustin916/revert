#!/usr/bin/env python3
"""Relabel THUG2's shoulder glyphs L/R -> LT/RT inside fonts.prx.

ButtonsXbox.fnt.xbx is ORIGINAL Xbox controller art: that pad had no bumpers, so its
two analog triggers are simply lettered "L" and "R". On a 360-era pad that reads as
LB/RB, which is the wrong button. This repaints three glyphs in place:

    slot 14   L      -> LT
    slot 15   R      -> RT
    slot 18   L + R  -> LT + RT     (the wide combined glyph, e.g. "level out")

ONLY pixels change. The rect table, the per-char entries and the file size are all left
exactly as they are, so glyph placement and text metrics are untouched.

.fnt.xbx layout (derived, see tools/glyphfix/glyphfix.cpp for the renderer side):
    0x00 u32 size · 0x04 u32 version(1) · 0x08 u32 numChars · 0x0c u32 32 · 0x10 u32 24
    0x14 numChars * 6   {u16 spacing, s16 charcode (-1,-2,...), u16 0}
    then 16 bytes       {u32 ?, u16 width=256, u16 height=128, u16 bpp=8, u16, u16}
    then the atlas      256 * H, 8bpp intensity (NOT paletted; 27 = transparent)
    last numChars * 8   {u16 x, u16 y, u16 w, u16 h} per glyph, tight bounds

The atlas origin is 0x14 + numChars*6 + 16. That is worth stating because it is easy to
land 4 rows or 4 columns off and still get a picture that looks plausible; the check that
actually pins it is that every rect must tightly bound its glyph with no ink in the
surrounding ring, which verify() asserts.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prx"))
import prx  # noqa: E402
import lzss  # noqa: E402

BG = 27          # transparent
INK = 240        # letter core
SHADOW = 45      # 1px bottom-right emboss, so the letter reads against the button body

# 9-row letterforms, 2px strokes. Small and bold beats small and faithful: the stock
# letters are downscaled mush that only reads as "L" once you know it says L.
GLYPHS = {
    "L": ["##...",
          "##...",
          "##...",
          "##...",
          "##...",
          "##...",
          "##...",
          "#####",
          "#####"],
    "R": ["#####.",
          "##..##",
          "##..##",
          "##..##",
          "#####.",
          "#####.",
          "##.##.",
          "##..##",
          "##..##"],
    "T": ["######",
          "######",
          "..##..",
          "..##..",
          "..##..",
          "..##..",
          "..##..",
          "..##..",
          "..##.."],
}


def parse(font):
    nch = struct.unpack_from("<I", font, 8)[0]
    img = 0x14 + nch * 6 + 16
    rect = len(font) - nch * 8
    h = (rect - img) // 256
    rects = [struct.unpack_from("<HHHH", font, rect + i * 8) for i in range(nch)]
    return nch, img, h, rects


def verify(font, tag):
    """Every rect must tightly bound its glyph, with a clean ring around it."""
    nch, img, h, rects = parse(font)
    px = lambda x, y: font[img + y * 256 + x] if 0 <= y < h and 0 <= x < 256 else BG
    for i, (x, y, w, hh) in enumerate(rects):
        edges = (any(px(x + k, y) != BG for k in range(w))
                 + any(px(x + k, y + hh - 1) != BG for k in range(w))
                 + any(px(x, y + j) != BG for j in range(hh))
                 + any(px(x + w - 1, y + j) != BG for j in range(hh)))
        if edges != 4:
            raise SystemExit("%s: slot %d does not fill its rect (%d/4 edges)" % (tag, i, edges))
        ring = ([px(x - 1, y + j) for j in range(hh)] + [px(x + w, y + j) for j in range(hh)]
                + [px(x + k, y - 1) for k in range(w)] + [px(x + k, y + hh) for k in range(w)])
        if any(v != BG for v in ring):
            raise SystemExit("%s: slot %d bleeds into its neighbour" % (tag, i))


INSET = 3       # how far inside the button outline the flat body starts


def scrub(buf, img, gx, gy, gw, gh, inset_l=INSET, inset_r=INSET):
    """Blank a button's interior back to flat body, following its rounded outline.

    A fixed rectangle is not enough: the stock "L" has an outlying foot pixel a couple of
    columns to the right of the stroke, and anything left behind reads as punctuation next
    to the new label. So for each row find the button's own left/right edge, inset past the
    bevel, and flood what remains with that row's body colour. Returns the per-row colour.

    The insets are per side because in the combined glyph the two buttons run straight into
    the plus sign instead of ending in a bevel: insetting an edge that isn't there would
    leave a strip of the old letter behind on exactly the side we need cleared.
    """
    fill = {}
    for j in range(gh):
        row = [buf[img + (gy + j) * 256 + gx + k] for k in range(gw)]
        ink = [k for k, v in enumerate(row) if v != BG]
        if not ink:
            fill[j] = None
            continue
        lo, hi = ink[0] + inset_l, ink[-1] - inset_r
        mids = {}
        for k in range(lo, hi + 1):
            if 90 <= row[k] <= 175:                # body mid-tones, not the letter or bevel
                mids[row[k]] = mids.get(row[k], 0) + 1
        fill[j] = max(mids, key=mids.get) if mids else None
    # Second pass: a row whose interior was mostly letter falls back to its neighbours.
    for j in range(gh):
        if fill[j] is None:
            near = [fill[k] for k in (j - 1, j + 1, j - 2, j + 2) if fill.get(k)]
            fill[j] = near[0] if near else 110
    for j in range(gh):
        row = [buf[img + (gy + j) * 256 + gx + k] for k in range(gw)]
        ink = [k for k, v in enumerate(row) if v != BG]
        if not ink:
            continue
        for k in range(ink[0] + inset_l, ink[-1] - inset_r + 1):
            buf[img + (gy + j) * 256 + gx + k] = fill[j]
    return fill


def draw_text(buf, img, gx, gy, gw, gh, text, cx, cy, inset_l=INSET, inset_r=INSET):
    """Scrub the button and stamp `text` at (cx, cy) with a bottom-right emboss."""
    scrub(buf, img, gx, gy, gw, gh, inset_l, inset_r)
    art = [GLYPHS[ch] for ch in text]

    def put(px, py, val):
        if 0 <= px < gw and 0 <= py < gh:
            buf[img + (gy + py) * 256 + gx + px] = val

    # Shadow for every ink cell, then ink on top: the interior shadow is overwritten and
    # only the bottom-right edge survives, which is the emboss we want.
    for val, dx, dy in ((SHADOW, 1, 1), (INK, 0, 0)):
        x0 = cx
        for a in art:
            for j, row in enumerate(a):
                for k, c in enumerate(row):
                    if c == "#":
                        put(x0 + k + dx, cy + j + dy, val)
            x0 += len(a[0]) + 1


def centred(gw, tw):
    return (gw - tw) // 2


def retag(font):
    buf = bytearray(font)
    nch, img, h, rects = parse(font)

    # slot 14 "L" and slot 15 "R": one button each, centre the pair of letters in it.
    for slot, text in ((14, "LT"), (15, "RT")):
        x, y, w, hh = rects[slot]
        tw = sum(len(GLYPHS[c][0]) for c in text) + len(text) - 1
        draw_text(buf, img, x, y, w, hh, text, centred(w, tw), (hh - 9) // 2)

    # slot 18: left button | plus | right button. The two buttons are the same art as
    # slots 14/15, so split the rect in half either side of the plus and centre in each.
    x, y, w, hh = rects[18]
    half = 21                                  # each button is 21px wide in the 58px glyph
    # Each half butts onto the plus, so do not inset the side that faces it.
    for text, x0, il, ir in (("LT", 0, INSET, 0), ("RT", w - half, 0, INSET)):
        tw = sum(len(GLYPHS[c][0]) for c in text) + len(text) - 1
        draw_text(buf, img, x + x0, y, half, hh, text,
                  centred(half, tw), (hh - 9) // 2, il, ir)
    return bytes(buf)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "Data/pre/fonts.prx"
    dst = sys.argv[2] if len(sys.argv) > 2 else src
    ver, entries = prx.parse(open(src, "rb").read())

    hit = 0
    for e in entries:
        if b"ButtonsXbox" not in e["name"]:
            continue
        blob = e["blob"][:e["csize"] or e["dsize"]]
        font = lzss.decompress(blob, e["dsize"]) if e["csize"] else blob
        verify(font, "stock")
        out = retag(font)
        if len(out) != len(font):
            raise SystemExit("font size changed (%d -> %d)" % (len(font), len(out)))
        verify(out, "retagged")
        # Store raw: the loader accepts csize==0 and we have no LZSS compressor.
        e["csize"] = 0
        e["dsize"] = len(out)
        e["blob"] = out + b"\0" * (prx.align4(len(out)) - len(out))
        hit += 1

    if hit != 1:
        raise SystemExit("expected exactly one ButtonsXbox entry, found %d" % hit)
    open(dst, "wb").write(prx.build(ver, entries))
    print("LT/RT glyphs written to %s" % dst)


if __name__ == "__main__":
    main()
