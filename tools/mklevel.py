#!/usr/bin/env python3
"""Level geometry for LUNA LANDER -> terrain.h

TWELVE WORLDS A MODE, and two chains of them, all generated and all committed,
so a plain `make` needs no Python at all:

    terrain_lander[WORLD_COLS]      mode LANDER's level 1, at each column
    terrain_lander_l2 .. _l12       the rest of that chain, the same size
    terrain_descent .. _l12         the DESCENT chain's, ~40..100 tiles down
    terrain                         THE ACTIVE ONE -- a `const uint8_t *`
    pads_<chain>_l<n>[PAD_COUNT]    each level's flat landing runs
    pads                            THE ACTIVE ONE -- a `const Pad *`
    levels_lander[]/levels_descent[]  the two chains, as main.c walks them

HEIGHTS ARE IN 8 px TILE UNITS, not pixels, and the type has to reach 255 of
them.  Mode LANDER's world is one screen and its profiles only use rows 0..17,
which is exactly the trap: capping the type at one screen (<= 17, or a byte
counted in pixels) makes the DESCENT chain -- whose deepest surface is ~100
tiles down -- a refactor of sim.h, every tests/test_sim.c case and every probe
check.  The unit is the 8 px tile mkgfx.py draws and TERRAIN_MAX_TILES is 255.

A LEVEL IS A RECIPE, EXPANDED HERE AND ONLY HERE.  `heights[c] = base +
amp * KERNELS[shape](c)`, then the pads are carved into the result -- so a level
is four bytes of intent (a shape, an amplitude, a depth and where its pads sit)
rather than twenty hand-typed numbers, and the file below reads as a set design.
WHAT SHIPS IS STILL THE 20-BYTE ARRAY, because sim.h's ship_step() reads
terrain[col] on every tick to find the ground: expanding a recipe on the Game Boy
would spend frames to save bytes nobody needs, so there is no recipe in the ROM
and no expansion at runtime.  The recipe buys AUTHORING and, more than that, it
buys VALIDATION -- see self_check() below, which rejects a hand-tuned level that
is unflyable before it can reach the ROM.

EVERY KERNEL IS ZERO AT COLUMN 0 AND COLUMN 19.  A triangle wave whose period
divides WORLD_COLS always is, and all five periods here (4, 5, 10, 20) divide
20.  So heights[0] == heights[19] == base whatever the shape and whatever the
amplitude, the wrap seam steps 0 tiles in every level, and the seam CANNOT be
made visible by tuning a level.  That is the property that makes the vocabulary
safe to hand-adjust, and it is why a phase or a random seed is not offered: a
phase moves the seam value, and a seed has nothing to check itself against.

WHY `terrain` AND `pads` ARE POINTERS AND NOT ARRAYS.  sim.h's ship_step() reads
terrain[col] and pad_mult() reads pads[i] to find the ground and its landing
sites, and tools/probe.py reads both symbols out of the linker map -- so the
NAMES have to stay one resolvable thing across twenty-four worlds.  Renaming a
level's array would break the collision call and the probe's address lookup
together, and it would look like a physics bug.  So: one array per level, one
pointer each, and main.c assigns them from the Level table.

WHY THE DESCENT CHAIN IS TALLER THAN A MAP.  One BG map is 32x32 tiles = 256 px.
A per-column fill that walks from the surface down to the bottom of the screen
writes nothing for a profile below the view, and a blit that tried to write all
100 rows would be TRUNCATED at row 31 by the map with no error anywhere.  The
`on_screen` assertion below is what says so at generate time instead of in the
renderer.

Run `make level` to regenerate; terrain.h is committed.
"""

# ------------------------------------------------------------- the world ---
WORLD_COLS = 20             # 160 px / 8 px per tile: every world is one
                            # screen WIDE, and 160 is not a power of two.
VIEW_TILES_H = 18           # the screen, in tiles (20x18 with SCX/SCY = 0)
MAP_TILES = 32              # ONE BG MAP is 32x32 tiles.  A profile taller than
                            # this cannot be put on the map by a single blit --
                            # the rows past 31 have nowhere to go and the write
                            # truncates SILENTLY.  That is the whole reason the
                            # renderer needs a window, and the reason the
                            # DESCENT assertion below is about this number.
TERRAIN_MAX_TILES = 255     # the type's ceiling, NOT a profile's.

# ------------------------------------------------------------- the shapes ---
# FIVE SILHOUETTES, each a triangle wave (or a sum of two) whose periods divide
# WORLD_COLS, which is what keeps the seam shut by construction -- see the
# module docstring.  `amp` (1 or 2) scales a kernel and cannot break that, since
# 0 * 2 is still 0.
#
# The names are what the PLAYER sees, and a row that increases is ground that is
# LOWER on the screen (row 0 is the top).  So `basin` dips the ground and
# `mound` raises it, which is the way round it is easy to write backwards.
KERNELS = {
    "ripple": (lambda c: tri(4, c) + (tri(20, c) >> 2), (4, 20)),
    "roller": (lambda c: tri(10, c),                   (10,)),
    "basin":  (lambda c: tri(20, c) >> 1,              (20,)),
    "mound":  (lambda c: -(tri(20, c) >> 1),           (20,)),
    "chop":   (lambda c: tri(5, c) + tri(4, c),        (5, 4)),
}

