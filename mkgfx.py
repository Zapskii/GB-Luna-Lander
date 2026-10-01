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

# The id gap between the terrain tiles and the font, less the four the stars
# took (3..6).  Named because the self-check below asserts the gap is exactly
# these ids and nothing else: a typo'd id would otherwise grow the array and
# shift the numbering in silence.
GAP = list(range(7, 20))

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

# ------------------------------------------------------------------ stars
# FOUR variants, and the count is the point.  One star tile would put every
# star at the same offset inside its own 8x8 cell, so the dots would land on a
# perfect 8 px lattice and the sky would read as a machined grid rather than as
# a field.  Four offsets break the lattice; two are drawn bright ('#') and two
# dim ('2'), so the sky has a little depth instead of being a flat scatter.
#
# They sit on 3..6, inside the gap that was already reserved between the
# terrain and the font, so the digit and letter numbering tools/probe.py and
# the HUD both spell out does not move.  tools/mklevel.py's star_field[] picks
# between them per world cell; these are only the four shapes.
put(3, ["........",
        "..#.....",
        "........",
        "........",
        "........",
        "........",
        "........",
        "........"], "T_STAR0")
put(4, ["........",
        "........",
        "........",
        "........",
        "........",
        "......#.",
        "........",
        "........"], "T_STAR1")
put(5, ["........",
        ".....2..",
        "........",
        "........",
        "........",
        "........",
        "........",
        "........"], "T_STAR2")
put(6, ["........",
        "........",
        "........",
        "........",
        "........",
        "........",
        ".2......",
        "........"], "T_STAR3")

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
 '-': ".....|.....|.....|#####|.....|.....|.....",
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

# The minus, on 56 - the one glyph the HUD needs that A-Z/0-9 does not cover.
# glyph() sends anything outside those two runs to T_BLANK, so a signed reading
# ("VY -02") printed without this renders the sign as a HOLE: the number is
# still there, one column left of where the layout put it, and it reads as a
# spacing bug rather than as a missing tile.
put(56, ["." + r + ".." for r in FONT['-'].split("|")] + ["........"],
    "T_MINUS")

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


SHIP_SPRITES = [enc(render_ship(h)) for h in range(ROT_STEPS)]

# -------------------------------------------------------------- the burst
# THE CRASH EXPLOSION, and it is a SPRITE and not a BG stamp: a crash can happen
# at any column of a world that wraps and at any camera offset, so a sprite is
# placed in SCREEN space by move_sprite() -- nothing to write into a map, and
# nothing to clean up when the burst is over but four OAM slots.
#
# FOUR FRAMES OF 16x16.  Typed in by hand, unlike the ship's headings: a
# rotation has angles that cannot be drawn at 8x8 without aliasing, but a burst
# has no geometry to get wrong -- each frame IS the shape, and the frames are
# the animation.  The ink thins from the flash to the specks, which is what
# makes it read as a blast rather than as four drawings in a row.
#
# EACH FRAME IS FOUR 8x8 QUADRANTS, top-left, top-right, bottom-left,
# bottom-right, because SPRITES_8x8 draws one tile per OAM slot and a 16x16 is
# four slots.  That order is main.c's `(i & 1, i >> 1)` and the check below is
# what stops the two drifting apart.
BOOM_STEPS = 4
BOOM_ROWS = 16                  # px a side, so 2x2 tiles of 8
BOOM_QUADRANTS = 4              # tiles per frame; the emitted tile order

BOOM = [
    # 0 - the flash: the ship is gone and this is what is left of it
    ["................",
     "................",
     ".....######.....",
     "....########....",
     "...##########...",
     "..############..",
     "..############..",
     "..############..",
     "..############..",
     "..############..",
     "...##########...",
     "....########....",
     ".....######.....",
     "................",
     "................",
     "................"],
    # 1 - it blows outward into a ring, and the ring is already coming apart
    ["................",
     "...##......##...",
     "..####....####..",
     "..#..##..##..#..",
     ".##...####...##.",
     ".#..#.####.#..#.",
     ".##..######..##.",
     ".#..########..#.",
     ".#..########..#.",
     ".##..######..##.",
     ".#..#.####.#..#.",
     ".##...####...##.",
     "..#..##..##..#..",
     "..####....####..",
     "...##......##...",
     "................"],
    # 2 - shreds, thrown wide
    ["..#..........#..",
     "....#......#....",
     "..#...#..#...#..",
     ".......##.......",
     "...#..#..#..#...",
     "......#..#......",
     "..#...#..#......",
     "....#......#....",
     "..#..........#..",
     ".....#....#.....",
     "................",
     "..#..........#..",
     ".....#....#.....",
     "..#........#....",
     "................",
     "................"],
    # 3 - specks, and the last of it
    ["................",
     "...#........#...",
     "........#.......",
     ".....#..........",
     "..........#.....",
     "...#............",
     "........#.......",
     "....#........#..",
     "..........#.....",
     ".......#........",
     "..##............",
     "......#.....#...",
     ".....#..........",
     ".........#......",
     "................",
     "................"],
]


def boom_tiles(rows):
    """One 16x16 frame -> its four 8x8 quadrants as tile bytes, in the order
    main.c places them: (0,0), (8,0), (0,8), (8,8)."""
    assert len(rows) == BOOM_ROWS, "frame is %d rows, not %d" % (len(rows), BOOM_ROWS)
    for r in rows:
        assert len(r) == BOOM_ROWS, "row %r is %d wide, not %d" % (r, len(r), BOOM_ROWS)
    half = BOOM_ROWS // 2
    quads = [(0, 0), (half, 0), (0, half), (half, half)]
    return [enc([rows[y][x:x + half] for y in range(dy, dy + half)])
            for (x, dy) in quads]


