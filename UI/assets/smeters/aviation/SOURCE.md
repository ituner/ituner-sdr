# Aviation Black and Aviation Brass

Original photorealistic housing assets created for this application on
2026-10-15 with the built-in image generation tool. Full prompts are in
`PROMPTS.md`; final unchanged source images are `black.png` and `brass.png`.
These are newly generated designs, not scans of historic S-meters and not
artwork by a third-party radio amateur. No callsign attribution is claimed.

Research references for actual metal, glass and period instrument construction:

- Smithsonian National Air and Space Museum / United States Gauge Co., fuel
  pressure indicator, circa 1926: chromed brass case and white-on-black dial.
  The reference photograph is CC0; it is not copied or bundled:
  https://commons.wikimedia.org/wiki/File:Indicator,_Pressure,_Fuel_-_DPLA_-_03a5d3be6fee27171f94a8ff2de5547f_(page_1).jpg
- Science Museum Group, United Brass Founders and Engineers aircraft engine
  back-pressure gauge, 1916 (reference only; no image copied or bundled):
  https://collection.sciencemuseumgroup.org.uk/objects/co240831/aircraft-engine-back-pressure-gauge-0-20-psi

The blank housings deliberately contain no painted scale or needle. Runtime
adds calibrated S and dBm markings, a live pointer and receiver readouts in S,
dBm and RMS microvolts at 50 ohms. Printed marks and pointer use the same
receiver signal mapping and -130° to +130° sweep. Dial images are kept square
in every preview size. Static print and housing are cached at native dimensions;
changing RSSI only moves the pointer and updates the readout. Existing saved
`aviation` and `heritage` selections automatically use the replacement faces.
