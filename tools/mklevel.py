#!/usr/bin/env python3
"""Level geometry for LUNA LANDEER -> terrain.h

One array and one table, both generated and both committed, so a plain `make`
needs no Python at all:

    terrain[WORLD_COLS]   the surface row at each world tile column
    pads[PAD_COUNT]       the flat landing runs: span + score multiplier

HEIGHTS ARE IN 8 px TILE UNITS, not pixels, and the type has to reach 255 of
them.  Mode LANDER's world is one screen and its profile only uses rows 0..17,
which is exactly the trap: capping the type at one screen (<= 17, or a byte
counted in pixels) makes M2's DESCENT -- which puts the surface ~100 tiles down
-- a refactor of sim.h, every tests/test_sim.c case and every probe check.  The
unit is the 8 px tile mkgfx.py draws and TERRAIN_MAX_TILES is 255; M1 simply
does not use the top of the range.

The wrap seam is the other family trap.  WORLD_COLS is 160 px / 8 = 20, which
is NOT a power of two, so the profile is built from triangle waves whose periods
divide 20 (a % and never an & WORLD_MASK -- 160 is not 256) and the self-check
below holds the seam shut by construction.

Run `make level` to regenerate; terrain.h is committed.
"""

# ------------------------------------------------------------- the world ---
WORLD_COLS = 20             # 160 px / 8 px per tile: mode LANDER's whole world
VIEW_TILES_H = 18           # the screen, in tiles (20x18 with SCX/SCY = 0)
TERRAIN_MAX_TILES = 255     # the type's ceiling, NOT the profile's: M2 needs
                            # ~100, M1 uses 0..12.

BASE = 9                    # the profile's mean surface row

# The ripple periods.  Both MUST divide WORLD_COLS or the wrap seam stops being
# invisible -- the self-check below asserts that, not the comment.
RIPPLE_FAST = 4             # +0..1
RIPPLE_SLOW = WORLD_COLS    # +0..2 after >> 2

# A pad is a flat run, so its row is a level constant rather than a ripple.  The
# multiplier -> row map is the contract probe.p2_terrain mirrors: a x2 pad is a
# smaller, higher platform than a x1 pad, and the probe catches a generator that
# gives one the other's row.
PAD_ROWS = {1: 12, 2: 9}