# How big a step the profile may take onto a pad shoulder, and across the wrap
# seam.  Not a look-and-feel number: a pad that is a cliff is one the ship
# cannot land on, and a seam step means the seam is visible.  The seam bound is
# never actually reached -- every kernel is 0 at both seam columns -- and it is
# kept as the assertion that would catch a kernel that was not.
PAD_MAX_STEP = 4
SEAM_MAX_STEP = 2

# The furthest the ship may ever have to fall, in px, measured from its spawn to
# the surface of the level's DEEPEST pad.
#
# 776 IS NOT A GUESS.  It is DESCENT level 1's own drop -- a 100-tile pad, ship
# spawned at y 16 -- which is the deepest descent this game has ever shipped and
# is known to be flyable on the tank FUEL_START gives it.  The check below is
# therefore a GEOMETRY bound with a provenance rather than a fuel model: a model
# would have to re-implement ship_step() and the landing rule here, and sim.h is
# the one copy of those that this project allows.
MAX_DROP_PX = 776
# ...and the least, so a level is a fall and not a shrug.
MIN_DROP_PX = 32
# How much air there must be under the spawn, over and above the drop above:
# a spawn at the surface row would open the level already touching down.
MIN_AIR_GAP_PX = 8

# A LANDER pad at row 16 or 17 is BENEATH THE STATUS BAR.  The telemetry is the
# WINDOW layer and covers the screen's bottom two rows whatever the background
# holds, so a pad there is drawn and never seen -- and the level would read as
# one with no landing site at all.  The play area is VIEW_TILES_H - 2 rows and
# this is the last row a pad may sit on.
LANDER_PAD_MAX_ROW = VIEW_TILES_H - 3

# Unused pads in a level's table.  col0 = 255 can never satisfy `col <= col1`
# for a column of a 20-wide world, so sim.h's pad_mult() walks past it and
# answers 0 -- exactly as it does for bare ground.  That is what lets PAD_COUNT
# be a compile-time constant on the collision hot path while the levels declare
# one, two or three pads between them.
PAD_SENTINEL = (0xFF, 0xFF, 0)

# ------------------------------------------------------------- starfield ---
# THE SKY IS NOT EMPTY.  Above each profile's surface, a LANDER level leaves a
# dozen rows of blank tile and a DESCENT level about ninety -- and a ship
# falling through unmarked space has nothing to measure itself against.  On a
# 160x144 screen the ship is the only thing in the sky that moves, so a descent
# at a steady pace reads as hovering and the ground arrives by surprise.  A star
# in some of the sky cells is the reference, and it is nearly free: main.c is
# writing every one of those cells anyway.
#
# IT IS A WORLD PATTERN, not a screen one -- star_field[world row & 15][col].
# LANDER's camera is pinned, so its stars stand still and the SHIP moves past
# them; DESCENT's scrolls, so they travel with the terrain.  Same table, same
# row_blit() line, both modes.  Indexing by world row is also what lets DESCENT
# re-blit a streamed row and get the SAME stars back -- a screen-space pattern
# would reshuffle the sky every time the camera moved.
#
# ONE FIELD FOR ALL TWENTY-FOUR LEVELS, deliberately.  It is a motion reference
# and not a layout, so a level that re-shuffled it would be spending 144 bytes
# on a difference the player cannot land on.
#
# STAR_ROWS is a power of two so main.c's index is an AND rather than a %.
STAR_ROWS = 16              # the pattern's period in world rows
STAR_TILES = 4              # mkgfx.py draws T_STAR0..3; the field says WHICH
# 1 sky cell in 12 carries one.  NOT a taste call: this number is half the frame
# budget for p13_descent's free-fall tick.  Measured, on the compact list main.c
# actually reads -- 8 (41 stars) fails p13 at 127 emulated frames, 12 (28) and
# 16 (20) both read the 126 that a blank sky reads.  Changing it means
# re-running `make probe`, not just `make level`.
STAR_ODDS = 12

# The field is emitted in TILE ID SPACE -- 0 for sky, 3..6 for the four stars --
# and not as 0..4 indices into mkgfx.py's tiles, even though the two generators
# otherwise keep their numbering to themselves.  It is worth the coupling:
# main.c's row_blit() runs this lookup once per sky cell on every streamed row,
# and the mapping step is a SECOND table read per cell.  Measured through
# probe.p13_descent's tick-rate check, a free-falling DESCENT life kept 126 of
# 128 emulated frames with the field holding tile ids, against 128 of 170 with
# it holding indices -- one extra read a cell was most of a 25% slowdown.  These
# two constants are the whole of the coupling, and mkgfx.py asserts its own
# numbering against them.
STAR_BLANK = 0              # T_BLANK
STAR_TILE0 = 3              # T_STAR0


def tri(period, col):
    """Triangle wave 0..period//2, periodic in `period`."""
    a = col % period
    if a >= period // 2:
        a = period - 1 - a
    return a


def kernel(shape, col):
    return KERNELS[shape][0](col % WORLD_COLS)


