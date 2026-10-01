#!/usr/bin/env python3
"""Procedural tiles and sprites for LUNA LANDEER -> gfx.h

The tile ids emitted here are a three-way contract (mkgfx.py, gfx.h,
tools/probe.py).  All of them stay < 128 because LCDC.4 = 0 puts BG tile data in
the 0x9000 page: an id of 128 or more reads 0x8800.. instead, which is where the
sprite tiles live.

Every tile is drawn as ASCII - '.' = colour 0, '1' = light, '2' = dark,
'#' = black - so there are no dependencies and `python3 mkgfx.py` runs anywhere.
gfx.h is committed, so a plain `make` needs no Python at all.

The ship's ROT_STEPS headings are the one thing not typed in by hand: they are
rasterised from a polygon at each 22.5 degree step, so the sprite turns smoothly
instead of being four quarter-turns of one drawing.  tools/mktab.py owns the
matching thrust vectors, and frame i has to point where vector i points.
"""
import math

TILES = []          # TILES[i] is 16 bytes; the index IS the BG tile id
NAMES = []          # (define name, tile id), for the generated #defines
DRAWN = set()       # ids put() was actually asked for

# The id gap between the terrain tiles and the font.  Named because the
# self-check below asserts the gap is exactly these ids and nothing else: a
# typo'd id would otherwise grow the array and shift the numbering in silence.
GAP = list(range(3, 20))

BLANK = ["........"] * 8


def enc(rows):
    """8 rows of 8 chars -> 16 bytes of 2bpp tile data."""
    assert len(rows) == 8, rows
    out = []
    for r in rows:
        assert len(r) == 8, r
        lo = hi = 0
        for ch in r:
            c = {'.': 0, '1': 1, '2': 2, '#': 3}[ch]
            lo = (lo << 1) | (c & 1)
            hi = (hi << 1) | (c >> 1)
        out += [lo, hi]
    return out


def put(index, rows, name=None):
    """Draw one tile.  Gaps on the way are filled with blanks - which is exactly
    why the self-check at the bottom does not trust `len(TILES)`: a typo'd id
    would otherwise grow the array, and the numbering would shift, in silence."""
    while len(TILES) <= index:
        TILES.append(enc(BLANK))
    TILES[index] = enc(rows)
    DRAWN.add(index)
    if name:
        NAMES.append((name, index))


# ------------------------------------------------------------ terrain tiles
# Ground heights are 8px TILE units (mkgfx draws the tiles, tools/mklevel.py owns
# the heights).  Tile 0 is the paper everything is blitted onto and doubles as
# the sky, so nothing has to be cleared to get rid of a drawn row.
put(0, BLANK, "T_BLANK")

# The ground body: solid black with a scatter of dark flecks.  Not a flat fill on
# purpose - a flat fill and an unloaded tile bank look the same on screen, and
# the flecks are what make "the tile data really got there" visible.
put(1, ["########",
        "###2####",
        "######2#",
        "#2######",
        "########",
        "#####2##",
        "2#######",
        "########"], "T_TERRAIN")

# The surface crust, for whatever blits a surface row: a lit band on top of the
# same body.
put(2, ["11111111",
        "1#1##1#1",
        "########",
        "###2####",
        "######2#",
        "#2######",
        "########",
        "2#######"], "T_TERRAIN_TOP")

