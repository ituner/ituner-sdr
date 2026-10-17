# Spectrum frequency / allocation inspector

Hover or tap the survey chart to inspect the cursor frequency, measured bin level and EU/CEPT + US allocations. A floating chart tooltip keeps the information visible on a short display; the panel below the chart lists every matching service, priority, application category, allocation interval, references and source links. Left/right arrows step by one acquired bin (Shift: ten); Home/End inspect the visible range edges. These controls do not retune or claim the receiver. A vertical marker persists at the last inspected frequency; live power refreshes with the survey.

The readout is an allocation reference, not a signal or transmitter classifier. Cursor position can be more precise than the acquired bin width, which is shown alongside the power. EU means the European **common CEPT plan**, not a single national EU licence table; Romanian and other national implementation can differ. Primary/secondary describe service priority. Applications and FCC rule categories may occupy only part of a broad allocation; source notes still apply.

## Sources and reproducibility

- European data: [CEPT/EFIS European Common Allocation Table](https://efis.cept.org/sitecontent.jsp?sitecontent=ecatable), official [CSV export](https://efis.cept.org/reports/ReportDownloader?reportid=3), captured 2026-10-17. 146 allocation intervals cover 25–1700 MHz. Explicit application subranges from EFIS notes are applied to cursor lookup, avoiding, for example, calling 868.3 MHz a GSM or RFID channel merely because those uses appear elsewhere within a broad mobile allocation.
- The CSV export omits 400.05–400.15 MHz, whose applications column is blank. `UI/spectrum_allocation_supplements.json` supplies the allocation verified visually against page 75 of the official [PDF export](https://efis.cept.org/reports/ReportDownloader?reportid=1): ERC Report 25, approved January 2025 / editorial update 28 November 2025.
- US data: the current [NTIA Redbook Table of Frequency Allocations](https://redbook.ntia.gov/view/4-17#frequency-table), marked **updated August 11, 2026**, captured 2026-10-17. Both federal and non-federal columns, FCC rule categories and matching source footnotes are retained (398 entries). Explicit additional allocations can be supplied by footnotes: US275, for example, adds secondary amateur use at 902–928 MHz. International Region 2 data is not substituted for the US national columns.

The packaged data is `UI/spectrum_allocations.json`; it includes source dates, URLs and SHA256 hashes of the captured inputs. The pure lookup module is `UI/spectrum_bands.js`. Intervals are half-open, so an exact band boundary belongs to the following band. All overlapping US entries are returned. Unknown/outside-reference values are explicitly unavailable.

Run `python3 scripts/build-spectrum-allocations.py` to rebuild the embedded lookup from the packaged JSON and module. This preserves the main application code after the generated marker. The compiled `UI/spectrum.js` contains the complete offline lookup; installation needs no new HTTP route, external hover requests or receiver restart. Existing VHF/weather/RTL433 installers already deploy this asset.

For a source refresh, obtain the EFIS CSV, then export the **visible DOM** from the NTIA table. The NTIA input JSON contains `cells` (allocation cells in columns 4, 5 and FCC rule column 6) and `notes`:

- Cell fields: `id` from data-allocation-id; `column` from CSS gridColumnStart / gridColumnEnd; `label` from aria-label; `lines` from each direct child of its first child, with `text` and `notes` (`marginTop === 'auto'`).
- Notes: each visible element under `#content-container [data-footnote-id]`, keyed by its data-footnote-id with `toa_` removed, whitespace-normalized text. Export notes as an array of pairs before converting to an object to avoid transport object-key limits.

Then run `python3 scripts/build-spectrum-allocations.py --eca-csv PATH --ntia-dom PATH`, inspect any supplements and source-date changes, and run `node --test tests/test_spectrum_bands.cjs`. Review coverage, endpoints, national differences, priorities, shared entries, and applications restricted to subbands before deploying.