# ------------------------------------------------------------- the levels ---
# THE SET DESIGN.  One entry per level, in chain order, and the order IS the
# progression: a landing on one walks the player to the next.
#
#   shape/amp  the silhouette (KERNELS above) and whether it is scaled
#   base       the depth: the row the kernel is measured from
#   pads       (name, col0, col1, multiplier) -- 1 to 3 of them, in columns
#              1..18, non-overlapping, each a flat run
#   pad_rows   multiplier -> the surface row that pad sits at
#   spawn      (x, y) in px, the ship's top-left, and it MUST be over a pad.
#              (col * 8 - 4, 16) centres the ship on tile column `col` at the
#              top of the play area, which is what the x2 pad has always used.
#   on_screen  which half of the size assertion applies
#
# LEVEL 1 OF EACH CHAIN IS THE WORLD THIS GAME HAS ALWAYS BOOTED INTO -- the
# `ripple` kernel at base 12 and base 96 -- so its arrays come back byte for
# byte and every test and check written against the old two-profile game is
# still a check on this one.  That is the constraint the whole table is built
# around, and self_check() below is what enforces the rest of it.
def level(chain, n, shape, amp, base, pads, pad_rows, spawn, on_screen):
    sym = "terrain_%s" % chain.lower() + ("" if n == 1 else "_l%d" % n)
    return dict(chain=chain, n=n, sym=sym, shape=shape, amp=amp, base=base,
                pads=pads, pad_rows=pad_rows, spawn=spawn,
                on_screen=on_screen)


LEVELS = [
    # ---- LANDER: one screen, wrapping.  Pads live on rows 8..15 so the fall
    # is a fall, and never on 16..17, which the status bar covers.
    level("LANDER", 1,  "ripple", 1, 12, [("LOW", 4, 7, 1), ("HIGH", 13, 14, 2)],
          {1: 15, 2: 12}, (108, 16), True),
    level("LANDER", 2,  "roller", 1, 11, [("LOW", 1, 3, 1), ("HIGH", 15, 17, 2)],
          {1: 13, 2: 13}, (124, 16), True),
    level("LANDER", 3,  "basin",  1, 11, [("LOW", 2, 4, 1), ("HIGH", 16, 18, 2)],
          {1: 13, 2: 11}, (132, 16), True),
    level("LANDER", 4,  "mound",  1, 15, [("LOW", 5, 7, 1), ("HIGH", 13, 15, 2)],
          {1: 12, 2: 12}, (108, 16), True),
    level("LANDER", 5,  "chop",   1, 12, [("LOW", 5, 7, 1), ("HIGH", 12, 13, 2)],
          {1: 13, 2: 14}, (92, 16),  True),
    level("LANDER", 6,  "roller", 2, 7,  [("LOW", 2, 4, 1), ("HIGH", 13, 15, 2)],
          {1: 13, 2: 13}, (108, 16), True),
    level("LANDER", 7,  "basin",  2, 7,  [("LOW", 1, 3, 1), ("HIGH", 14, 16, 2)],
          {1: 9, 2: 11}, (116, 16),  True),
    level("LANDER", 8,  "mound",  2, 15, [("LOW", 4, 6, 1), ("HIGH", 13, 15, 2)],
          {1: 11, 2: 9}, (108, 16),  True),
    level("LANDER", 9,  "ripple", 2, 6,  [("LOW", 4, 6, 1), ("HIGH", 14, 16, 2)],
          {1: 10, 2: 8}, (116, 16),  True),
    level("LANDER", 10, "chop",   2, 6,  [("LOW", 1, 3, 1), ("HIGH", 12, 14, 2)],
          {1: 10, 2: 10}, (100, 16), True),
    level("LANDER", 11, "roller", 1, 13, [("LOW", 3, 5, 1), ("HIGH", 14, 16, 2)],
          {1: 15, 2: 15}, (116, 16), True),
    level("LANDER", 12, "chop",   1, 13, [("LOW", 6, 8, 1), ("HIGH", 13, 14, 2)],
          {1: 14, 2: 15}, (100, 16), True),

    # ---- DESCENT: deeper than a BG map, so the camera follows.  Every one is
    # more than MAP_TILES down, and no pad is deeper than level 1's own 100 --
    # see MAX_DROP_PX.
    level("DESCENT", 1,  "ripple", 1, 96,  [("LOW", 4, 7, 1), ("HIGH", 13, 14, 2)],
          {1: 100, 2: 97}, (108, 16), False),
    level("DESCENT", 2,  "roller", 1, 52,  [("LOW", 1, 3, 1), ("HIGH", 15, 17, 2)],
          {1: 54, 2: 54}, (124, 16), False),
    level("DESCENT", 3,  "basin",  1, 37,  [("LOW", 2, 4, 1), ("HIGH", 16, 18, 2)],
          {1: 39, 2: 37}, (132, 16), False),
    level("DESCENT", 4,  "mound",  1, 44,  [("LOW", 5, 7, 1), ("HIGH", 13, 15, 2)],
          {1: 41, 2: 41}, (108, 16), False),
    level("DESCENT", 5,  "chop",   1, 61,  [("LOW", 6, 8, 1), ("HIGH", 12, 13, 2)],
          {1: 62, 2: 63}, (92, 16),  False),
    level("DESCENT", 6,  "roller", 2, 68,  [("LOW", 3, 5, 1), ("HIGH", 13, 15, 2)],
          {1: 76, 2: 74}, (108, 16), False),
    level("DESCENT", 7,  "basin",  2, 55,  [("LOW", 1, 3, 1), ("HIGH", 14, 16, 2)],
          {1: 57, 2: 59}, (116, 16), False),
    level("DESCENT", 8,  "mound",  2, 72,  [("LOW", 4, 6, 1), ("HIGH", 13, 15, 2)],
          {1: 68, 2: 66}, (108, 16), False),
    level("DESCENT", 9,  "ripple", 2, 82,  [("LOW", 4, 6, 1), ("HIGH", 14, 16, 2)],
          {1: 86, 2: 84}, (116, 16), False),
    level("DESCENT", 10, "chop",   2, 49,  [("LOW", 1, 3, 1), ("HIGH", 12, 14, 2)],
          {1: 51, 2: 53}, (100, 16), False),
    level("DESCENT", 11, "roller", 1, 88,  [("LOW", 3, 5, 1), ("HIGH", 14, 16, 2)],
          {1: 92, 2: 92}, (116, 16), False),
    level("DESCENT", 12, "mound",  1, 100, [("LOW", 5, 7, 1), ("HIGH", 13, 15, 2)],
          {1: 97, 2: 97}, (108, 16), False),
]


