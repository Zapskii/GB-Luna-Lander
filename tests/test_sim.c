/* Host tests for LUNA LANDEER.
 *
 * WHY THIS EXISTS: the physics lives in sim.h as pure C with no gb/gb.h in it,
 * so plain gcc can compile and run it -- no emulator, no ROM, no waiting.
 * tools/probe.py is the other half: it covers the wiring between that maths and
 * main.c, which the host cannot see.  This covers the maths, where the boundary
 * cases live.
 *
 * P1 had no sim.h yet -- it was the toolchain probe -- so the width discipline
 * every later phase is written in comes first: the values are explicit
 * uint8_t/int16_t/uint32_t and GBDK's `int` is 16-bit, so a type that silently
 * widened here would poison the arithmetic below.
 *
 * P3 is what there is to test so far: fix_step's carried remainder and the
 * exact 8.8 trajectory gravity produces from rest.  The trap of the phase --
 * a fraction byte in ship_step()'s LOCALS instead of in the state -- is pinned
 * from both sides, because it is the one that ships looking fine.
 *
 *     make test
 */
#include <stdint.h>
#include <stdio.h>

#include "../sim.h"

static int checks, failed;

static void check(int cond, const char *msg)
{
    checks++;
    if (!cond) {
        failed++;
        printf("FAIL  %s\n", msg);
    }
}

int main(void)
{
    check(sizeof(uint8_t) == 1 && sizeof(uint16_t) == 2 &&
          sizeof(int16_t) == 2 && sizeof(uint32_t) == 4,
          "the fixed-width types are the widths the physics is written in");

    /* ------------------------------------------------------------ P3 ---- */

    {
        uint8_t frac = 0;
        int16_t moved = 0;
        uint8_t i;

        /* fix_step carries the remainder it is POINTED AT: sixteen ticks of
         * GRAV (16/256 px each) are exactly one whole pixel, and the byte is
         * back where it started. */
        for (i = 0; i < 16; i++)
            moved += fix_step(&frac, GRAV);
        check(moved == 1 && frac == 0,
              "sixteen GRAV ticks carry one whole pixel and leave no remainder");

        /* The same sixteen ticks with the fraction in a LOCAL -- the trap.  A
         * fresh zero every call means every remainder is discarded, so the
         * ship does not move at all here.  If this ever stops failing to move,
         * fix_step has changed what its first argument means. */
        moved = 0;
        for (i = 0; i < 16; i++) {
            uint8_t local = 0;
            moved += fix_step(&local, GRAV);
        }
        check(moved == 0,
              "a fraction byte in a local throws the remainder away");
    }

    {
        Ship s;
        uint8_t i;

        /* P3's whole target in one condition: from rest the ship spends WHOLE
         * TICKS not moving a single pixel while the state's fraction byte
         * builds up the remainder.  Written against GRAV rather than against
         * 16, so retuning the knob in P5 moves the numbers, not the check. */
        s.x = 80; s.y = 16; s.xf = 0; s.yf = 0; s.vx = 0; s.vy = 0;
        for (i = 0; i < 5 && s.y == 16; i++)
            ship_step(&s);
        check(i >= 2 && s.yf != 0,
              "from rest the whole-pixel y holds for whole ticks while the "
              "fraction byte accumulates the sub-pixel motion");

        /* ... and the position is the EXACT integral of the velocity ramp on
         * every tick: y*256 + yf == sum of GRAV*i for i = 1..n.  A fraction
         * byte in a local produces a sum of v >> 8 instead, which falls behind
         * this by a pixel in the first second and never catches up. */
        s.x = 80; s.y = 16; s.xf = 0; s.yf = 0; s.vx = 0; s.vy = 0;
        for (i = 1; i <= 60; i++) {
            uint32_t pos;
            ship_step(&s);
            pos = ((uint32_t)(s.y - 16) << 8) + s.yf;
            if (s.vy != (int16_t)(GRAV * i) ||
                pos != (uint32_t)GRAV * i * (i + 1) / 2)
                break;
        }
        check(i == 61 && s.y > 16,
              "sixty ticks of gravity are exactly the 8.8 integral of the "
              "velocity ramp, tick by tick");
    }

    if (failed) {
        printf("FAILED: %d of %d checks\n", failed, checks);
        return 1;
    }
    printf("OK: %d checks passed\n", checks);
    return 0;
}
