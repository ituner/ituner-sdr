# Waterfall contrast

Display settings has separate **WATERFALL AUTO** and **WATERFALL MANUAL**
choices. Auto is the default on new installations and on the first upgrade
from the older implicit fixed palette settings. Subsequent explicit choices
are saved as `waterfall.contrast_mode` and restored on restart.

Auto measures the visible window's noise and upper signal levels, seeds the
range from the first row and smooths subsequent adjustments. Panning, tuning,
zooming or changing receiver starts a fresh measurement. Local magnification
estimates contrast from the visible slice of the source FFT, excluding signals
outside the view. Main Kiwi, OpenWebRX, FM-DX audio FFT, USB and Smart Seek use
the same contrast rule with independent ranges for their current views.

Manual starts from the live range and holds fixed floor and ceiling settings.
Dragging either level slider selects Manual. Choosing another color palette
preserves the contrast mode; Reset Display returns to Auto. The spectrum's
existing Auto control remains independent of the waterfall mode.

The range estimation changes display mapping, not receiver tuning. There are
no new network connections or speech models. Existing waterfall history stays
on screen while newly arriving rows use the selected settings.