# EVERY LEVEL'S TABLE IS AS WIDE AS THE WIDEST LEVEL NEEDS, and no wider.  This
# is DERIVED from the table above rather than written down, and the reason is a
# measurement rather than tidiness: PAD_COUNT is the loop bound in sim.h's
# pad_mult(), which runs once a tick out of ship_step() and once a streamed row
# out of row_blit(), and probe.p13_descent holds the DESCENT tick to ONE
# EMULATED FRAME with exactly one frame of slack over 330.  A slot that no
# level uses is a third indirect load per call bought for nothing.  The day a
# level needs three pads this becomes 3 by itself, and PAD_SENTINEL above is
# what pads the shorter tables out.
PAD_COUNT = max(len(lvl["pads"]) for lvl in LEVELS)


def build(lvl):
    """A level's 20 surface rows, then its pads carved flat into them.

    The carve is the whole of what a pad is: every column in a span is set to
    the ONE row its multiplier names, which is what makes the run the ship lands
    on flat by construction rather than by inspection."""
    terrain = [lvl["base"] + lvl["amp"] * kernel(lvl["shape"], c)
               for c in range(WORLD_COLS)]
    for _name, col0, col1, mult in lvl["pads"]:
        for c in range(col0, col1 + 1):
            terrain[c] = lvl["pad_rows"][mult]
    return terrain


