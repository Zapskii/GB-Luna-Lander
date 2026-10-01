# GB-LUNA-LANDEER build.
#   make          build luna.gb   (GBDK if GBDK_HOME is set, else Docker)
#   make test     host unit tests (plain gcc, no emulator)
#   make probe    headless PyBoy check harness against the rules in main.c
#   make fps      the tick-rate check alone (frame per emulated frame)
#   make shot     write a screenshot to /tmp/luna.png
#   make gfx      regenerate gfx.h from mkgfx.py
#   make level    regenerate terrain.h from tools/mklevel.py
#   make usage    ROM/RAM headroom
#   make image    build the gbdk-dev Docker image used when GBDK_HOME is absent
#   make clean

ROM    = luna.gb
CFILES = main.c
# gfx.h and terrain.h are on the line deliberately: they are GENERATED, and a
# make that does not know that says "nothing to do" after `make gfx` / `make
# level`, leaving the OLD ROM in place for the checks to grade.  That is a
# false PASS, and it is silent.
SRCS   = $(CFILES) gfx.h terrain.h

# The harness needs PyBoy.  Prefer this project's venv, then the one Protector
# keeps (it has PyBoy in it), then whatever python3 is on PATH:
#   make probe PY=python3
PY ?= $(firstword $(wildcard .venv/bin/python ../GB-Protector/.venv/bin/python) python3)

ifneq ($(wildcard $(GBDK_HOME)/bin/lcc),)
  RUN   :=
  LCC   := $(GBDK_HOME)/bin/lcc
  USAGE := $(GBDK_HOME)/bin/romusage
else
  # GBDK is not installed on this host, so run the toolchain out of the image.
  # lcc must be the FULL PATH: it is not on PATH inside gbdk-dev, and a bare
  # `lcc` fails with "executable file not found".
  # -u keeps build artefacts owned by the user rather than root.
  RUN   := docker run --rm -u $(shell id -u):$(shell id -g) -v "$(CURDIR)":/work -w /work gbdk-dev
  LCC   := /opt/gbdk/bin/lcc
  USAGE := /opt/gbdk/bin/romusage
endif

# -Wm-yn"..." : the title in the ROM header, so a flash cart names it
# -Wl-m      : the linker map.  Not optional here -- tools/probe.py reads the
#              game's own statics out of it instead of hardcoding addresses.
# -Wl-j      : NoICE symbols, for emulator debuggers.
# Anything the cart type does not need yet (MBC, SRAM, the SGB header flag) is
# deliberately absent until the phase that needs it.
LCCFLAGS = -Wm-yn"LUNA" -Wl-m -Wl-j

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

tests/test_sim: tests/test_sim.c
	gcc -std=c99 -Wall -Wextra -o $@ tests/test_sim.c

gfx:
	python3 mkgfx.py

level:
	python3 tools/mklevel.py

usage: $(ROM)
	$(RUN) $(USAGE) $(ROM:.gb=.map) -g

image:
	docker build -t gbdk-dev .

clean:
	rm -f $(ROM) *.map *.noi *.o *.lst *.sym *.ihx *.asm *.adb *.cdb \
	      tests/test_sim $(ROM:.gb=.sav) $(ROM).ram

.PHONY: all test gfx level usage image clean sym probe fps shot
