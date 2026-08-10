# WSPR Workspace Notes - 2026-08-10

## Scope

The Pi 5 OpenGL SDR UI now contains a multi-session WSPR monitoring workspace.
It is implemented in `UI/kiwi_gl_display.py` and uses the normal KiwiSDR SND
and W/F protocols rather than browser automation.

## Workspace behavior

- Up to six WSPR monitor tiles can run at once, with startup staggered by five
  seconds to avoid connection bursts after boot.
- A tile is configured with a receiver and WSPR band. It can be stopped,
  edited, or deleted from its settings control without stopping other tiles.
- Tapping the body of a tile cycles its waterfall, decoded-spot log, and MRTG
  distance/history views. The settings target remains separate.
- The decode tile shows seven compact rows. `FULL` opens the full-screen,
  scrollable recent spot log.
- WSPR waterfall history is an 800-row, in-RAM ring per active tile. `W/F
  FULL` opens it without opening an extra Kiwi connection. The OpenGL history
  texture is persistent and receives one row at a time; it must not be
  recreated or fully re-uploaded for every incoming waterfall row.

## Decoder and logging

- Each tile records an approximately UTC-aligned two-minute PCM capture and
  queues it for `wsprd` decoding. Decode work is deliberately serialized and
  launched with low CPU priority so active radio use remains responsive.
- The default identity is `SWL` until an operator callsign/grid is entered.
  Local JSONL logs remain valid without an amateur transmit licence. The log
  contains receiver, band, decoder state, and decoded spots; it is rotated by
  size rather than written on every UI frame.
- Distance is calculated from the *receiver's* Maidenhead grid to each decoded
  transmitter grid, never from a different tile's location.

## MRTG distance view

The compact tile plot uses a stable 48-minute timeline:

- 24 fixed bins, one for each two-minute WSPR cycle.
- Bars represent the number of spots decoded in that cycle.
- Dots represent individual path distances in kilometres.
- Empty cycles remain visible as gaps. This is deliberate: it prevents a few
  active bars from stretching across the whole graph and makes activity density
  readable at a glance.

## Kiwi receiver capacity and waterfall detail

KiwiSDR audio and waterfall resources are not necessarily equal. A receiver
reporting `mode=rx8.wf3` is in the newer Full 8-channel arrangement: it can
provide eight receiver/audio channels but only three tuneable waterfall paths.
Those shared waterfall paths support the lower 11-level zoom architecture,
while the classic yellow waterfall architecture supports 14 levels.

Implications:

- A main receiver plus three WSPR tiles can exhaust `wf3` even though audio
  slots remain available.
- A client must not continuously retry a refused W/F stream. After two short
  attempts it should retain audio/decode service and report the source state.
- At high WSPR zoom, an 11-level source should not be cropped and enlarged as
  though it were a native 14-level source. Prefer the tile's narrow audio-FFT
  fallback when a detailed W/F path is unavailable.
- `Kiwi classic` is usually the better local FPGA choice when the priority is
  four simultaneous high-detail waterfall sessions rather than eight audio
  receivers.

## Resilience rules

- Public Kiwi proxy redirects (HTTP 301/302/307/308 during WebSocket upgrade)
  are followed a bounded number of times.
- Paired SND and W/F sockets share a Kiwi session timestamp so they are treated
  as one listener by capacity-limited receivers.
- Health checks record audio, waterfall, and advertised time-limit state.
- A normal transient W/F problem never interrupts selected receiver audio.
- Audio gaps may be marked in a locally generated audio-FFT timeline; do not
  paint red retry lines over a genuine remote waterfall simply because its W/F
  socket is reconnecting.

## Verification baseline

- The display systemd unit is `ituner-sdr-lcd-kms.service`.
- Validate source with:

  ```sh
  python3 -m py_compile UI/kiwi_gl_display.py UI/kiwi_live_display_fb.py \
    UI/kiwi_station_health.py UI/render_sdr_frontend_mockup.py
  ```

- Confirm the display service after deployment:

  ```sh
  systemctl is-active ituner-sdr-lcd-kms.service
  ```