BOOM_SPRITES = [t for f in BOOM for t in boom_tiles(f)]

# The whole OBJ array main.c hands to set_sprite_data(): the ship's headings
# first, then the burst, so SPR_SHIP0 + heading and SPR_BOOM0 + frame*4 + q are
# the two id bases and neither moves when the other grows.
SPR_BOOM0 = len(SHIP_SPRITES)
SPRITES = SHIP_SPRITES + BOOM_SPRITES

# ------------------------------------------------------------- self-check
# NTILES is the id space, and it is written out rather than taken from
# len(TILES): an id typed one too high grows the array and shifts nothing, so
# the check has to be told what the numbering IS to be able to disagree with it.
NTILES = 57
TILE_IDS = sorted(DRAWN)
assert len(TILES) == NTILES, "expected %d tile ids, got %d" % (NTILES, len(TILES))
assert TILE_IDS == [0, 1, 2, 3, 4, 5, 6, 19] + list(range(20, NTILES)), (
    "unaccounted tile ids: %r" % (sorted(set(range(NTILES)) - DRAWN - set(GAP))))
assert max(TILE_IDS) < 128, "tile id %d >= 128 reads the sprite bank" % max(TILE_IDS)

# The ONE number the two generators share.  tools/mklevel.py's star_field[] is
# emitted in TILE ID space -- main.c writes a sky cell straight from it, with no
# mapping step, because that loop runs once per cell of every streamed row -- so
# its STAR_BLANK/STAR_TILE0 have to agree with the ids below.  A renumbering of
# the gap would otherwise move the stars out from under a sky that still points
# at where they used to be: every star would silently become a digit.
_IDS = dict(NAMES)
assert _IDS["T_BLANK"] == 0, "mklevel.py's STAR_BLANK says 0, this says %d" % _IDS["T_BLANK"]
assert _IDS["T_STAR0"] == 3, "mklevel.py's STAR_TILE0 says 3, this says %d" % _IDS["T_STAR0"]

# The ship headings.  Two things can be wrong here and both are invisible on a
# screenshot: a "rotation" that stopped rotating (sixteen copies of one frame),
# and a frame rendered at a different angle than the thrust vector tables.h
# gives the same index -- which thrusts the ship sideways while it looks right.
assert len(SHIP_SPRITES) == ROT_STEPS, \
    "expected %d ship headings, got %d" % (ROT_STEPS, len(SHIP_SPRITES))
assert len(set(tuple(s) for s in SHIP_SPRITES)) == ROT_STEPS, \
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

# The burst.  A frame that is a different SIZE from the others, or a quadrant
# split that dropped a row, still encodes and still draws -- as a 16x16 that is
# quietly assembled wrong, which is a screenshot bug nobody would trace back
# here.  The width and height are asserted in boom_tiles(); what is left for
# this block is the tile count and the thing the animation IS.
assert len(BOOM) == BOOM_STEPS, \
    "expected %d burst frames, got %d" % (BOOM_STEPS, len(BOOM))
assert len(BOOM_SPRITES) == BOOM_STEPS * BOOM_QUADRANTS, \
    "the burst is %d tiles, not %d frames x %d quadrants" \
    % (len(BOOM_SPRITES), BOOM_STEPS, BOOM_QUADRANTS)
assert SPR_BOOM0 == ROT_STEPS, \
    "the burst starts at tile %d, and the ship's headings run to %d" \
    % (SPR_BOOM0, ROT_STEPS - 1)
assert len(set(tuple(t) for t in BOOM_SPRITES)) > 1, \
    "every quadrant of the burst is the same tile"
_ink = [sum(row.count("#") for row in f) for f in BOOM]
for i, n in enumerate(_ink):
    assert n, "burst frame %d is empty -- an invisible frame in the animation" % i
# It THINS: the flash is the heaviest frame and the specks the lightest, so a
# burst whose frames got denser -- a generator reading them backwards, or a
# last frame left as a copy of the first -- is caught here rather than as an
# explosion that seems to reassemble itself.  The margin is one pixel, so
# redrawing the art is free; reversing the order is not.
assert _ink[0] == max(_ink) and _ink[-1] == min(_ink) and _ink[0] > _ink[-1], \
    "the burst does not thin from the flash to the specks (%r)" % _ink

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
    " * 3..6 are the stars, 7..18 the unused gap up to the font, and 20/30 start",
    " * the digit and letter runs glyph() indexes into. */",
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
    " * slice of gfx_tiles.",
    " *",
    " * THEN THE BURST, at SPR_BOOM0: BOOM_STEPS frames of 16x16, each frame four",
    " * 8x8 quadrants in tile order top-left, top-right, bottom-left, bottom-right,",
    " * because SPRITES_8x8 draws one tile per OAM slot.  Frame f's top-left is",
    " * SPR_BOOM0 + f * SPR_BOOM_TILES, and main.c has to place them in the same",
    " * order it is written here -- the two are the same contract the ship's",
    " * heading and its thrust vector have. */",
    "#define GFX_SPRITE_COUNT %d" % len(SPRITES),
    "#define SPR_SHIP0 %d" % 0,
    "#define SPR_BOOM0 %d" % SPR_BOOM0,
    "#define SPR_BOOM_TILES %d" % BOOM_QUADRANTS,
    "#define BOOM_STEPS %d" % BOOM_STEPS,
    "#define BOOM_PX %d" % BOOM_ROWS,
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
