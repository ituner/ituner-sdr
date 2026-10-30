# Prepared AM auto-tune

For a connected Kiwi receiver in AM, AMN or AMW, acquisition begins after
300 ms of tuning inactivity. No frequency change occurs until the operator
presses AUTO TUNE / READY. The button stays hidden without a reliable result.
It remains visible when ready, independently of the normal controls fade.

The existing W/F connection measures a coarse zoom-11 carrier followed by
zoom-14 data (respecting the receiver's zoom cap). Five consistent rows are
needed for a fine estimate. That first estimate enables the button while
refinement continues. Three independent estimates agreeing within half a
native bin (at least 1 Hz), two seconds after the first estimate, or a total
four-second acquisition budget ends the measurement. No additional connection
or /status request is made. Audio continues; the displayed waterfall temporarily
holds while its existing connection supplies the measurement rows, then resumes.

A tuning/view change, held tuning gesture, mode/filter change, receiver change,
pause, disconnect or another tool taking audio invalidates the result. A failed
attempt is not continuously retried at the same view. A cached successful
measurement is retained for that unchanged tuning context; it is not continuous
carrier tracking. Once applied, the button stays hidden until another change.

The detector rejects noise, broad peaks and similarly strong competing carriers.
The applied correction preserves passband cuts, display zoom and waterfall
center. Frequency is rounded to 1 Hz; accuracy is limited by signal quality,
receiver calibration and its available RF resolution.