def self_check(lvl, terrain):
    """Everything the renderer, the collision and a player are entitled to
    assume about a level.

    Run for EVERY level before the file is written.  A generator that emits a
    height the type cannot hold, a pad that is not actually flat, or a level
    whose ship spawns over bare ground has to fail HERE -- at `make level` --
    and not as a sprite standing in the ground, or a life that cannot be won, on
    hardware."""
    name = "%s L%d" % (lvl["chain"], lvl["n"])
    shape = lvl["shape"]
    base = lvl["base"]

    assert shape in KERNELS, "%s: no such shape as %r" % (name, shape)
    assert lvl["amp"] in (1, 2), \
        "%s: amp is %r; the vocabulary is 1 or 2" % (name, lvl["amp"])
    assert len(terrain) == WORLD_COLS, \
        "%s: expected %d columns, got %d" % (name, WORLD_COLS, len(terrain))

    # 255, not 17: this is the ceiling the TYPE has to carry, and it is the
    # whole reason terrain[] is not a screen-sized array.
    assert 0 <= min(terrain) and max(terrain) <= TERRAIN_MAX_TILES, \
        "%s: heights must fit TERRAIN_MAX_TILES (%d), got %d..%d" \
        % (name, TERRAIN_MAX_TILES, min(terrain), max(terrain))

    # The size assertion, and it has two halves because the two chains are meant
    # to sit on opposite sides of it.
    if lvl["on_screen"]:
        assert max(terrain) < VIEW_TILES_H, \
            "%s's profile must fit on screen, got a surface row of %d" \
            % (name, max(terrain))
    else:
        assert max(terrain) > MAP_TILES, \
            "%s's profile is %d tiles deep, which fits inside one BG map (%d) " \
            "-- a descent that fits on one screen is a relabelled LANDER, and " \
            "a blit of it would never meet the truncation the window exists " \
            "to avoid" % (name, max(terrain), MAP_TILES)

    # The seam.  Every period the selected kernel is built from must divide
    # WORLD_COLS (so `% period` is the same function either side of column 0),
    # no pad may sit on a seam column (or carving it would be the one thing the
    # periodicity misses), and the step across the seam has to be walkable.
    periods = KERNELS[shape][1]
    for period in periods:
        assert WORLD_COLS % period == 0, \
            "%s: %s's period %d does not divide WORLD_COLS (%d): the seam " \
            "would be visible" % (name, shape, period, WORLD_COLS)
    for c in range(WORLD_COLS):
        assert kernel(shape, c) == kernel(shape, c + WORLD_COLS), \
            "%s: %s is not periodic at column %d" % (name, shape, c)

    for pname, col0, col1, mult in lvl["pads"]:
        assert mult in lvl["pad_rows"], \
            "%s: pad %s has no pad_rows entry for x%d" % (name, pname, mult)
        assert 1 <= col0 <= col1 <= WORLD_COLS - 2, \
            "%s: pad %s (%d..%d) touches a seam column or is inverted" \
            % (name, pname, col0, col1)

    # Each named pad is a flat run of equal heights -- the surface row the ship
    # lands on, the same for every column in the span, and the one this level's
    # pad_rows says.
    for pname, col0, col1, mult in lvl["pads"]:
        run = terrain[col0:col1 + 1]
        assert len(set(run)) == 1, \
            "%s: pad %s is not flat: %r" % (name, pname, run)
        assert run[0] == lvl["pad_rows"][mult], \
            "%s: pad %s sits at row %d, not the x%d row (%d)" \
            % (name, pname, run[0], mult, lvl["pad_rows"][mult])

    # Pads do not overlap: two multipliers on one column is a scoring ambiguity
    # nothing downstream could resolve.
    seen = set()
    for pname, col0, col1, _mult in lvl["pads"]:
        for c in range(col0, col1 + 1):
            assert c not in seen, \
                "%s: column %d is claimed by two pads (%s)" % (name, c, pname)
            seen.add(c)

    # A pad is a plateau, not a cliff, and the seam is a step like any other.
    # Measured against the KERNEL and not the carved terrain: the question is
    # whether the ground the pad was cut into meets its edge walkably, and
    # comparing the pad row to the pad row next to it would answer nothing.
    def raw(c):
        return base + lvl["amp"] * kernel(shape, c % WORLD_COLS)

    for pname, col0, col1, mult in lvl["pads"]:
        row = terrain[col0]
        if col0 > 0:
            assert abs(row - raw(col0 - 1)) <= PAD_MAX_STEP, \
                "%s: pad %s steps %d tiles up onto column %d" \
                % (name, pname, abs(row - raw(col0 - 1)), col0 - 1)
        if col1 < WORLD_COLS - 1:
            assert abs(row - raw(col1 + 1)) <= PAD_MAX_STEP, \
                "%s: pad %s steps %d tiles off column %d" \
                % (name, pname, abs(row - raw(col1 + 1)), col1 + 1)
    assert abs(raw(0) - raw(WORLD_COLS - 1)) <= SEAM_MAX_STEP, \
        "%s: the wrap seam steps %d tiles" \
        % (name, abs(raw(0) - raw(WORLD_COLS - 1)))

    # ---- what makes a level a LEVEL rather than a shape -------------------
    # The spawn is over a pad, above it, and no further up than the drop bound
    # allows.  These are the checks a hand-tuned recipe fails on, and they are
    # the reason the table above can be adjusted without flying every entry.
    sx, sy = lvl["spawn"]
    col = (sx + 4) >> 3                      # sim.h's ship_col(), SHIP_W 8
    assert 0 <= sx <= 255 - 8 and 0 <= sy <= 255 - 8, \
        "%s: spawn (%d,%d) does not fit the level table's byte fields" \
        % (name, sx, sy)
    assert any(c0 <= col <= c1 for _n, c0, c1, _m in lvl["pads"]), \
        "%s: the ship spawns over column %d, which is bare ground -- a level " \
        "with no pad under the spawn opens on a life that cannot be won" \
        % (name, col)

    underside = sy + 8                       # SHIP_H
    # The fall is measured to the DEEPEST pad, whether or not the ship starts
    # over it: the drop bound is about what the level can demand of a tank, and
    # a player who flies across to the far pad is the one it has to cover.
    drop = max(lvl["pad_rows"][mult] * 8 - underside
               for _n, _c0, _c1, mult in lvl["pads"])
    # ...and the ship's OWN pad is the one that must have air under it.
    aimed = [lvl["pad_rows"][mult] * 8 - underside
             for _n, c0, c1, mult in lvl["pads"] if c0 <= col <= c1]
    assert min(aimed) >= MIN_AIR_GAP_PX, \
        "%s: the ship spawns %d px above its own pad -- it opens the level " \
        "already touching down" % (name, min(aimed))
    assert drop >= MIN_DROP_PX, \
        "%s: the greatest fall is %d px -- too short to be a landing" \
        % (name, drop)
    assert drop <= MAX_DROP_PX, \
        "%s: a fall of %d px is deeper than the %d px this game is known to be " \
        "flyable on one tank (DESCENT L1's own drop); raise MAX_DROP_PX only " \
        "with a flown level behind it" % (name, drop, MAX_DROP_PX)

    # A LANDER pad under the status bar is a pad nobody can see.
    if lvl["on_screen"]:
        for _n, _c0, _c1, mult in lvl["pads"]:
            assert lvl["pad_rows"][mult] <= LANDER_PAD_MAX_ROW, \
                "%s: a pad at row %d is under the status bar (rows %d..%d)" \
                % (name, lvl["pad_rows"][mult], LANDER_PAD_MAX_ROW + 1,
                   VIEW_TILES_H - 1)


