#!/usr/bin/env python3
"""Level geometry for LUNA LANDEER -> terrain.h

Two profiles, one table and one pointer, all generated and all committed, so a
plain `make` needs no Python at all:

    terrain_lander[WORLD_COLS]    mode LANDER's surface row at each column
    terrain_descent[WORLD_COLS]   the DESCENT world's, ~100 tiles down
    terrain                       THE ACTIVE ONE -- a `const uint8_t *`
    pads[PAD_COUNT]               the flat landing runs: span + multiplier

HEIGHTS ARE IN 8 px TILE UNITS, not pixels, and the type has to reach 255 of
them.  Mode LANDER's world is one screen and its profile only uses rows 0..17,
which is exactly the trap: capping the type at one screen (<= 17, or a byte
counted in pixels) makes M2's DESCENT -- whose surface is ~100 tiles down -- a
refactor of sim.h, every tests/test_sim.c case and every probe check.  The unit
is the 8 px tile mkgfx.py draws and TERRAIN_MAX_TILES is 255; M1 simply does
not use the top of the range.

WHY `terrain` IS A POINTER AND NOT AN ARRAY.  sim.h's ship_step() reads
terrain[col] to find the ground under the ship and tools/probe.py reads the
symbol out of the linker map, so the NAME has to stay one resolvable thing
across both worlds.  Renaming LANDER's array to terrain_lander and letting the
mode pick a different array would break the collision call and the probe's
address lookup together -- and it would look like a physics bug.  So: two
arrays, one pointer, and main.c assigns it.

WHY THE DESCENT IS TALLER THAN A MAP.  One BG map is 32x32 tiles = 256 px.  A
per-column fill that walks from the surface down to the bottom of the screen
writes nothing for a profile below the view, and a blit that tried to write all
100 rows would be TRUNCATED at row 31 by the map with no error anywhere.  The
new assertion below -- taller than MAP_TILES -- is what says so at generate
time instead of in P10.

The wrap seam is the other family trap.  WORLD_COLS is 160 px / 8 = 20, which
is NOT a power of two, so both profiles are built from triangle waves whose
periods divide 20 (a % and never an & WORLD_MASK -- 160 is not 256) and the
self-check below holds the seam shut by construction.

Run `make level` to regenerate; terrain.h is committed.
"""

# ------------------------------------------------------------- the world ---
WORLD_COLS = 20             # 160 px / 8 px per tile: both worlds are one
                            # screen WIDE, and neither is a power of two.
VIEW_TILES_H = 18           # the screen, in tiles (20x18 with SCX/SCY = 0)
MAP_TILES = 32              # ONE BG MAP is 32x32 tiles.  A profile taller than
                            # this cannot be put on the map by a single blit --
                            # the rows past 31 have nowhere to go and the write
                            # truncates SILENTLY.  That is the whole reason the
                            # renderer needs a window, and the reason the
                            # DESCENT assertion below is about this number.
TERRAIN_MAX_TILES = 255     # the type's ceiling, NOT a profile's.

RIPPLE_FAST = 4             # +0..1
RIPPLE_SLOW = WORLD_COLS    # +0..2 after >> 2

# A pad is a flat run, so its row is a level constant rather than a ripple.  The
# spans and multipliers are SHARED by both worlds -- sim.h's pad_mult() reads
# this one table and P5's landing rule scores off it, so a second table would be
# a second answer to "is this column a landing site".  Only the DEPTH differs,
# and that is per profile below.
PADS = [
    ("LOW",  4,  7, 1),
    ("HIGH", 13, 14, 2),
]

# The profiles, and each world's own x1/x2 pad row.  x2 sits ABOVE x1 in both,
# because the multiplier -> row map is the contract probe.p2_terrain mirrors: a
# x2 pad is a smaller, higher platform than a x1 pad.
#
# `on_screen` is which half of the size assertion applies: LANDER's profile has
# to fit the 18-row view (the world IS the screen), and DESCENT's has to NOT
# fit a 32-row map (that is what makes it a descent).  Both are asserted below.
PROFILES = [
    dict(name="LANDER",  arr="terrain_lander",  base=9,
         pad_rows={1: 12, 2: 9},   on_screen=True),
    dict(name="DESCENT", arr="terrain_descent", base=96,
         pad_rows={1: 100, 2: 97}, on_screen=False),
]

# How big a step the profile may take onto a pad shoulder, and across the wrap
# seam.  Not a look-and-feel number: a pad that is a cliff is one the ship
# cannot land on, and a seam step means the seam is visible.
PAD_MAX_STEP = 4
SEAM_MAX_STEP = 2


def tri(period, col):
    """Triangle wave 0..period//2, periodic in `period`."""
    a = col % period
    if a >= period // 2:
        a = period - 1 - a
    return a


