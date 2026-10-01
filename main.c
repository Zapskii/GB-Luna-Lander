/* LUNA LANDEER -- main.c
 *
 * Hardware only: boot, the tick loop, and the drawing that has to go through
 * gb/gb.h.  Every rule (gravity, thrust, the landing verdict) belongs in sim.h
 * so tests/test_sim.c can compile it with plain gcc, and this file owns the
 * storage those rules operate on.  Nothing else in the project includes gfx.h:
 * a `static const` in a header is duplicated into every translation unit that
 * includes it.
 *
 * P1 is the toolchain probe.  The ROM boots, the generated tiles and the ship
 * sprite land in VRAM, the BG map is filled with the terrain tile, and `frame`
 * advances once per emulated frame.
 *
 * P2 blits the generated height profile over that fill: one tilemap column per
 * world column, sky above the surface and ground below it.  Still no camera,
 * no ship and no collision -- the profile and the screen are what this phase
 * has to agree about.
 */
#include <gb/gb.h>
#include <stdint.h>

#include "gfx.h"
#include "terrain.h"

/* The BG tilemap.  The PPU's is 32x32 regardless of what the 20x18 window
 * shows, and P2 blanks all of it: a later scroll brings in sky, not whatever
 * was left in VRAM. */
#define MAP_W 32
#define MAP_H 32
#define VIEW_H 18

/* One loop iteration IS one tick.  wait_vbl_done() paces the loop, so there is
 * no dt accumulator and none may be added: physics runs once per iteration and
 * one iteration is one ~16.7 ms frame.  probe.p1_boot reads this out of
 * luna.map -- statics live in main.c for that reason, and `Fmain$` in the map
 * is where it finds them -- and asserts it advances by exactly one per emulated
 * frame.  That assertion is also the frame-rate check: a frame that overruns
 * the budget halves the game and shows up here as frame advancing 0, not 1. */
static uint16_t frame;

/* This tick's joypad poll.  Nothing branches on it yet; P4/P6 read it (and
 * `pressed`, which is `keys & ~prev_keys`). */
static uint8_t keys;

/* The family's VRAM lock, as a value tools/probe.py can read back.
 *
 * The PPU locks VRAM while the display is on, so every tile write has to happen
 * with it off -- load the data first, DISPLAY_ON last.  PyBoy does NOT model
 * that lock, which means a DISPLAY_ON placed too early renders identically
 * under the emulator and nothing about the finished screen can tell the two
 * orders apart.  Sampling LCDC at the last VRAM write is what makes the order
 * observable: this IS the order, not a proxy for it.  probe.p1_boot asserts bit
 * 7 is clear here. */
static uint8_t lcdc_at_load;

/* Blit the level surface into the BG tilemap: one tilemap column per world
 * column.  There is no camera yet, so world column N IS screen column N and the
 * whole 160 px world is on screen at once.
 *
 * terrain[col] is a TILE row, not a pixel row -- the 8 px tile mkgfx.py draws
 * the art in -- so there is no `<< 3` anywhere here.  A `<< 3` is the classic
 * "heights are pixels" slip and it would drop the ground eight rows and push
 * the bottom of it off the screen, which still LOOKS like terrain.
 */
static void draw_terrain(void)
{
    uint8_t col, top;

    /* Sky first, the whole 32x32 map: T_BLANK is tile 0, so this leaves the
     * paper behind everything the surface does not cover. */
    fill_bkg_rect(0, 0, MAP_W, MAP_H, T_BLANK);

    for (col = 0; col < WORLD_COLS; col++) {
        top = terrain[col];                     /* surface row, tile units */

        fill_bkg_rect(col, top, 1, 1, T_TERRAIN_TOP);

        /* Guarded: a surface on the last view row leaves no body to draw, and
         * a zero-height fill_bkg_rect is a map address walked for nothing. */
        if (top + 1 < VIEW_H)
            fill_bkg_rect(col, top + 1, 1, VIEW_H - 1 - top, T_TERRAIN);
    }
}

void main(void)
{
    DISPLAY_OFF;

    /* set_bkg_data/set_sprite_data take a tile COUNT, not a last id: passing 0
     * loads all 256. */
    set_bkg_data(0, GFX_TILE_COUNT, gfx_tiles);
    set_sprite_data(0, GFX_SPRITE_COUNT, gfx_sprites);

    /* 0xE4: colour 0 is the paper and colour 3 the ink, the ramp mkgfx.py draws
     * against.  OBJ has its own register, and powering up leaves it to crt0. */
    BGP_REG = 0xE4;
    OBP0_REG = 0xE4;

    draw_terrain();

    /* The LAST VRAM write, so this one sample covers all of them: if the
     * display went on at any point before this line, bit 7 is set here.  It has
     * to come after draw_terrain(), which is the last thing that touches VRAM. */
    lcdc_at_load = LCDC_REG;

    /* Park the ship off-screen until there is a game to fly it in.  OAM is not
     * screen space -- an 8x8 sprite draws at (x-8, y-16) -- and OAM y = 0 hides
     * a sprite outright, which is the (0, 0) this game parks things at. */
    move_sprite(SPR_SHIP0, 0, 0);

    SHOW_BKG;
    SHOW_SPRITES;
    DISPLAY_ON;

    while (1) {
        keys = joypad();
        frame++;
        wait_vbl_done();
    }
}
