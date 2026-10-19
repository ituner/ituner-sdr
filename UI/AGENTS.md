# Decoder workspace layout

User preference: decoder workspaces without a waterfall may use the entire
screen for the view, instruments, menus, and controls in whatever arrangement
makes the decoder easiest to use. A fixed menu on the right is not required.
This applies to ADS-B and future decoders without waterfall displays.
Use the available space deliberately, keep touch targets usable, and make live
data, historical data, and receiver status easy to distinguish.

Keep shared UI elements in HOME's positions across screens. Side rails use
HOME's 256 px width and 10 px inner margins, with BACK spanning the same
236 px as other full-width rail controls. Use the shared button renderer for
every clickable control, including receiver and contact tiles. Reuse
`ui_chrome` for BACK geometry and the 18 px lower-left UTC clock; decoder
status messages use HOME's two-row footer, not miniature custom footers.
Full-width workspaces place navigation directly on the selected theme side;
rail-based workspaces use the existing rail composition and touch mapping.

Spectrum Analyzer uses a touch-first Survey → Signals → Investigate workflow.
Use full-width workspaces and one main chart at a time, including for its
waterfall. Primary touch controls use at least 20 px labels and 56 px hit
targets. Do not shrink the web sidebar into a native control rail. Preserve
an explicit return from investigation to the preceding survey or watch mode.