def profile(base, col):
    """Surface row at world column `col`, before any pad is carved.

    Periodic in WORLD_COLS because both ripple periods divide it, so the ripple
    leaving the right edge is the one entering the left edge.  `base` is the
    only thing that tells the two worlds apart, which is the point: a descent
    is the same shape laid deeper, not a second kind of terrain."""
    col %= WORLD_COLS
    return base + tri(RIPPLE_FAST, col) + (tri(RIPPLE_SLOW, col) >> 2)


def build(p):
    terrain = [profile(p["base"], c) for c in range(WORLD_COLS)]
    for _name, col0, col1, mult in PADS:
        for c in range(col0, col1 + 1):
            terrain[c] = p["pad_rows"][mult]
    return terrain


def self_check(p, terrain):
    """Everything the renderer and M2 are entitled to assume about terrain.h.

    Run for EVERY profile before the file is written: a generator that emits a
    height the type cannot hold, or a pad that is not actually flat, has to fail
    here and not as a sprite standing in the ground on hardware."""
    name = p["name"]

    assert len(terrain) == WORLD_COLS, \
        "%s: expected %d columns, got %d" % (name, WORLD_COLS, len(terrain))

    # 255, not 17: this is the ceiling the TYPE has to carry, and it is the
    # whole reason terrain[] is not a screen-sized array.
    assert 0 <= min(terrain) and max(terrain) <= TERRAIN_MAX_TILES, \
        "%s: heights must fit TERRAIN_MAX_TILES (%d), got %d..%d" \
        % (name, TERRAIN_MAX_TILES, min(terrain), max(terrain))

    # The size assertion, and it has two halves because the two worlds are
    # meant to sit on opposite sides of it.
    if p["on_screen"]:
        assert max(terrain) < VIEW_TILES_H, \
            "%s's profile must fit on screen, got a surface row of %d" \
            % (name, max(terrain))
    else:
        assert max(terrain) > MAP_TILES, \
            "%s's profile is %d tiles deep, which fits inside one BG map (%d) " \
            "-- a descent that fits on one screen is a relabelled LANDER, and " \
            "a blit of it would never meet the truncation the window exists " \
            "to avoid" % (name, max(terrain), MAP_TILES)

    # The seam.  Both ripple periods must divide WORLD_COLS (so `% period` is
    # the same function either side of column 0), no pad may sit on a seam
    # column (or carving it would be the one thing the periodicity misses), and
    # the step across the seam has to be walkable.
    for period in (RIPPLE_FAST, RIPPLE_SLOW):
        assert WORLD_COLS % period == 0, \
            "ripple period %d does not divide WORLD_COLS (%d): the seam would " \
            "be visible" % (period, WORLD_COLS)
    for c in range(WORLD_COLS):
        assert profile(p["base"], c) == profile(p["base"], c + WORLD_COLS), \
            "%s: profile is not periodic at column %d" % (name, c)

    for pname, col0, col1, mult in PADS:
        assert mult in p["pad_rows"], \
            "%s: pad %s has no pad_rows entry for x%d" % (name, pname, mult)
        assert 1 <= col0 <= col1 <= WORLD_COLS - 2, \
            "%s: pad %s (%d..%d) touches a seam column or is inverted" \
            % (name, pname, col0, col1)

    # Each named pad is a flat run of equal heights -- the surface row the ship
    # lands on, the same for every column in the span, and the one this world's
    # pad_rows says.
    for pname, col0, col1, mult in PADS:
        run = terrain[col0:col1 + 1]
        assert len(set(run)) == 1, \
            "%s: pad %s is not flat: %r" % (name, pname, run)
        assert run[0] == p["pad_rows"][mult], \
            "%s: pad %s sits at row %d, not the x%d row (%d)" \
            % (name, pname, run[0], mult, p["pad_rows"][mult])

    # Pads do not overlap: two multipliers on one column is a scoring ambiguity
    # nothing downstream could resolve.  Checked once per profile because the
    # spans are shared -- if they overlapped they would do it in both.
    seen = set()
    for pname, col0, col1, _mult in PADS:
        for c in range(col0, col1 + 1):
            assert c not in seen, \
                "column %d is claimed by two pads (%s)" % (c, pname)
            seen.add(c)

    # A pad is a plateau, not a cliff, and the seam is a step like any other.
    for pname, col0, col1, mult in PADS:
        row = terrain[col0]
        if col0 > 0:
            assert abs(row - profile(p["base"], col0 - 1)) <= PAD_MAX_STEP, \
                "%s: pad %s steps %d tiles up onto column %d" \
                % (name, pname, abs(row - profile(p["base"], col0 - 1)), col0 - 1)
        if col1 < WORLD_COLS - 1:
            assert abs(row - profile(p["base"], col1 + 1)) <= PAD_MAX_STEP, \
                "%s: pad %s steps %d tiles off column %d" \
                % (name, pname, abs(row - profile(p["base"], col1 + 1)), col1 + 1)
    assert abs(profile(p["base"], 0) -
               profile(p["base"], WORLD_COLS - 1)) <= SEAM_MAX_STEP, \
        "%s: the wrap seam steps %d tiles" \
        % (name, abs(profile(p["base"], 0) - profile(p["base"], WORLD_COLS - 1)))


