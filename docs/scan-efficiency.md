# Scan efficiency and verification

Smart Scan and experimental Long Scan share a bounded feedback policy. It
learns from observations; it does not rewrite code or claim universal optimality.
The listening session remains separate from Long Scan.

## Protocol traffic

The first waterfall setup still sends all five required settings. Later view
changes send only changed wire values. Unchanged levels, compression and
interpolation stay on that connection; repeated identical requests send nothing.
Rate changes use the same cache, including restoration after a scan. A new
connection or authentication starts a fresh configuration lifetime. Failed
writes are not remembered as successful.

For 100 distinct view changes, the protocol benchmark reduces setup commands
from **500 to 104 (79.2%)**. Text payload falls from 8,600 to 2,264 bytes. With
six bytes of masked WebSocket framing per command, that is 11,600 to 2,888 bytes;
TCP/TLS overhead and keepalives are excluded. The previous callers already
suppressed identical views; the baseline does not inflate its count with polls.
Fewer commands do not imply an equal percentage reduction in wall-clock time.

Long Scan pauses its waterfall between cycles when at least three seconds remain.
It retains the paired connection and keepalives, discards late rows while paused,
and resumes with a rate command rather than reconnecting or reinitializing every
setting. Idle silence is not a stalled scan or evidence that a station stopped.
The listening waterfall is never paused by this dedicated-session optimization.

## Resolution and scheduling

Each receiver, allocation and receiver geometry gets an initial full narrow
reference sweep. At 30 MHz receiver bandwidth that is zoom eight, about 117 kHz
per view. Only bands that need fewer views can try zoom seven, about 234 kHz.
The wider setting is capped at 250 Hz per bin and never goes wider than zoom seven.

The planner compares the cost of a wider sweep **plus its expected local
follow-ups** with a full narrow sweep. Weak stations, close neighbors and
unexplained AM-like energy can get local rechecks instead of forcing the entire
band to stay narrow. Bare carriers alone do not request an AM follow-up. Two
repeated nonqualifying observations are a scheduling hint; they never become a
station count, and compulsory reference audits can requalify the frequency.

A wider pass that loses a recent station or leaves a new uncertainty must finish
its targeted checks before the band is considered complete. Targets sharing a
usable RF span share a view. The same view budget can use zoom nine or ten when
the targets fit, improving frequency resolution. If a finer view does not confirm
a suspected signal, baseline-resolution reference contexts are checked before
absence is accepted. Extra contexts stop when the specific uncertainty is
positively resolved. A failed measurement remains incomplete.

Unexpected follow-ups impose a three-reference-sweep cooldown. At most three
successful wider sweeps precede a compulsory full narrow audit. An in-memory
two-hour watch retains previously qualified frequencies through fading, without
counting an absent station as present or refreshing its age on an empty pass.
New very weak stations can still first appear during a later narrow audit;
this is not a guarantee of equal live recall on every sweep.

A timeout gets one bounded retry of the same view, restarting useful observation
without another frequency command. Repeated failure remains an uncertainty gap.
Finer confirmed tuning estimates are retained instead of being overwritten by
coarser measurements; row identity and listening remain stable.

The AM detector checks farther from the carrier when a strong wide station fills
the usual nearby noise reference. A mirrored shallow line must match geometry,
relative strength, temporal variation, and the parent's programme-sideband ratio
before it is treated as an image. Correlation from parent fading alone is
insufficient. Later parent evidence can remove an earlier sideband candidate;
a playing row offers its existing centering action without retuning audio.
A channel can requalify after suppression when an independent signal starts.

Every accepted pass covers the whole allocation. Productive windows are visited
first, using nearest-view distance to break ties; none are omitted. Smart Scan
retains its selected-band return after every four background band sweeps. Both
scanners rank bands using confirmed yield per required view and broad activity
hints. Long Scan starts with a broad survey rather than always beginning at LW,
then uses its measured results on subsequent cycles. Quiet bands remain in every
cycle. Receiver changes cannot reuse another receiver's learned profile, while
tuning listening audio within Smart Scan does not invalidate that profile.

Observation dwell, matching-frame validation, the additional response margin,
and interrupted-observation handling remain intact. A wider overview never
counts as a detected station or as a measured empty band.

## Reproducing the comparison

Run from the checkout, with numpy installed:

```sh
python3 scripts/benchmark-smart-scan.py --output /tmp/scan-audit.json --seeds 8 --passes 12 --workers 3 --extended
```

