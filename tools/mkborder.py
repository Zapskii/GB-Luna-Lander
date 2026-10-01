#!/usr/bin/env python3
"""Generate art/border_sgb.png -- the Super Game Boy border for GB-LUNA-LANDEER.

The border is a 256x224 image; the 160x144 game window (x 48..207, y 40..183)
stays transparent, because that is where the SGB puts the Game Boy's screen.
`make border` then turns the PNG into border_data.c with png2asset.

Modelled on ../GB-Checkers/tools/mkborder.py, which is the family's reference:
drawn rather than hand-painted, lettering taken from the game's OWN font so the
border is the same hand as the title screen, and colours capped at 16 so the
whole thing packs into one SGB palette.

Two differences from that one.  The motif is this game's: a rocket either side
of the screen standing on the lunar surface the game lands on, a porthole rim
around the window (the screen is the view out of the ship), and the two mode
names along the bottom.  And the starfield is laid out on the 8-pixel grid on
purpose: a star is BAKED INTO ITS TILE, so five tile patterns give a sky of
scattered stars, where stars placed freely would be a new tile each and blow the
budget on their own.

    tools/mkborder.py && make border && make
"""
import random
import re

from PIL import Image, ImageDraw

OUT_PNG = "art/border_sgb.png"
MKGFX = "mkgfx.py"

W, H = 256, 224
WIN = (48, 40, 208, 184)                # game window: x0, y0, x1, y1 (exclusive)

# The palette: fifteen opaque colours plus the window's transparent slot, which
# is the sixteen one SGB border palette holds.  Space is nearly black and does
# double duty as every outline -- an outline colour of its own would be the
# sixteenth and there is not one to spare.
SPACE = (6, 8, 26, 255)                 # deep space, and every outline
SPACE_L = (16, 20, 50, 255)             # ...lighter, behind the rockets
STAR = (238, 242, 255, 255)             # the bright end of the starfield
STAR_D = (156, 170, 210, 255)           # ...and the dim end
HULL = (226, 232, 244, 255)             # the rocket's body
HULL_D = (138, 148, 170, 255)           # ...its shading and panel lines
RED = (214, 74, 58, 255)                # nose cone and fins
RED_D = (138, 40, 32, 255)              # ...shaded side
GOLD = (234, 192, 74, 255)              # the title
FLAME = (252, 206, 86, 255)             # exhaust, hot core
FLAME_D = (228, 116, 38, 255)           # ...its outer plume
GREY = (122, 120, 112, 255)             # lunar regolith
GREY_L = (170, 166, 152, 255)           # ...its lit surface
RIM = (98, 106, 130, 255)               # the porthole rim's metal
BYLINE = (152, 202, 222, 255)           # the byline: a caption, not a title

TITLE, TITLE_SCALE = "LUNA LANDEER", 2
CREDIT, CREDIT_SCALE = "BY ZAPSKI", 1
MODES = "LANDER  DESCENT"               # the two worlds, along the bottom

GROUND = 208                            # the lunar surface line, on the grid
CELL = 6                                # pen advance at 1x: 5px ink + 1px gap
GLYPH = 5

# 32 wide, centred on the boundary between its two middle tile columns, so a row
# of the rocket is two tile patterns rather than four.  Both rockets are then
# drawn identically and share every one of those patterns; only the map points
# at them twice.
ROCKET_W, ROCKET_Y, ROCKET_H = 32, 8, 200


def read_font():
    """The game's own 5x7 glyphs, straight out of mkgfx.py.

    FONT maps a character to seven 5-bit rows.  Parsing rather than copying
    means the border spells LUNA LANDEER in exactly the letters the HUD does,
    and follows if the font ever grows.
    """
    src = open(MKGFX).read()
    body = re.search(r'^FONT = \{(.*?)^\}', src, re.S | re.M).group(1)
    return {ch: rows.split("|")
            for ch, rows in re.findall(r"'(\w)': \"([^\"]*)\"", body)}


def text_w(s, scale):
    return len(s) * CELL * scale - scale


def draw_text(d, font, x, y, s, scale, col):
    for ch in s:
        if ch != " ":
            for r, row in enumerate(font[ch]):
                for c, bit in enumerate(row):
                    if bit == "#":
                        d.rectangle([x + c * scale, y + r * scale,
                                     x + c * scale + scale - 1,
                                     y + r * scale + scale - 1], fill=col)
        x += CELL * scale


