# GB-LUNA-LANDEER build.
#   make          build luna.gb   (GBDK if GBDK_HOME is set, else Docker)
#   make test     host unit tests (plain gcc, no emulator)
#   make probe    headless PyBoy check harness against the rules in main.c
#   make fps      the tick-rate check alone (frame per emulated frame)
#   make shot     write a screenshot to /tmp/luna.png
#   make gfx      regenerate gfx.h from mkgfx.py
#   make border   regenerate border_data.c from art/border_sgb.png (SGB border)
#   make level    regenerate terrain.h from tools/mklevel.py
#   make tab      regenerate tables.h from tools/mktab.py
#   make usage    ROM/RAM headroom
#   make image    build the gbdk-dev Docker image used when GBDK_HOME is absent
#   make clean

ROM    = luna.gb
CFILES = main.c sgb_border.c border_data.c
# gfx.h, terrain.h, tables.h, sgb_border.h and border_data.h are on the line
# deliberately: they are GENERATED, and a make that does not know that says
# "nothing to do" after `make gfx` / `make level` / `make tab` / `make border`,
# leaving the OLD ROM in place for the checks to grade.  That is a false PASS,
# and it is silent.
SRCS   = $(CFILES) gfx.h terrain.h tables.h sgb_border.h border_data.h

# The harness needs PyBoy.  Prefer this project's venv, then the one Protector
# keeps (it has PyBoy in it), then whatever python3 is on PATH:
#   make probe PY=python3
PY ?= $(firstword $(wildcard .venv/bin/python ../GB-Protector/.venv/bin/python) python3)

ifneq ($(wildcard $(GBDK_HOME)/bin/lcc),)
  RUN   :=
  LCC   := $(GBDK_HOME)/bin/lcc
  USAGE := $(GBDK_HOME)/bin/romusage
  P2A   := $(GBDK_HOME)/bin/png2asset
else
  # GBDK is not installed on this host, so run the toolchain out of the image.
  # lcc must be the FULL PATH: it is not on PATH inside gbdk-dev, and a bare
  # `lcc` fails with "executable file not found".
  # -u keeps build artefacts owned by the user rather than root.
  RUN   := docker run --rm -u $(shell id -u):$(shell id -g) -v "$(CURDIR)":/work -w /work gbdk-dev
  LCC   := /opt/gbdk/bin/lcc
  USAGE := /opt/gbdk/bin/romusage
  P2A   := /opt/gbdk/bin/png2asset
endif

# -Wm-yn"..." : the title in the ROM header, so a flash cart names it
# -Wl-m      : the linker map.  Not optional here -- tools/probe.py reads the
#              game's own statics out of it instead of hardcoding addresses.
# -Wl-j      : NoICE symbols, for emulator debuggers.
# -Wm-ys     : the Super Game Boy flag in the header.  Without it the SGB
#              ignores the border packets and the border simply never appears --
#              no error, and identical behaviour on a DMG, so it is invisible
#              everywhere except on the real thing.  probe.p14_sgb_border reads
#              the header byte it sets.
# Anything the cart type does not need yet (MBC, SRAM) is deliberately absent
# until the phase that needs it.
LCCFLAGS = -Wm-ys -Wm-yn"LUNA" -Wl-m -Wl-j

all: $(ROM)

$(ROM): $(SRCS)
	$(RUN) $(LCC) $(LCCFLAGS) -o $@ $(CFILES)

# A `-debug` build: the linker map then carries EVERY symbol, not just the
# globals, which is what tools/probe.py reads the game's state through -- and
# what emulator debuggers want.  Not the default, because it is a bigger ROM.
# Phony, so it always re-links: as a file target make would see luna.gb already
# newer than its sources and leave the release ROM where the probe expects the
# debug one.
sym: $(SRCS)
	$(RUN) $(LCC) $(LCCFLAGS) -debug -o $(ROM) $(CFILES)

# The check harness: drives the ROM and asserts on what it did.  Dev-only;
# nothing in the build depends on it.
probe: sym
	$(PY) tools/probe.py $(ROM) $(ROM:.gb=.map)

# Frame-rate, kept as its own target because it is the one failure nobody
# notices by eye: a render that overruns the frame budget quietly halves the
# game.  There is no separate tools/fps.py here -- the measurement IS p1_boot's
# tick-rate assertion (frame per emulated frame), so this asks the harness for
# that one check rather than growing a second script that reads the same symbol.
fps: sym
	$(PY) tools/probe.py $(ROM) $(ROM:.gb=.map) p1_boot

shot: $(ROM)
	$(PY) tools/shot.py $(ROM) /tmp/luna.png

test: tests/test_sim
	./tests/test_sim

# sim.h, tables.h and terrain.h are on the line for the same reason they are on
# the ROM's: they are what the test actually compiles, so a `make test` after
# `make level` that did NOT relink would grade the previous headers' binary and
# print OK -- the false PASS this project keeps an eye out for.
tests/test_sim: tests/test_sim.c sim.h tables.h terrain.h
	gcc -std=c99 -Wall -Wextra -o $@ tests/test_sim.c

gfx:
	python3 mkgfx.py

# The Super Game Boy border: art/border_sgb.png (256x224; the 160x144 game area
# at x=48,y=40 is transparent) -> border_data.c/.h, committed like gfx.h so a
# plain `make` needs no Python.  The PNG is itself generated -- tools/mkborder.py
# draws it, the way mkgfx.py draws the tiles -- so an art change is that script
# plus this recipe, in that order.  -pack_mode sgb is what gets the SGB layout --
# 4bpp tiles, a 256x224 map, one attribute byte per cell -- instead of a GB
# screen; -use_map_attributes keeps that byte, which is the per-cell palette.
# -b 1 is what makes png2asset write `#pragma bank 1` at the top of the output,
# so the border's ~5 KB of tiles does not eat bank 0: this ROM never switches
# banks, so bank 1 is permanently mapped at 0x4000 and main.c can hand those
# addresses straight to set_bkg_data.  Regenerating is safe -- the pragma comes
# from here, not from hand-editing the generated file.
border:
	$(RUN) $(P2A) art/border_sgb.png -map -bpp 4 -max_palettes 4 \
	      -pack_mode sgb -use_map_attributes -b 1 -c border_data.c

level:
	python3 tools/mklevel.py

tab:
	python3 tools/mktab.py

usage: $(ROM)
	$(RUN) $(USAGE) $(ROM:.gb=.map) -g

image:
	docker build -t gbdk-dev .

clean:
	rm -f $(ROM) *.map *.noi *.o *.lst *.sym *.ihx *.asm *.adb *.cdb \
	      tests/test_sim $(ROM:.gb=.sav) $(ROM).ram

.PHONY: all test gfx border level tab usage image clean sym probe fps shot