# ------------------------------------------------------------------- font
# 5x7 glyphs, inset one column from the left and two from the right, so a row
# of them is legible on a blank background and "A" of a string is one tile.
FONT = {
 '0': ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.",
 '1': "..#..|.##..|..#..|..#..|..#..|..#..|.###.",
 '2': ".###.|#...#|....#|...#.|..#..|.#...|#####",
 '3': ".###.|#...#|....#|..##.|....#|#...#|.###.",
 '4': "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.",
 '5': "#####|#....|####.|....#|....#|#...#|.###.",
 '6': ".###.|#....|#....|####.|#...#|#...#|.###.",
 '7': "#####|....#|...#.|..#..|.#...|.#...|.#...",
 '8': ".###.|#...#|#...#|.###.|#...#|#...#|.###.",
 '9': ".###.|#...#|#...#|.####|....#|...#.|.##..",
 'A': ".###.|#...#|#...#|#####|#...#|#...#|#...#",
 'B': "####.|#...#|#...#|####.|#...#|#...#|####.",
 'C': ".###.|#...#|#....|#....|#....|#...#|.###.",
 'D': "####.|#...#|#...#|#...#|#...#|#...#|####.",
 'E': "#####|#....|#....|####.|#....|#....|#####",
 'F': "#####|#....|#....|####.|#....|#....|#....",
 'G': ".###.|#...#|#....|#.###|#...#|#...#|.###.",
 'H': "#...#|#...#|#...#|#####|#...#|#...#|#...#",
 'I': ".###.|..#..|..#..|..#..|..#..|..#..|.###.",
 'J': "..###|...#.|...#.|...#.|...#.|#..#.|.##..",
 'K': "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
 'L': "#....|#....|#....|#....|#....|#....|#####",
 'M': "#...#|##.##|#.#.#|#.#.#|#...#|#...#|#...#",
 'N': "#...#|##..#|#.#.#|#..##|#...#|#...#|#...#",
 'O': ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
 'P': "####.|#...#|#...#|####.|#....|#....|#....",
 'Q': ".###.|#...#|#...#|#...#|#.#.#|#..#.|.##.#",
 'R': "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
 'S': ".####|#....|#....|.###.|....#|....#|####.",
 'T': "#####|..#..|..#..|..#..|..#..|..#..|..#..",
 'U': "#...#|#...#|#...#|#...#|#...#|#...#|.###.",
 'V': "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
 'W': "#...#|#...#|#...#|#.#.#|#.#.#|##.##|#...#",
 'X': "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
 'Y': "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..",
 'Z': "#####|....#|...#.|..#..|.#...|#....|#####",
}

# 19 is a deliberate blank: it puts the digits on 20 and the letters on 30,
# which is the numbering tools/probe.py and the HUD both spell out.
put(19, BLANK)
for i, ch in enumerate("0123456789"):
    put(20 + i, ["." + r + ".." for r in FONT[ch].split("|")] + ["........"])
for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    put(30 + i, ["." + r + ".." for r in FONT[ch].split("|")] + ["........"])
NAMES.append(("T_DIGIT0", 20))
NAMES.append(("T_LETTER0", 30))

# ------------------------------------------------------------- sprite data
# OBJ tiles are a VRAM bank of their own, so sprite tile 0 has nothing to do
# with BG tile 0 and this is a separate array.  Colour 0 is transparent on a
# sprite, so '.' here is a hole rather than a colour.  SPRITES_8x8: one tile per
# OAM slot, and OAM coordinates are not screen ones (the DMG draws an 8x8 sprite
# 8 px left of and 16 px above the position written), so the placing lives in
# main.c and adds both offsets.
#
# ROT_STEPS PRE-RENDERED HEADINGS, and this is the whole reason P4 needs no
# runtime trigonometry: the ship's heading picks one of these tiles and the
# matching pair out of tables.h's thrust_dx/dy, and neither the renderer nor the
# physics ever calls sin().  Hand-rotating an 8x8 ASCII drawing would alias into
# mush at the odd angles, so the ship is a POLYGON rasterised at the eight pixel
# centres once per step - the same shape at every heading, which is also what
# makes the self-check below able to measure which way each frame points.
ROT_STEPS = 16              # 22.5 deg per step; tables.h defines the same

# The triangle, in px from the tile centre: nose at SHIP_APEX along the heading,
# back edge at SHIP_BASE behind it, that edge SHIP_BASE_HW wide to each side.
# APEX is tuned rather than chosen -- a pointed nose has no pixel within half a
# pixel of the tile's centre line, so the tip is drawn one pixel short and the
# ship's ink lands half a pixel off centre; at 4.7 the tip DOES cover a pixel
# centre and the ink spans the tile symmetrically, which is what stops the ship
# wobbling a pixel sideways as it turns.
SHIP_APEX = 4.7
SHIP_BASE = -3.8
SHIP_BASE_HW = 3.8


def render_ship(step):
    """One heading as 8 rows of ASCII.  Step 0 is nose-up and each step turns
    the nose 22.5 deg clockwise -- the SAME order tables.h indexes the thrust
    vectors in, because the frame on screen and the vector the physics uses
    come out of one byte and a mismatch is invisible on a screenshot."""
    th = 2.0 * math.pi * step / ROT_STEPS
    s, c = math.sin(th), math.cos(th)
    rows = []
    for py in range(8):
        row = ""
        for px in range(8):
            du, dv = px + 0.5 - 4.0, py + 0.5 - 4.0   # pixel centre, tile-centred
            u = du * s - dv * c                       # along the nose
            v = du * c + dv * s                       # to the nose's right
            hw = SHIP_BASE_HW * (SHIP_APEX - u) / (SHIP_APEX - SHIP_BASE)
            row += "#" if (SHIP_BASE <= u <= SHIP_APEX and -hw <= v <= hw) else "."
        rows.append(row)
    return rows