# ------------------------------------------------------------- generate ----
built = [(p, build(p)) for p in PROFILES]
for _p, _t in built:
    self_check(_p, _t)

by_name = {p["name"]: t for p, t in built}
lander = by_name["LANDER"]
descent = by_name["DESCENT"]

lines = [
    "/* Generated by mklevel.py - do not edit.  Run `make level` to regenerate. */",
    "#ifndef TERRAIN_H",
    "#define TERRAIN_H",
    "",
    "#include <stdint.h>",
    "",
    "/* Both worlds are 160 px / 8 px per tile WIDE, and neither is one screen",
    " * wide plus a bit: 160 is NOT a power of two, so the wrap is two compares",
    " * (x < 0 -> x += 160; x >= 160 -> x -= 160) and never an `& WORLD_MASK`:",
    " * masking would wrap at 256 and put the seam off-screen. */",
    "#define WORLD_COLS %d" % WORLD_COLS,
    "",
    "/* The ceiling on a surface row, in 8 px TILE units -- the unit mkgfx.py",
    " * draws the terrain tiles in.  NOT pixels, and NOT the screen: mode 1 only",
    " * reaches row %d, the DESCENT profile reaches row %d, and the type has to"
    % (max(lander), max(descent)),
    " * hold both without a refactor. */",
    "#define TERRAIN_MAX_TILES %d" % TERRAIN_MAX_TILES,
]


def emit_profile(lines, p, terrain):
    lines.append("")
    lines.append("/* %s's surface row (tile units) at each world tile column.  Periodic"
                 % p["name"])
    lines.append(" * in WORLD_COLS: a ripple of period %d inside a swell of period %d,"
                 % (RIPPLE_FAST, RIPPLE_SLOW))
    lines.append(" * both dividing %d, so the wrap seam is invisible.  Rows %d..%d."
                 % (WORLD_COLS, min(terrain), max(terrain)))
    if p["on_screen"]:
        lines.append(" * One screen tall -- the world IS the screen, so main.c windows it")
        lines.append(" * at row 0 and the offset arithmetic is the identity there. */")
    else:
        lines.append(" * TALLER THAN A BG MAP (%d rows) and taller than the view (%d):"
                     % (MAP_TILES, VIEW_TILES_H))
        lines.append(" * there is no blit that puts these rows on one map, which is why")
        lines.append(" * main.c draws a WINDOW of it rather than the whole profile. */")
    lines.append("static const uint8_t %s[WORLD_COLS] = {" % p["arr"])
    for i in range(0, WORLD_COLS, 10):
        lines.append("    " + ", ".join("%3d" % v for v in terrain[i:i + 10]) + ",")
    lines.append("};")


for _p, _t in built:
    emit_profile(lines, _p, _t)

lines += [
    "",
    "/* THE ACTIVE PROFILE, and the one symbol in this header that is not a",
    " * constant.  sim.h's ship_step() reads terrain[col] to find the ground",
    " * under the ship and tools/probe.py reads terrain out of the linker map, so",
    " * the two worlds share THIS name rather than one array being renamed per",
    " * mode -- a second name would break the collision call and the probe's",
    " * address lookup together, and the mismatch would look like a physics bug.",
    " * main.c assigns it; everything else just reads through it. */",
    "static const uint8_t *terrain = terrain_lander;",
    "",
    "/* The flat landing runs.  col0/col1 are inclusive world tile columns; mult",
    " * is the score multiplier for a landing that stays on the pad.  The span is",
    " * flat (mklevel.py asserts it for BOTH worlds), so terrain[col0..col1] is",
    " * all one row -- at a different depth in each: the DESCENT world's pads sit",
    " * on its own pad_rows, and sim.h's pad_mult() is a question about columns,",
    " * which is why the spans are shared. */",
    "typedef struct {",
    "    uint8_t col0;",
    "    uint8_t col1;",
    "    uint8_t mult;",
    "} Pad;",
    "",
    "#define PAD_COUNT %d" % len(PADS),
]
for i, (name, _c0, _c1, _m) in enumerate(PADS):
    lines.append("#define PAD_%-8s %d" % (name, i))
lines.append("")
lines.append("static const Pad pads[PAD_COUNT] = {")
for name, col0, col1, mult in PADS:
    lines.append("    { %2d, %2d, %d },  /* %s */" % (col0, col1, mult, name))
lines += ["};", "", "#endif", ""]

with open("terrain.h", "w") as f:
    f.write("\n".join(lines))

for p, t in built:
    print("%-8s %s: rows %d..%d, pads %s"
          % (p["name"], p["arr"], min(t), max(t),
             ", ".join("%s(%d..%d x%d@%d)" % (n, a, b, m, p["pad_rows"][m])
                       for n, a, b, m in PADS)))
print("terrain.h: %d columns, %d pads, two profiles, one `terrain` pointer"
      % (WORLD_COLS, len(PADS)))
