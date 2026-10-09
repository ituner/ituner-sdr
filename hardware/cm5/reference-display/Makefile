# SPDX-License-Identifier: GPL-2.0-or-later
obj-m += panel-jadard-jd9365da-h3.o

ifeq ($(KERNELRELEASE),)
KVER ?= $(shell uname -r)
KDIR ?= /lib/modules/$(KVER)/build
DTC ?= dtc
OVERLAYS := cm5-main-fpc2-yx80030.dtbo cm5-main-fpc2-gt911.dtbo

.DEFAULT_GOAL := all
.PHONY: all modules overlays clean help
all: modules overlays

modules:
	@test -f "$(KDIR)/Makefile" || { echo 'Install headers matching the target kernel; see README.md.' >&2; exit 1; }
	$(MAKE) -C "$(KDIR)" M="$(CURDIR)" modules

overlays: $(OVERLAYS)

%.dtbo: %-overlay.dts
	$(DTC) -@ -I dts -O dtb -o "$@" "$<"

clean:
	$(MAKE) -C "$(KDIR)" M="$(CURDIR)" clean
	$(RM) $(OVERLAYS)

help:
	@echo 'make                 Build module and both FPC2 overlays for the running kernel'
	@echo 'make overlays        Build only device-tree overlays (also works off-board)'
	@echo 'make KVER=... KDIR=...  Build against a specific prepared kernel tree'
	@echo 'Installation, boot settings, touch mapping and rollback: see README.md'
endif
