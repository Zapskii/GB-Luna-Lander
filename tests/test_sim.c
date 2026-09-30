/* Host tests for LUNA LANDEER.
 *
 * WHY THIS EXISTS: the physics lives in sim.h as pure C with no gb/gb.h in it,
 * so plain gcc can compile and run it -- no emulator, no ROM, no waiting.
 * tools/probe.py is the other half: it covers the wiring between that maths and
 * main.c, which the host cannot see.  This covers the maths, where the boundary
 * cases live.
 *
 * P1 has no sim.h yet -- it is the toolchain probe -- so the one thing worth
 * pinning today is the width discipline every later phase is written in: the
 * values are explicit uint8_t/int16_t/uint32_t and GBDK's `int` is 16-bit, so a
 * type that silently widened here would poison every arithmetic case P3 adds.
 *
 *     make test
 */
#include <stdint.h>
#include <stdio.h>

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

    if (failed) {
        printf("FAILED: %d of %d checks\n", failed, checks);
        return 1;
    }
    printf("OK: %d checks passed\n", checks);
    return 0;
}