def text(d, font, y, s, scale, col):
    """A centred line, on the 8px grid, over a cleared strip: the starfield is
    laid down first and a glyph over a star is unreadable."""
    x = (W - text_w(s, scale)) // 2
    d.rectangle([x - 4, y - 2, x + text_w(s, scale) + 3,
                 y + 7 * scale + 1], fill=SPACE)
    draw_text(d, font, x, y, s, scale, col)


def starfield(d):
    """Five patterns -- four stars and the empty sky -- tiled over everything
    outside the window.  The star's position is part of the tile, so the sky
    gets its scatter from WHICH pattern each cell holds."""
    rng = random.Random(7)               # seeded: the art is regenerated, not re-rolled
    stars = [((1, 1), STAR), ((1, 1), STAR), ((5, 2), STAR_D), ((2, 6), STAR_D)]
    for cy in range(0, H, 8):
        for cx in range(0, W, 8):
            if not (WIN[0] - 8 < cx < WIN[2] and WIN[1] - 8 < cy < WIN[3]):
                continue
            if rng.random() < 0.45:
                (sx, sy), col = rng.choice(stars)
                d.rectangle([cx + sx, cy + sy, cx + sx + 1, cy + sy + 1], fill=col)


def rim(d):
    """The porthole rim: one 8px band around the window, so the screen reads as
    the view out of the ship rather than a hole in the picture."""
    x0, y0, x1, y1 = WIN[0] - 8, WIN[1] - 8, WIN[2] + 8, WIN[3] + 8
    d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=RIM)
    d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=SPACE)
    d.rectangle([WIN[0] - 2, WIN[1] - 2, WIN[2] + 1, WIN[3] + 1], outline=SPACE)
    for i, x in enumerate(range(x0 + 16, x1 - 16, 16)):     # rivets, on the grid
        d.rectangle([x, y0 + 3, x + 2, y0 + 4], fill=GREY_L)
        d.rectangle([x, y1 - 5, x + 2, y1 - 4], fill=GREY_L)