def build_stars():
    """The star field, from a fixed seed, so `make level` is reproducible.

    An LCG and NOT a hash of (row, col), which is the obvious way to write this
    and the wrong one: every shift-and-XOR hash is linear over GF(2), so the
    cells it selects out of a small range form a lattice -- the stars come out
    on a regular diagonal grid, which is the one thing a starfield must not
    look like.  Breaking that needs a non-linear step, and a multiply is the
    cheapest one there is.

    The terrain does NOT get the same treatment.  A seeded layout would be just
    as reproducible and would be UNCONTROLLABLE: it cannot promise a spawn over
    a pad, a walkable shoulder or a shut seam, which is exactly what self_check()
    above exists to promise.  A level is tuned by hand; only the sky is drawn."""
    state = 0x5EED
    field = []
    for _r in range(STAR_ROWS):
        row = []
        for _c in range(WORLD_COLS):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            # STAR_ODDS is the SPARSITY, not the hit rate: one draw in
            # STAR_ODDS cells gets a star and the rest stay sky, which is the
            # way round it is easy to write backwards -- the check below is
            # what caught it the first time.
            if (state >> 16) % STAR_ODDS:
                row.append(STAR_BLANK)
            else:
                row.append(STAR_TILE0 + (state >> 8) % STAR_TILES)
        field.append(row)
    return field


STAR_FIELD = build_stars()
STARS = sum(1 for r in STAR_FIELD for v in r if v)
STAR_CELLS = STAR_ROWS * WORLD_COLS

# The field's self-checks, and the shape of the table is the one that is easy
# to get wrong in silence: a row that is not WORLD_COLS wide wraps the sky at
# the wrong column, and a value past STAR_TILES indexes off the end of
# mkgfx.py's star tiles into whatever tile id happens to be next.
assert len(STAR_FIELD) == STAR_ROWS, "the field is not STAR_ROWS rows"
assert all(len(r) == WORLD_COLS for r in STAR_FIELD), \
    "a star row is not WORLD_COLS wide -- the sky would wrap at the wrong column"
assert all(v in ({STAR_BLANK} | set(range(STAR_TILE0, STAR_TILE0 + STAR_TILES)))
           for r in STAR_FIELD for v in r), \
    "a cell is neither blank nor one of the %d star tile ids" % STAR_TILES
