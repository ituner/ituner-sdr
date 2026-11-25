# CM5 CPU monitoring

The `cm5-hang-watcher.service` samples every 10 seconds and appends to
`/var/log/ituner-sdr/hang-watcher.jsonl`. Monitoring does not require restarting
the UI. Per-core and process/thread counters were added on 18 November 2026.

- `cpu_core_ticks`: cumulative total, idle and I/O-wait ticks per core. Compare
  adjacent records from the same boot, skipping counter regressions and zero
  totals. Busy percentage is `100 * (delta_total - delta_idle - delta_iowait) /
  delta_total`.
- `cpu_attribution.top_processes`: up to eight busiest observed processes by
  interval CPU usage across all their threads. Includes PID, kernel name,
  start ticks (PID reuse protection), and `leader_last_cpu`.
- `cpu_attribution.top_ituner_threads`: up to twelve busiest observed iTuner
  threads, including TID, kernel name, start ticks and `last_cpu`.
- `cpu_percent`: percentage of one logical core's capacity over `interval_s`.
  A multithreaded process can exceed 100%. Process and thread totals overlap;
  do not add them together.

The first scan establishes a baseline. Only positive CPU deltas are logged.
Previous-scan state is replaced every interval, and output lists are bounded.
Reads use procfs directly, with no new per-process subprocesses or tracing.
Measured on the deployed CM5: about 10.5 ms CPU time per attribution scan of
236 process/thread entries, approximately 0.11% of one core at a 10-second
interval. Workload and process count can change this cost.

## Interpretation limits

Last CPU means the CPU on which the thread most recently executed, not where
it spent the entire interval. A process's leader CPU does not represent all
its threads. This is not an exact per-core application-time breakdown.
Tasks can migrate, disappear between scans, or fall outside the top lists.
Kernel names may be truncated or generic (for example, several Python threads
can have the same name); TIDs distinguish them but do not identify their
Python functions. Detailed residency attribution would require scheduler tracing.

See [Linux proc_pid_stat documentation](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html).

## Python thread names (19 November 2026)

The native UI now installs `UI/thread_names.py` at startup. Standard Python
threads publish their role once to their own Linux `comm` file. Existing named
workers retain their Python role (limited to 15 UTF-8 bytes by Linux); unnamed
workers fall back to the target's qualified name. This adds no periodic work.

Key labels: `ui-main` (main UI), `waterfall-rx` (waterfall receiver), `audio-rx`
(audio receiver/processing), `asr-captions`, `callsign-decode`, `network-config`,
`receiver-home`, `globe-directory`, and `vfo-b-waterfall`.

This supersedes the generic-name limitation above for newly started standard
Python workers. Earlier log entries remain generic. Native-library threads
and subclasses overriding `Thread.run` are outside the naming hook; inherited
or library-provided names must not be interpreted as verified Python roles.