def rocket(d, x0):
    """One rocket, standing on the lunar surface.  Symmetric about its centre
    line, drawn in flat colours with a space-black outline, which is the same
    hand as the ship's own tiles: no gradients, and the shading all on one side.
    """
    cx = x0 + ROCKET_W // 2
    d.rectangle([x0 - 2, ROCKET_Y, x0 + ROCKET_W + 1, ROCKET_Y + ROCKET_H],
                fill=SPACE_L)

    def shape(rows, col, outline=1):
        """A run of (y, half-width) rows, outlined by drawing it once a pixel
        wider in space-black first -- one outline, or two for the body."""
        for dy, grow in ((0, outline),):
            for y, hw in rows:
                d.rectangle([cx - hw - grow, y, cx + hw + grow - 1, y], fill=col)

    cone = [(y, 2 + (y - ROCKET_Y) * 8 // 24) for y in range(ROCKET_Y, 32)]
    body = [(y, 10) for y in range(32, 152)]
    # Nose FIRST, so the body's outline and shading sit on top of the cone's
    # join rather than being cut by it.
    shape(cone, SPACE)
    shape(body, SPACE)
    for y, hw in cone:
        d.rectangle([cx - hw, y, cx + hw - 1, y], fill=RED)
    for y, hw in body:
        d.rectangle([cx - hw, y, cx + hw - 1, y], fill=HULL)
        d.rectangle([cx + 5, y, cx + hw - 1, y], fill=HULL_D)
        if y % 8 == 0:
            d.rectangle([cx - hw, y, cx + hw - 1, y], fill=HULL_D)
    # A colour break across the body, on the grid like everything else: without
    # it the rocket is twenty pixels of pale hull and the eye has nothing to
    # measure its length against.
    d.rectangle([cx - 10, 104, cx + 9, 111], fill=RED)
    d.rectangle([cx + 5, 104, cx + 9, 111], fill=RED_D)

    # Fins: a triangle flaring from the body's edge out to the full width, and
    # the nozzle between them, which is what makes the bottom read as an engine
    # rather than a blunt end.
    for y in range(132, 164):
        hw = 10 + (y - 132) * 6 // 32
        d.rectangle([cx - hw - 1, y, cx + hw, y], fill=SPACE)
        if hw >= 12:                    # until it clears the body's own outline
            d.rectangle([cx - hw, y, cx - 12, y], fill=RED)
            d.rectangle([cx + 11, y, cx + hw - 1, y], fill=RED_D)
    for y in range(152, 168):
        hw = 6 + (y - 152) * 3 // 16
        d.rectangle([cx - hw - 1, y, cx + hw, y], fill=SPACE)
        d.rectangle([cx - hw + 1, y, cx + hw - 2, y], fill=RIM)
        d.rectangle([cx - hw + 1, y, cx - 1, y], fill=GREY_L)

    # The plume, from the nozzle down onto the surface: two tones, tapering, so
    # the rockets are LANDING on the horizon rather than parked above it.
    for y in range(168, GROUND):
        hw = 7 - (y - 168) * 5 // 40
        d.rectangle([cx - hw, y, cx + hw - 1, y], fill=FLAME_D)
        d.rectangle([cx - hw + 2, y, cx + hw - 3, y], fill=FLAME)

    # One porthole, on the body's upper half, with a glint: the ship the game
    # flies has the same one tile, and it is what says "crew" and not "missile".
    for r in (10, 9, 6):
        col = SPACE if r == 10 else (RIM if r == 9 else SPACE)
        d.ellipse([cx - r, 72 - r, cx + r - 1, 72 + r - 1], fill=col)
    d.rectangle([cx - 5, 68, cx - 3, 69], fill=STAR)


def surface(d):
    """The horizon: two tile rows of regolith along the bottom, with craters.
    Flat and level, because the whole point of the game is that only the pads
    are safe to land on and this is not one."""
    d.rectangle([0, GROUND, W - 1, H - 1], fill=GREY)
    d.rectangle([0, GROUND, W - 1, GROUND + 2], fill=GREY_L)
    for cx in (96, 168):
        d.ellipse([cx - 16, GROUND - 1, cx + 15, GROUND + 10], fill=GREY_L)
        d.ellipse([cx - 13, GROUND + 1, cx + 12, GROUND + 8], fill=GREY)


def main():
    font = read_font()
    im = Image.new("RGBA", (W, H), SPACE)
    d = ImageDraw.Draw(im)

    starfield(d)
    rim(d)
    rocket(d, 8)
    rocket(d, W - 8 - ROCKET_W)
    surface(d)

    text(d, font, 4, TITLE, TITLE_SCALE, GOLD)
    text(d, font, 24, CREDIT, CREDIT_SCALE, BYLINE)
    text(d, font, 196, MODES, 1, HULL_D)

    # The game window: the SGB shows the GB screen here, so it stays empty.
    d.rectangle([WIN[0], WIN[1], WIN[2] - 1, WIN[3] - 1], fill=(0, 0, 0, 0))

    im.save(OUT_PNG)
    colours = im.getcolors(1 << 16)
    print("%s: %dx%d, %d colours (limit 16)"
          % (OUT_PNG, W, H, len(colours)))
    assert len(colours) <= 16, "one SGB border palette holds 16 colours"

    # The window is the hole the SGB shows the Game Boy's screen through, and it
    # is the ONLY transparent part: any other transparent pixel is a hole in the
    # border, whatever happens to be behind it.  So the clear pixels must count
    # out to the window exactly.
    clear = sum(n for n, c in colours if c[3] == 0)
    want = (WIN[2] - WIN[0]) * (WIN[3] - WIN[1])
    assert clear == want, "%d transparent pixels, window is %d" % (clear, want)

    # The tile budget, checked HERE rather than discovered at `make border`: the
    # border's tile data is one CHR_TRN block of 128 tiles, or two, and a border
    # with EXACTLY 128 tiles transfers nothing at all -- sgb_border.c shifts the
    # count left for a single block, so 128 comes back as 256 in a uint8_t and
    # the payload goes out empty.  That is the whole trap, and it is silent: no
    # error, no partial border, just nothing where the border should be.
    # Over 128 is fine -- it goes out as two blocks, which is what Protector's
    # 185-tile border ships -- but 256 is the SGB's two blocks and the end of it.
    tiles = {im.crop((x, y, x + 8, y + 8)).tobytes()
             for y in range(0, H, 8) for x in range(0, W, 8)}
    print("distinct 8x8 tiles: %d (128 is the number that does not work)"
          % len(tiles))
    assert len(tiles) != 128, "exactly 128 tiles transfers nothing"
    assert len(tiles) <= 256, "%d tiles is past the SGB's two CHR blocks" % len(tiles)

    # Easy to think this script is the whole job: it only writes the PNG, and
    # `make` alone will not pick it up (border_data.c is generated, and only by
    # `make border`).  Skip the second step and the ROM keeps the old border,
    # which looks exactly like the change not working.
    print("next: make border && make   # PNG -> border_data.c -> ROM")


if __name__ == "__main__":
    main()
