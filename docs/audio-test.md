# Sine-wave audio test

Open Apps / Tools → Audio Test. Choose a frequency (100 Hz–5 kHz), digital
level (−40 to 0 dBFS), and duration (5–60 seconds), then press Play Tone.
The initial selection is 1 kHz, −30 dBFS, 10 seconds. Stop Tone or Back ends
playback; timed playback stops automatically. Settings change while stopped.

The tone is identical on left and right, 48 kHz signed 16-bit PCM. It uses
the selected audio backend and output device, bypasses radio EQ/DSP, and
preserves system/codec volume and headphone detection. Unmute first if needed.
Radio audio is suspended during playback and its previous state resumes
when the tool releases the output. Stop other audio tools or dual listening
before starting a test. No additional receiver connection is opened.

The selected dBFS value describes peak digital amplitude, not speaker power.
For example −6 dBFS is approximately 50% peak amplitude. The actual voltage
also depends on codec volume, amplifier gain, supply, load, and clipping.
Begin at a low level. Use a suitable dummy load for high-level measurements.
For the bridged Class-D output, measure differentially across SPK+ / SPK−;
SPK− is not ground.
