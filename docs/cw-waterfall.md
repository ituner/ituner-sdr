# CW waterfall and signal slots

The local CW console and `/cw` web page show the 3 kHz audio window from 200 to
3200 Hz above the receiver's USB dial frequency. Frequency labels are RF MHz,
spaced every 500 Hz. The plot does not zoom to the selected signal.

Numbered vertical markers correspond to the four signal slots below the plot:

- Yellow marks the selected signal and its decoded-text panel.
- Green marks other active signals.
- Dashed gray marks fading signals (a selected fading signal stays yellow/dashed).

Tap a marker or its slot to select its text. Selection does not retune the radio.

fldigi can acquire signals across the full 3 kHz window. GGMorse retains its
200–1200 Hz acquisition limits; the remaining visible area is shaded and labeled
“Overview only.” Showing that extra spectrum does not add native decoding support
outside GGMorse's limits or allocate additional Kiwi channels.

Existing frequencies and decoder limits are preserved. Restart the SDR application
after installing this change to reconnect existing receivers with the wider audio
passband. Decoded-text history is unchanged.
