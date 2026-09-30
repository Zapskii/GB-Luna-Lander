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
 */
#include <gb/gb.h>
#include <stdint.h>

#include "gfx.h"

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

    /* The LAST VRAM write, so this one sample covers all of them: if the
     * display went on at any point before this line, bit 7 is set here. */
    lcdc_at_load = LCDC_REG;
    fill_bkg_rect(0, 0, 32, 32, T_TERRAIN);

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
