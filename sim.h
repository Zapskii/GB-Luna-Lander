/* LUNA LANDEER -- sim.h
 *
 * THE RULES.  Pure C: no gb/gb.h in here, so tests/test_sim.c compiles this
 * with plain gcc -std=c99 and the physics can be run without an emulator.
 * main.c owns every variable; nothing in this file declares storage, only the
 * types and the functions that operate on them.
 *
 * Positions are WHOLE PIXELS plus a separate fraction byte, never 8.8 packed
 * into one word.  fix_step() needs the fraction as a byte it can point at, and
 * keeping the whole part a plain uint16_t leaves a value a tile lookup or a
 * camera can use directly.  HEIGHTS, by contrast, are 8 px TILE units -- see
 * terrain.h -- so a `<< 3` anywhere near terrain[] is the classic slip.
 */
#ifndef SIM_H
#define SIM_H

#include <stdint.h>

/* ------------------------------------------------------------- 8.8 fixed */

/* Advance a sub-pixel accumulator by velocity v (8.8 fixed, px/frame) and
 * return the whole-pixel delta.
 *
 * *frac MUST point at one of the caller's own fraction bytes -- the fractional
 * remainder has to survive from one tick to the next, and that is the only
 * reason this takes a pointer.  Hand it a local (or a fresh uint8_t) and the
 * remainder is reset every tick: every fractional pixel is thrown away and the
 * motion quantises to whole pixels.  The ship still moves, so it looks like
 * "the physics is fine, it is just chunky" and nothing on screen says
 * otherwise -- which is exactly why the byte lives in the state struct. */
static int16_t fix_step(uint8_t *frac, int16_t v)
{
    int16_t acc = (int16_t)*frac + v;
    *frac = (uint8_t)(acc & 0xFF);
    return acc >> 8;
}

/* ---------------------------------------------------------------- gravity */

/* Gravity per tick as n/256 px/frame^2 -- n a POWER OF TWO and nothing else.
 * SDCC turns a power-of-two scale into a shift; any other constant silently
 * pulls in __mulint (~69 bytes) or __divsint (~231 bytes) for one line.
 *
 * 16/256 = 0.0625 px/frame^2 crosses the 144 px screen from rest in ~68 frames
 * (~1.1 s): long enough to react, short enough to read as falling.  This is a
 * CALIBRATION KNOB, not a derived value -- P5 owns the feel and is expected to
 * move it, so nothing below may assume this particular number. */
#define GRAV 16

/* ------------------------------------------------------------------ ship */

typedef struct {
    uint16_t x;     /* left edge, whole screen px */
    uint16_t y;     /* top edge, whole screen px  */
    uint8_t  xf;    /* x fraction, 1/256 px       */
    uint8_t  yf;    /* y fraction, 1/256 px       */
    int16_t  vx;    /* 8.8 fixed px/frame         */
    int16_t  vy;
} Ship;

/* One tick of the ship.  P3 is gravity ALONE: no rotation, no thrust, no fuel,
 * no collision and no landing verdict.  Each of those lands here as another
 * line rather than as a surrounding rewrite, which is the point of doing the
 * smallest wrong-in-an-interesting-way thing first.
 *
 * The two fix_step() calls are the whole of the sub-pixel behaviour: both
 * fraction bytes live in the struct, so the remainders carry across ticks and
 * the ship leaves rest a fraction of a pixel at a time. */
static void ship_step(Ship *s)
{
    s->vy += GRAV;
    s->y = (uint16_t)(s->y + fix_step(&s->yf, s->vy));
    s->x = (uint16_t)(s->x + fix_step(&s->xf, s->vx));
}

#endif
