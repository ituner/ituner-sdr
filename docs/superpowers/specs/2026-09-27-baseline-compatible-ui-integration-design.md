# Baseline-Compatible UI Integration Design

## Purpose

Extend PR #11 with the previously developed icon refresh, screen-layout improvements, and sidebar-navigation consistency while preserving every accepted behavior in the current `ituner/ituner-sdr` main branch.

The implementation must adapt the earlier work to the current code. It must not replace `UI/kiwi_gl_display.py` with an older version or reintroduce obsolete installation, display, receiver, or runtime behavior.

## Source material

The intended behavior comes from three earlier commits:

- `08588f7` — refreshed menu icons, consistent icon bounds, Apps naming, and muted-audio artwork.
- `a2f5c64` — unified mode selection and sidebar navigation.
- `c71268f` — unified menus and enlarged workspace layouts.

These commits are references, not patches to apply wholesale. Their relevant behavior will be transplanted into the current PR #11 branch function by function.

## Scope

### Included

- Refreshed SVG menu-icon sources and synchronized PNG runtime assets.
- Consistent icon sizing, padding, selection treatment, and muted-audio icon switching.
- The Apps label and icon where the current internal tests/apps destination is exposed to the operator.
- Unified Home and Settings sidebar conventions.
- A shared bottom-positioned Back control for right-side drawers.
- Clear navigation labels, including `MODES`, `BACK`, and `PASSBAND` where applicable.
- Reusable two-line sidebar buttons for controls with a category and active value.
- Parent-aware return behavior for screens opened from Home or Settings.
- Enlarged workspace layouts that fit the current 800×1280 display baseline.
- Visual enlargement and reorganization of the Constellation screen without adding new map interaction behavior.
- Focused regression coverage for assets, geometry, navigation, and current receiver integrations.

### Deferred

- Knob controllers, input adapters, focus overlays, or knob-specific routing.
- Physical knob-device integration.
- New map or globe navigation mechanics.
- Changes to map gestures, map selection behavior, or map performance behavior solely for this work.

## Compatibility rules

Current upstream behavior takes precedence whenever an older design conflicts with the accepted baseline. The following must remain intact:

- CM5 application-only installation and the legacy installation path.
- Current 800×1280 logical geometry, display orientation handling, and seeded display defaults.
- KiwiSDR, OpenWebRX, local RTL-SDR, and FM-DX receiver behavior.
- Current audio, waterfall, spectrum, captions, callsign, and station-health paths.
- Current runtime dependency and model provisioning.
- Existing touch and mouse behavior except where a navigation control is deliberately moved and its hitbox is moved with it.

No old full-file version may replace a current production file. Integration is performed at the asset, helper, screen, and event-routing levels.

## Architecture

### Icon layer

The refreshed SVG artwork is the editable source. Matching PNG files remain the runtime assets consumed by the current renderer.

The implementation will preserve current icon identifiers unless the intended earlier design explicitly introduces an additional identifier such as `apps` or `audio_muted`. Rendering continues to use the existing texture loading and fallback paths.

Both runtime asset locations used by the installers must contain synchronized icon files. Tests will verify required names and matching image dimensions. The audio navigation item selects the muted icon only when the existing muted state is active.

### Layout layer

Reusable geometry helpers will define:

- The shared drawer Back target.
- Drawer headings and explanatory text lanes.
- Two-line navigation buttons.
- Settings leaf sidebars.
- Screen-specific enlarged workspace bounds.

Screens will consume these helpers rather than copying coordinates. Drawing and hit testing must use the same boxes.

The accepted display dimensions, waterfall canvas, orientation transformations, and upstream default preferences remain unchanged. Enlargement applies only within each screen's available workspace.

### Navigation layer

Navigation keeps explicit parent information for destinations that can be opened from more than one surface. A leaf screen opened from Settings returns to Settings; the same leaf opened from Home returns to Home.

Home, Settings, and leaf screens retain their current destination behavior. The integration changes labels, arrangement, and return consistency without changing the receiver protocol selected or the worker launched.

The Constellation screen receives the earlier visual enlargement and hierarchy improvements. Its existing current-main touch, mouse, loading, and receiver behavior remains unchanged. No new map navigation state or gestures are introduced.

## State and data flow

1. Existing application state determines the active top-level or leaf screen.
2. Navigation activation records the destination's parent surface when the destination is shared.
3. The destination renders using current state plus reusable sidebar geometry.
4. Touch or mouse hit testing uses the same geometry returned to the renderer.
5. Back closes the leaf and restores its recorded parent surface.
6. Receiver and audio state continue through their existing protocol-specific workers without alteration from navigation presentation.

## Failure and fallback behavior

- Missing optional icon artwork falls back through the current icon-loading behavior rather than preventing startup.
- A legacy visual rule that does not fit current geometry is adapted or omitted; current controls may not be obscured.
- Parent state always has a safe Home fallback if a leaf is opened without an explicit parent.
- Layout helpers clamp or define boxes within the current logical display bounds.
- The implementation must not silently change a receiver protocol, tuning state, audio worker, or installation path.

## Commit structure

The implementation will follow the three existing FM-DX commits with separate reviewable commits:

1. Add and validate the refreshed icon assets.
2. Add shared layout/navigation helpers and adapt the Home and Settings surfaces.
3. Adapt leaf workspaces and the Constellation visual layout.
4. Add or update regression tests and operator documentation as required.

Mechanical asset synchronization may be included with the icon commit. Deferred functionality must not be included in any commit.

## Verification

The change is complete only when:

- All existing FM-DX UI and protocol tests pass.
- All current upstream dependency tests pass.
- Required icon assets exist in both runtime locations and pass dimension/name checks.
- Muted state selects the muted-audio icon.
- Home and Settings expose the intended labels and destinations.
- Every adapted drawer uses the shared Back geometry.
- Back returns to the parent that opened the destination.
- Rendered controls and hitboxes use identical geometry.
- Enlarged workspaces remain inside the 800×1280 logical bounds.
- Tests confirm that deferred knob and map-navigation modules or routes were not added.
- Python compilation, shell syntax, and `git diff --check` pass.
- The complete UI test suite passes in the available macOS environment.
- A desktop OpenGL smoke test is attempted and any environment limitation is reported explicitly.
- The final diff against `upstream/main` is reviewed to confirm that accepted upstream files and behavior were preserved.

## Acceptance criteria

The result should look like the earlier refreshed interface while behaving like the current upstream application. The maintainer must be able to review the interface work separately from the three FM-DX commits, and the diff must contain no deferred knob or map-navigation implementation.