# The SAME field again as a compact per-row list of `column, tile` pairs,
# terminated by STAR_END.  This is the form main.c reads, and the reason is a
# measurement rather than a preference: main.c's row_blit() runs once per
# streamed row per tick, and probe.p13_descent's free-fall tick sits on exactly
# the last frame the check allows -- 126 emulated frames advancing the tick
# counter by 125, with the sky simply blank.  Handing that loop a WORLD_COLS-
# wide row to copy cost it that frame and the check went red.
#
# The compact list is the necessary half of the answer and not the whole of it:
# STAR_ODDS is the other half and it is measured too.  At 8 (41 stars) the loop
# is still 2-3 cells a row too wide and p13 fails at 127 frames; at 12 (28) it
# reads 126/125, the same number the sky with no stars at all reads -- the star
# work is inside the tick again.  So the sparsity IS the frame budget here, and
# moving STAR_ODDS down without re-running p13 is how this gets broken.
#
# The wide field above is still what the checks grade -- the list is derived
# from it, never the other way, so the density assertion still covers what
# ships.
STAR_END = 0xFF                 # column 0..19 can never collide with it
STAR_LIST = [[[c, v] for c, v in enumerate(_row) if v] for _row in STAR_FIELD]
STAR_STRIDE = 2 * max(len(r) for r in STAR_LIST) + 1
# A row with no stars is legal -- row 4 is one -- and is just its terminator.
# The floor only guards the degenerate table where EVERY row is empty, which
# would leave a stride of 1 and a table with no room to say anything.
assert STAR_STRIDE >= 3, "every star row is empty -- the table says nothing"
assert all(len(r) <= (STAR_STRIDE - 1) // 2 for r in STAR_LIST), \
    "a star row is wider than STAR_STRIDE -- the pairs would run off the end"
assert sum(len(r) for r in STAR_LIST) == STARS, \
    "the compact list and the field disagree about how many stars there are"

assert 0.05 <= STARS / float(STAR_CELLS) <= 0.25, (
    "the sky came out %.0f%% stars; a generator that emitted none of them, or "
    "all of them, would still build and still pass everything else"
    % (100.0 * STARS / STAR_CELLS))


# ------------------------------------------------------------- generate ----
built = [(lvl, build(lvl)) for lvl in LEVELS]
for _l, _t in built:
    self_check(_l, _t)

# Distinctness, per chain: the probe's "the world really changed" assertion
# compares the profile the ROM is pointed at against the one it was pointed at
# a tick earlier, and two levels that came out the same shape would make that
# assertion pass without the level having moved.
for _chain in ("LANDER", "DESCENT"):
    _mine = [tuple(t) for l, t in built if l["chain"] == _chain]
    assert len(set(_mine)) == len(_mine), \
        "two %s levels have identical profiles -- the chain has a duplicate " \
        "and a landing on one could not be told from a landing on the other" \
        % _chain

CHAIN_NAMES = ("LANDER", "DESCENT")
for _c in CHAIN_NAMES:
    assert [l["n"] for l, _t in built if l["chain"] == _c] == \
        list(range(1, 13)), "%s's levels are not numbered 1..12" % _c

lines = [
    "/* Generated by mklevel.py - do not edit.  Run `make level` to regenerate. */",
    "#ifndef TERRAIN_H",
    "#define TERRAIN_H",
    "",
    "#include <stdint.h>",
    "",
    "/* Every world is 160 px / 8 px per tile WIDE, and none is one screen wide",
    " * plus a bit: 160 is NOT a power of two, so the wrap is two compares",
    " * (x < 0 -> x += 160; x >= 160 -> x -= 160) and never an `& WORLD_MASK`:",
    " * masking would wrap at 256 and put the seam off-screen. */",
    "#define WORLD_COLS %d" % WORLD_COLS,
    "",
    "/* The ceiling on a surface row, in 8 px TILE units -- the unit mkgfx.py",
    " * draws the terrain tiles in.  NOT pixels, and NOT the screen: the LANDER",
    " * levels stop at row %d and the DESCENT ones reach row %d, and the type"
    % (max(max(t) for l, t in built if l["chain"] == "LANDER"),
       max(max(t) for l, t in built if l["chain"] == "DESCENT")),
    " * has to hold both without a refactor. */",
    "#define TERRAIN_MAX_TILES %d" % TERRAIN_MAX_TILES,
]


def emit_profile(lines, lvl, terrain):
    lines.append("")
    lines.append("/* %s L%d -- %s x%d from base %d.  Surface row (tile units) at"
                 % (lvl["chain"], lvl["n"], lvl["shape"], lvl["amp"], lvl["base"]))
    lines.append(" * each world tile column.  Periodic in WORLD_COLS -- the period")
    lines.append(" * (%s) divides %d, so the wrap seam is invisible by construction,"
                 % (", ".join(str(p) for p in KERNELS[lvl["shape"]][1]), WORLD_COLS))
    lines.append(" * and the kernel is 0 at both seam columns whatever the base is.")
    lines.append(" * Rows %d..%d.  The pads are carved flat into it at %s. */"
                 % (min(terrain), max(terrain),
                    ", ".join("x%d@%d (cols %d..%d)"
                              % (m, lvl["pad_rows"][m], a, b)
                              for _n, a, b, m in lvl["pads"])))
    if not lvl["on_screen"]:
        lines.append("/* TALLER THAN A BG MAP (%d rows) and taller than the view (%d):"
                     % (MAP_TILES, VIEW_TILES_H))
        lines.append(" * there is no blit that puts these rows on one map, which is why")
        lines.append(" * main.c draws a WINDOW of it rather than the whole profile. */")
    lines.append("static const uint8_t %s[WORLD_COLS] = {" % lvl["sym"])
    for i in range(0, WORLD_COLS, 10):
        lines.append("    " + ", ".join("%3d" % v for v in terrain[i:i + 10]) + ",")
    lines.append("};")


for _l, _t in built:
    emit_profile(lines, _l, _t)

lines += [
    "",
    "/* THE ACTIVE PROFILE, and the one symbol in this header that is not a",
    " * constant.  sim.h's ship_step() reads terrain[col] to find the ground",
    " * under the ship and tools/probe.py reads terrain out of the linker map, so",
    " * all %d worlds share THIS name rather than one array being renamed per"
    % len(built),
    " * level -- a second name would break the collision call and the probe's",
    " * address lookup together, and the mismatch would look like a physics bug.",
    " * main.c assigns it out of the Level table below; everything else reads",
    " * through it. */",
    "static const uint8_t *terrain = terrain_lander;",
    "",
    "/* One landing site: col0/col1 are inclusive world tile columns and mult is",
    " * the score multiplier for a landing that stays on the pad.  The span is",
    " * flat -- mklevel.py asserts it for every level -- so terrain[col0..col1] is",
    " * one row, at whatever depth that level put it. */",
    "typedef struct {",
    "    uint8_t col0;",
    "    uint8_t col1;",
    "    uint8_t mult;",
    "} Pad;",
    "",
    "/* A level declares one to three pads and the generator pads the table out",
    " * to PAD_COUNT with a sentinel whose col0 is 255.  No column of a %d-wide"
    % WORLD_COLS,
    " * world can satisfy `col <= col1` for it, so sim.h's pad_mult() walks past",
    " * it and answers 0 exactly as it does for bare ground -- which is what lets",
    " * this stay a compile-time bound on the collision hot path. */",
    "#define PAD_COUNT %d" % PAD_COUNT,
    "",
    "/* Level 1's two slots, named because tests/test_sim.c indexes them.  Level 1",
    " * of each chain is the world this game has always booted into, and slot 0 is",
    " * its x1 pad and slot 1 its x2 pad. */",
    "#define PAD_LOW  0",
    "#define PAD_HIGH 1",
]

for _l, _t in built:
    lines.append("")
    lines.append("static const Pad pads_%s_l%d[PAD_COUNT] = {"
                 % (_l["chain"].lower(), _l["n"]))
    _slots = [(_n, a, b, m) for _n, a, b, m in _l["pads"]]
    _slots += [("--", PAD_SENTINEL[0], PAD_SENTINEL[1], PAD_SENTINEL[2])] * \
        (PAD_COUNT - len(_slots))
    for _n, _a, _b, _m in _slots:
        lines.append("    { %3d, %3d, %d },  /* %s%s */"
                     % (_a, _b, _m, _n,
                        "" if _n == "--" else " @row %d" % _l["pad_rows"][_m]))
    lines.append("};")

lines += [
    "",
    "/* THE ACTIVE PAD TABLE, the second symbol that is not a constant, and a",
    " * pointer for exactly the reason `terrain` above is one: sim.h's pad_mult()",
    " * and tools/probe.py both have to reach the CURRENT level's pads through one",
    " * name.  main.c assigns it beside `terrain`, out of the same Level row. */",
    "static const Pad *pads = pads_lander_l1;",
    "",
    "/* A LEVEL: which profile, which pads, and where the ship opens in it.  The",
    " * spawn is per level rather than a constant in main.c because it is part of",
    " * the design -- it has to be over a pad, and mklevel.py rejects a level where",
    " * it is not.  x is the ship's left edge in px and y its top edge; ship_init()",
    " * writes them straight into the state. */",
    "typedef struct {",
    "    const uint8_t *profile;",
    "    const Pad     *pads;",
    "    uint8_t        spawn_x;",
    "    uint8_t        spawn_y;",
    "} Level;",
    "",
]

for _c in CHAIN_NAMES:
    _rows = [(l, t) for l, t in built if l["chain"] == _c]
    lines.append("#define %s_LEVELS %d" % (_c, len(_rows)))
for _c in CHAIN_NAMES:
    _rows = [(l, t) for l, t in built if l["chain"] == _c]
    lines.append("")
    lines.append("/* The %s chain, in the order a landing walks it. */" % _c)
    lines.append("static const Level levels_%s[%s_LEVELS] = {"
                 % (_c.lower(), _c))
    for _l, _t in _rows:
        lines.append("    { %s, pads_%s_l%d, %3d, %2d },  /* L%d */"
                     % (_l["sym"], _l["chain"].lower(), _l["n"],
                        _l["spawn"][0], _l["spawn"][1], _l["n"]))
    lines.append("};")

lines += [
    "",
    "/* THE SKY.  main.c's row_blit() indexes this with",
    " * `world row & (STAR_ROWS - 1)`, so row N here is the sky at world rows",
    " * N, N + %d, N + %d ... and the pattern REPEATS every %d rows -- which is"
    % (STAR_ROWS, 2 * STAR_ROWS, STAR_ROWS),
    " * what keeps the list %d bytes instead of one row per row of world, and"
    % (STAR_ROWS * STAR_STRIDE),
    " * lets it be a pure function of a WORLD row.  DESCENT streams its rows in",
    " * whatever order the camera asks for and re-blits them as the ring wraps,",
    " * so a table the ring had to carry would come back shuffled.",
    " *",
    " * ONE FIELD FOR ALL %d LEVELS, because it is a motion reference and not a"
    % len(built),
    " * layout: nothing lands on a star, so a level that reshuffled the sky would",
    " * be spending bytes on a difference the player cannot fly against.",
    " *",
    " * THE LIST IS `column, tile` PAIRS, terminated by STAR_END (%d), and not"
    % STAR_END,
    " * a WORLD_COLS-wide row: row_blit() runs once per streamed row per tick",
    " * and probe.p13_descent's free-fall tick sits on the last frame it is",
    " * allowed, so the loop copies the %d cells that ARE stars and not the %d"
    % (STARS, STAR_CELLS),
    " * that are not.  Row N is padded out with STAR_END after its pairs and is",
    " * always read from the start, so the padding costs nothing.",
    " *",
    " * THE VALUES ARE TILE IDS, not indices: %d..%d are mkgfx.py's four stars"
    % (STAR_TILE0, STAR_TILE0 + STAR_TILES - 1),
    " * (two of them drawn dim, so the field has depth) and T_BLANK (%d) is the"
    % STAR_BLANK,
    " * sky the loop already wrote.  %d of the %d cells carry one.  mkgfx.py"
    % (STARS, STAR_CELLS),
    " * asserts its own ids against those.",
    " *",
    " * NOT a hash of (row, col) -- a shift-and-XOR hash is linear over GF(2)",
    " * and the cells it picks land on a regular diagonal lattice.  It is an LCG",
    " * in tools/mklevel.py from a fixed seed instead, and `make level`",
    " * reproduces it byte for byte.  See that function for the argument. */",
    "#define STAR_ROWS %d" % STAR_ROWS,
    "#define STAR_TILES %d" % STAR_TILES,
    "#define STAR_END %d" % STAR_END,
    "#define STAR_STRIDE %d" % STAR_STRIDE,
    "",
    "static const uint8_t star_cells[STAR_ROWS][STAR_STRIDE] = {",
]
for _row in STAR_LIST:
    _flat = [b for _c, _t in _row for b in (_c, _t)]
    _flat += [STAR_END] * (STAR_STRIDE - len(_flat))
    lines.append("    { " + ", ".join("%d" % v for v in _flat) + " },")
lines += ["};", "", "#endif", ""]

with open("terrain.h", "w") as f:
    f.write("\n".join(lines))

print("star_cells: %d rows x %d, %d stars, list %d bytes of %d"
      % (STAR_ROWS, STAR_STRIDE, STARS, STAR_ROWS * STAR_STRIDE, STAR_CELLS))

for p, t in built:
    print("%-12s %s: rows %d..%d, pads %s"
          % ("%s L%d" % (p["chain"], p["n"]), p["sym"], min(t), max(t),
             ", ".join("%s(%d..%d x%d@%d)" % (n, a, b, m, p["pad_rows"][m])
                       for n, a, b, m in p["pads"])))
print("terrain.h: %d columns, %d levels over %d chains, one `terrain` pointer"
      % (WORLD_COLS, len(built), len(CHAIN_NAMES)))
print("star_field: %dx%d, %d stars (%.0f%% of sky cells)"
      % (STAR_ROWS, WORLD_COLS, STARS, 100.0 * STARS / STAR_CELLS))