# (name, first column, last column, multiplier) -- columns inclusive.
PADS = [
    ("LOW",  4,  7, 1),
    ("HIGH", 13, 14, 2),
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


def profile(col):
    """Surface row at world column `col`, before any pad is carved.

    Periodic in WORLD_COLS because both ripple periods divide it, so the ripple
    leaving the right edge is the one entering the left edge."""
    col %= WORLD_COLS
    return BASE + tri(RIPPLE_FAST, col) + (tri(RIPPLE_SLOW, col) >> 2)


def build():
    terrain = [profile(c) for c in range(WORLD_COLS)]
    for _name, col0, col1, mult in PADS:
        for c in range(col0, col1 + 1):
            terrain[c] = PAD_ROWS[mult]
    return terrain


def self_check(terrain):
    """Everything the renderer and M2 are entitled to assume about terrain.h.

    These run BEFORE the file is written: a generator that emits a height the
    type cannot hold, or a pad that is not actually flat, has to fail here and
    not as a sprite standing in the ground on hardware."""
    assert len(terrain) == WORLD_COLS, \
        "expected %d columns, got %d" % (WORLD_COLS, len(terrain))

    # 255, not 17: this is the ceiling the TYPE has to carry, and it is the
    # whole reason terrain[] is not a screen-sized array.
    assert 0 <= min(terrain) and max(terrain) <= TERRAIN_MAX_TILES, \
        "heights must fit TERRAIN_MAX_TILES (%d), got %d..%d" \
        % (TERRAIN_MAX_TILES, min(terrain), max(terrain))
    assert max(terrain) < VIEW_TILES_H, \
        "mode 1's profile must fit on screen, got a surface row of %d" % max(terrain)

    # The seam.  Both ripple periods must divide WORLD_COLS (so `% period` is
    # the same function either side of column 0), no pad may sit on a seam
    # column (or carving it would be the one thing the periodicity misses), and
    # the step across the seam has to be walkable.
    for period in (RIPPLE_FAST, RIPPLE_SLOW):
        assert WORLD_COLS % period == 0, \
            "ripple period %d does not divide WORLD_COLS (%d): the seam would " \
            "be visible" % (period, WORLD_COLS)
    for c in range(WORLD_COLS):
        assert profile(c) == profile(c + WORLD_COLS), \
            "profile is not periodic at column %d" % c

    for name, col0, col1, mult in PADS:
        assert mult in PAD_ROWS, "pad %s has no PAD_ROWS entry for x%d" % (name, mult)
        assert 1 <= col0 <= col1 <= WORLD_COLS - 2, \
            "pad %s (%d..%d) touches a seam column or is inverted" \
            % (name, col0, col1)

    # Each named pad is a flat run of equal heights -- the surface row the ship
    # lands on, the same for every column in the span.
    for name, col0, col1, mult in PADS:
        run = terrain[col0:col1 + 1]
        assert len(set(run)) == 1, \
            "pad %s is not flat: %r" % (name, run)
        assert run[0] == PAD_ROWS[mult], \
            "pad %s sits at row %d, not the x%d row (%d)" \
            % (name, run[0], mult, PAD_ROWS[mult])

    # Pads do not overlap: two multipliers on one column is a scoring ambiguity
    # nothing downstream could resolve.
    seen = set()
    for name, col0, col1, _mult in PADS:
        for c in range(col0, col1 + 1):
            assert c not in seen, "column %d is claimed by two pads (%s)" % (c, name)
            seen.add(c)

    # A pad is a plateau, not a cliff, and the seam is a step like any other.
    for name, col0, col1, mult in PADS:
        row = terrain[col0:col1 + 1][0]
        if col0 > 0:
            assert abs(row - profile(col0 - 1)) <= PAD_MAX_STEP, \
                "pad %s steps %d tiles up onto column %d" \
                % (name, abs(row - profile(col0 - 1)), col0 - 1)
        if col1 < WORLD_COLS - 1:
            assert abs(row - profile(col1 + 1)) <= PAD_MAX_STEP, \
                "pad %s steps %d tiles off column %d" \
                % (name, abs(row - profile(col1 + 1)), col1 + 1)
    assert abs(profile(0) - profile(WORLD_COLS - 1)) <= SEAM_MAX_STEP, \
        "the wrap seam steps %d tiles" % abs(profile(0) - profile(WORLD_COLS - 1))


# ------------------------------------------------------------- generate ----
terrain = build()
self_check(terrain)

lines = [
    "/* Generated by mklevel.py - do not edit.  Run `make level` to regenerate. */",
    "#ifndef TERRAIN_H",
    "#define TERRAIN_H",
    "",
    "#include <stdint.h>",
    "",
    "/* Mode LANDER's world: 160 px / 8 px per tile.  NOT a power of two, so the",
    " * wrap is two compares (x < 0 -> x += 160; x >= 160 -> x -= 160) and never",
    " * an `& WORLD_MASK`: masking would wrap at 256 and put the seam off-screen. */",
    "#define WORLD_COLS %d" % WORLD_COLS,
    "",
    "/* The ceiling on a surface row, in 8 px TILE units -- the unit mkgfx.py",
    " * draws the terrain tiles in.  NOT pixels, and NOT the screen: mode 1 only",
    " * reaches row %d, but M2's DESCENT puts the surface ~100 tiles down and the"
    % max(terrain),
    " * type has to hold that without a refactor. */",
    "#define TERRAIN_MAX_TILES %d" % TERRAIN_MAX_TILES,
    "",
    ("/* Surface row (tile units) at each world tile column.  Periodic in\n"
     " * WORLD_COLS: a ripple of period %d inside a swell of period %d, both\n"
     " * dividing %d, so the wrap seam is invisible. */"
     % (RIPPLE_FAST, RIPPLE_SLOW, WORLD_COLS)),
    "static const uint8_t terrain[WORLD_COLS] = {",
]
for i in range(0, WORLD_COLS, 10):
    lines.append("    " + ", ".join("%3d" % v for v in terrain[i:i + 10]) + ",")
lines += [
    "};",
    "",
    "/* The flat landing runs.  col0/col1 are inclusive world tile columns; mult",
    " * is the score multiplier for a landing that stays on the pad.  The span is",
    " * flat (mklevel.py asserts it), so terrain[col0..col1] is all one row. */",
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

print("terrain.h: %d columns, rows %d..%d, %d pads %s"
      % (WORLD_COLS, min(terrain), max(terrain), len(PADS),
         ", ".join("%s(%d..%d x%d@%d)" % (n, a, b, m, PAD_ROWS[m])
                   for n, a, b, m in PADS)))