The baseline is fixed zoom-eight scanning with the previous five-command setup.
Both policies use a two-second observation dwell. By default the detector is
shared, isolating scheduling and resolution. For full old/new quality audits,
`--baseline-source` points to the saved installed `smart_seek.py`; those audits
also compare the detector changes. The live harness freezes the installed
baseline separately from the staged implementation.
The benchmark drives the real scan engine, including partial publication,
response budgets, narrower fallback and compulsory audits. It records confirmed
frequencies, false detections, lost baseline detections, first-result time,
complete coverage, view changes and setup commands. Source hashes are saved.

The deterministic RF **power-spectrum model** keeps carrier and sideband offsets
in hertz and scales noise power with bin width. It is not an IQ receiver emulator
or calibrated propagation model. Scenes include sparse carriers, 5 kHz neighbors,
weak fading, edges, bare carriers, noise and mixed strengths. The extended audit
adds broadcasts starting and stopping, longer fading changes, unmodulated spurs
and impulsive interference. Response delays of 50, 250 and 700 ms are modeled;
reported scan times are simulated observation/arrival times, not measured WAN
latency. Setup command counts come from the actual command emitter.

Simultaneous on-air comparisons used two independent receiver sessions on the
selected Romania Kiwi, with listening unchanged. The baseline loaded the installed
implementation; the experimental channel used the staged policy. Captures and
source hashes were saved. These representative live runs used successive guarded
revisions while tuning the policy:

| Band | Complete pairs | Baseline mean | Guarded mean | Setup commands |
| --- | ---: | ---: | ---: | ---: |
| Quiet 13 m | 5 | 11.91 s | 8.42 s | 100 → 18 |
| Quiet 19 m | 6 | 22.80 s | 19.91 s | 240 → 46 |
| Crowded 49 m | 6 | 14.44 s | 14.06 s | 150 → 34 |

One incomplete baseline 13 m pass is excluded from that paired comparison.
Neither channel detected stations on the two quiet bands. The crowded band
showed no convincing time gain because the guards kept detailed checks. An
unguarded zoom-seven experiment took 8.62 s versus 14.14 s, but its weaker-signal
lists varied; it is not the shipped policy.

The independent final cohorts use different noise/fading seeds and twelve passes,
including broadcasts starting/stopping, impulses and strong mirrored music lobes.
The fine-confirmation fallback reconciled the initial weak-signal discrepancy.
Both the repeated cohort and a second unseen cohort retained every baseline
true detection, with no extra false detections and complete coverage. The model
still misses some densely packed/weak signals in both versions; no live audio
classification or absolute detection guarantee is claimed.

An identical-packet replay of six live narrow sweeps retained all 42 baseline
detections, eliminating cross-channel fading as a comparison confound. A separate
simultaneous finer-reference check found roughly 60–80 Hz differences where the
reference qualified. That is a relative RF reference, not an absolute frequency
standard or an assertion that nominal channel rounding is correct.

On-device checks also exercise a local WebSocket peer: an active higher band is
visited first, every band receives full coverage, invariant settings are sent once,
idle pause/resume works, and listening remains unchanged. Injected disconnects
verify reconnect and uncertainty gaps in saved history.

## What can be proved

For a fixed view span `S`, required overlap `O = 16 kHz`, and padded allocation
width `W`, the planner needs
`N = max(1, 1 + ceil(max(0, W - S) / (S - O)))` views. No arrangement with that
span and at least that overlap can cover more than `S + (N - 1) * (S - O)`.
The planner attains this geometric bound. For targeted follow-ups, greedily
choosing the furthest-reaching reference-grid view covering the leftmost suspect
minimizes that grid subset. Safety fallback contexts can deliberately add views
when the first confirmation is inconclusive.
A changed remote view likewise needs
at least one view command; the cached emitter reaches that bound after setup.

Neither result proves the best resolution, dwell or scheduling for unknown,
changing radio signals. Bandit regret guarantees require assumptions such as
stationary independent rewards that fading and scheduled broadcasts do not
satisfy. The policy therefore uses bounded trials, forced coverage and reference
checks, rather than claiming a theorem guarantees its live detection quality.

Primary protocol references: [Kiwi waterfall command handling](https://github.com/jks-prv/KiwiSDR/blob/master/rx/rx_waterfall_cmd.cpp),
[waterfall speed definitions](https://github.com/jks-prv/KiwiSDR/blob/master/rx/rx_waterfall.h),
and [server idle-waterfall handling](https://github.com/jks-prv/KiwiSDR/blob/master/rx/rx_waterfall.cpp).
For the assumptions behind classical bandit guarantees, see
[Auer, Cesa-Bianchi and Fischer, 2002](https://people.eecs.berkeley.edu/~russell/classes/cs294/s11/readings/Auer%2Bal:2002.pdf).
