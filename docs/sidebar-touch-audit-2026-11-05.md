# Sidebar touch audit — 5 November 2026

Requested behavior: sidebar titles, whitespace, margins and gaps must not act as HOME or BACK. Navigation stays on visible controls. UI implementation, decoder coverage and independent UX review were assigned separately.

## Findings and changes by screen

| Screen | Finding / correction |
|---|---|
| HOME | Explicit navigation targets retained; gaps have no action. |
| SYSTEM and DIGITAL/DECODERS menus | Protect the covered HOME rail from fall-through; navigation requires an actual target. |
| MODES / FM-DX | Remove the blank-hit close path; only explicit controls change mode or leave the drawer. |
| DISPLAY / Advanced | Remove unmatched-hit dismissal; retain explicit BACK and settings actions. |
| SYSTEM → SYSTEM (INFO) | Remove the unmatched-hit close path; title and gaps remain on INFO. |
| AUDIO / Advanced | Preserve inert header and internal gaps; protect the outer rail margins from outside-dismiss handling. |
| PASSBAND / FREQUENCY / FAN CURVE | Keep graphs, sliders, keypad and explicit BACK usable; protect rail whitespace from dismissal. |
| CAPTIONS / engine and language choices | Preserve explicit selection/BACK actions; no header dismissal. |
| APPS / TOOLS / Font Lab | Preserve explicit actions; guard press/release target matching. |
| DJ Tune / USB local receiver / RTL Lab | Protect rail margins from generic outside-dismiss routes. |
| RECEIVERS lists/categories | Preserve explicit rows, categories and BACK; guard covered rail areas. |
| RECEIVERS GLOBE | Full-canvas map, not a conventional sidebar. Preserve map gestures and explicit BACK. |
| Wi-Fi / ETHERNET | Explicit controls only; require a matching press/release target. |
| RADIO / USER information | Existing StationWorkspace action-list handler already ignores unmatched taps. |
| USB-RADIOS | Existing DongleWorkspace action-list handler already ignores unmatched taps. |
| UPDATES / recovery / Audio Test | Existing explicit controls; no header or whitespace navigation action found. |
| CPU LOAD | Preserve SYSTEM navigation and the visible CPU footer/graph actions; sidebar whitespace does not trigger navigation. The shared CPU/sidebar boundary belongs to the sidebar. |
| BAND chooser | Remove blank-hit dismissal in the release handler; retain explicit band/BACK actions. |
| Dual RX | Preserve main controls. Inside the nested mode picker, blank space is idle rather than outside-dismiss. RF-pane VFO selectors remain interactive; they are not sidebar titles. |
| Themes: chooser, Customize, Color, hidden controls | Existing unknown-hit behavior is inert. Add regression coverage for both physical sidebar positions in all four states. |
| ADS-B: Map, Traffic, Logs, Receiver, Settings, View, history window | Existing action-only routing verified with header, margin and gap probes; no decoder-local dismissal fix needed. |
| CW: main, receivers, add form, history | Existing action-only routing verified with blank-area probes. |
| QRSS, SSTV, HELL: main/gallery, receivers, add forms | Existing action-only routing verified with blank-area probes. |
| AIS, APRS, rtl_433, Meteor-M, CubeSat, Radiosonde | Existing shared VHF routing verified across data, map, products, USB and profile views. |
| Spectrum: Scan, Signals, Tools, Activity, Compare, Watch, Reports | Existing explicit navigation verified, including Settings, Advanced, USB and presets. |
| WSPR | Core routing audit included workspace, add/setup and settings paths; explicit controls retained. |
| Log search / USB notice | Existing action-list handlers ignore unmatched taps. |
| Satellite web apps / Ground Stations / Satvisor | Shell title has no navigation action; explicit native/browser return controls retained. |

## Verification scope

Ordinary left-side rails are normalized to canonical right-rail coordinates before hit-testing. Full-width workspaces position their own controls and bypass this remapping. Theme regression tests exercise both physical positions; core tests cover normalized rails. Decoder tests sample visible headers, margins and inter-button gaps, excluding actual action rectangles.

The existing idle timeout is separate from touch dismissal and is unchanged. Existing deliberate outside-modal dismissal on the RF/content area is outside this sidebar-only correction. The audit and automated checks do not substitute for physical CM5 touch acceptance testing.

## Validation record

- Final full UI suite: 1,236 tests completed; 1,233 passed and three optional decoder-engine checks skipped.
- Final focused sidebar, decoder and theme checks on CM5: 29 passed, including the boundary refinement.
- Three independent agents contributed implementation, decoder regression coverage and UX review.
- No physical tap/drag acceptance result is claimed; test the deployed build on CM5.
