#!/usr/bin/env python3
"""Add a receive-only PCM pipe to pinned fldigi 4.2.13 benchmark mode.
The inserted adapter uses fldigi's GPL-3.0-or-later benchmark code/decoder.
No sound device, rig connection, transmission or decoder algorithm changes.
"""
import sys
from pathlib import Path
root=Path(sys.argv[1])
p=root/'src/misc/benchmark.cxx'
s=p.read_text()
if 'ITUNER_READY' not in s:
    s=s.replace('#include "benchmark.h"','#include "benchmark.h"\n#include "cw.h"')
    marker='\tif (!benchmark.samples) {'
    adapter=r'''
	// iTuner streaming adapter: signed little-endian PCM at modem sample rate.
	if (benchmark.input == "-") {
		unsigned char raw[512]; double audio[256];
		printf("ITUNER_READY\n"); fflush(stdout);
		size_t n;
		while ((n = fread(raw, 1, sizeof(raw), stdin)) > 0) {
			for (size_t i = 0; i < n / 2; ++i)
				audio[i] = (int16_t)(raw[2*i] | (raw[2*i+1] << 8)) / 32768.0;
			active_modem->rx_process(audio, n / 2);
			printf("ITUNER_RX:");
			for (size_t i = 0; i < benchmark.buffer.size(); ++i)
				printf("%02x", (unsigned char)benchmark.buffer[i]);
			printf("\n"); benchmark.buffer.clear();
			if (active_modem->get_mode() == MODE_CW)
				printf("ITUNER_WPM:%d\n", static_cast<cw*>(active_modem)->ituner_receive_wpm());
			fflush(stdout);
		}
		return;
	}
'''
    if marker not in s:raise SystemExit('Unexpected fldigi source; streaming hook not found')
    s=s.replace(marker,adapter+'\n'+marker,1)
    p.write_text(s)
p=root/'src/include/cw.h';s=p.read_text()
if 'ituner_receive_wpm' not in s:
    s=s.replace('\tcw();','\tint ituner_receive_wpm() const { return cw_receive_speed; }\n\tcw();',1)
    p.write_text(s)