SPRITES = [enc(render_ship(h)) for h in range(ROT_STEPS)]

# ------------------------------------------------------------- self-check
TILE_IDS = sorted(DRAWN)
assert len(TILES) == 56, "expected 56 tile ids, got %d" % len(TILES)
assert TILE_IDS == [0, 1, 2, 19] + list(range(20, 56)), (
    "unaccounted tile ids: %r" % (sorted(set(range(56)) - DRAWN - set(GAP))))
assert max(TILE_IDS) < 128, "tile id %d >= 128 reads the sprite bank" % max(TILE_IDS)

# The ship headings.  Two things can be wrong here and both are invisible on a
# screenshot: a "rotation" that stopped rotating (sixteen copies of one frame),
# and a frame rendered at a different angle than the thrust vector tables.h
# gives the same index -- which thrusts the ship sideways while it looks right.
assert len(SPRITES) == ROT_STEPS, \
    "expected %d ship headings, got %d" % (ROT_STEPS, len(SPRITES))
assert len(set(tuple(s) for s in SPRITES)) == ROT_STEPS, \
    "the ship headings are not all distinct -- some step renders a repeat"
for h in range(ROT_STEPS):
    rows = render_ship(h)
    ink = [(x, y) for y in range(8) for x in range(8) if rows[y][x] == "#"]
    assert ink, "heading %d renders nothing" % h
    # Which way the frame ACTUALLY points, read off the pixels rather than taken
    # on trust from the step it was rendered at.  The ship is a triangle: its
    # mass sits behind the nose, so the ink's centroid is displaced AWAY from
    # the heading.  Measured along the heading that is cos = -1; measured across
    # it, 0; measured the wrong way round, +1.
    cx = sum(p[0] for p in ink) / len(ink) - 3.5
    cy = sum(p[1] for p in ink) / len(ink) - 3.5
    a = 2.0 * math.pi * h / ROT_STEPS
    cos_back = (cx * math.sin(a) + cy * -math.cos(a)) / math.hypot(cx, cy)
    # -0.95 rather than -1: the measured values sit at -0.999 or tighter, and
    # the slack is for art tweaks.  What it rejects is a whole step or more --
    # 22.5 deg off reads -0.92 -- which is the size of error the frame/vector
    # pairing can actually have.
    assert cos_back < -0.95, \
        "heading %d does not point where it says (centroid cos %.2f)" % (h, cos_back)

# ----------------------------------------------------------------- output
lines = [
    "/* Generated by mkgfx.py - do not edit.  Run `make gfx` to regenerate. */",
    "#ifndef GFX_H",
    "#define GFX_H",
    "",
    "#include <stdint.h>",
    "",
    "/* BG tile ids, all < 128: LCDC.4 = 0 puts BG tile data in the 0x9000 page,",
    " * and an id >= 128 would alias into the sprite bank at 0x8000 instead.",
    " * 3..18 are the unused gap between the terrain tiles and the font. */",
    "#define GFX_TILE_COUNT %d" % len(TILES),
]
for name, val in NAMES:
    lines.append("#define %-15s %d" % (name, val))
lines += [
    "",
    "/* The ship, one tile per heading: sprite tile SPR_SHIP0 + heading, and the",
    " * heading is also the index into tables.h's thrust_dx/dy.  ROT_STEPS (16)",
    " * headings at 22.5 deg, pre-rendered here so nothing rotates at runtime --",
    " * sprite frame i and thrust vector i point the same way, which is the whole",
    " * pairing.  Colour 0 is a HOLE on a sprite, so the ship's background is",
    " * transparent here - which is why sprites are a second array and not a",
    " * slice of gfx_tiles. */",
    "#define GFX_SPRITE_COUNT %d" % len(SPRITES),
    "#define SPR_SHIP0 %d" % 0,
    "",
    "static const uint8_t gfx_tiles[] = {",
]
for i, t in enumerate(TILES):
    lines.append("    " + ",".join("0x%02X" % b for b in t) + ",  /* %d */" % i)
lines += ["};", "", "static const uint8_t gfx_sprites[] = {"]
for i, t in enumerate(SPRITES):
    lines.append("    " + ",".join("0x%02X" % b for b in t) + ",  /* %d */" % i)
lines += ["};", "", "#endif", ""]

with open("gfx.h", "w") as f:
    f.write("\n".join(lines))
print("gfx.h: %d tiles (%d bytes), %d sprite tiles"
      % (len(TILES), len(TILES) * 16, len(SPRITES)))
