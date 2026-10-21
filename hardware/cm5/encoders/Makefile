OVERLAY = cm5-main-three-knobs-overlay

.PHONY: all clean
all: $(OVERLAY).dtbo

$(OVERLAY).dtbo: $(OVERLAY).dts
	dtc -@ -I dts -O dtb -o $@ $<

clean:
	rm -f $(OVERLAY).dtbo
