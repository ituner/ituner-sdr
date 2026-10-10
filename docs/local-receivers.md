# Local KiwiSDR recovery

Local `.local` names use multicast discovery. A Wi-Fi extender, isolated guest
network or multicast filter can interrupt discovery even while the receiver's
IP address remains reachable. This is separate from CPU load and available
Kiwi listening channels.

The shared Kiwi connection layer now remembers verified local receivers in
`~/.cache/ituner-sdr/local-receivers.json`. This covers the main radio's sound
and waterfall, WSPR, SSTV, Hell, QRSS and CW. These local identity requests
are allowed; the retired background receiver health service performs no probes.

- Normal local name discovery runs off the connection thread. Waiting for it
  is limited to one second, with one outstanding lookup per hostname/port.
- If discovery fails, a previously verified private/link-local address can be
  reused. The receiver's public `/status` must still identify a KiwiSDR with
  the same advertised name before a cached fallback is accepted. This is a
  wrong-receiver guard, not cryptographic device authentication.
- Fresh discovery can learn a changed DHCP address automatically. If the address
  changes while multicast remains blocked, recovery needs working discovery or
  a manually selected IP endpoint; the software does not scan the network.
- Cached fallback is rejected if the receiver is offline or its advertised
  name differs. If you intentionally renamed the receiver, restore discovery
  or remove its entry from the cache to relearn it.
- Host/Origin headers and TLS hostname verification retain the original name.
  Public receiver hosts and literal IP endpoints use their existing connection
  path. No router, system DNS, `/etc/hosts` or boot configuration changes are
  made by this feature.
- The cache survives application restarts. Writes are atomic and locked between
  processes; a read-only cache does not block otherwise working reception.
  `ITUNER_LOCAL_RECEIVERS_CACHE` optionally changes its location for testing.

For the most reliable home setup, reserve the Kiwi's IP address in the main
router's DHCP settings. The extender should bridge to the same LAN; guest/AP
client isolation can prevent device-to-device communication. If configurable,
allow local multicast/mDNS forwarding (UDP 5353). Settings depend on the
extender model; do not blindly disable unrelated router security options.

Validation:

```sh
python3 -m unittest discover -s tests -p 'test_local_receivers.py'
python3 -m unittest discover -s tests -p 'test_wspr_runtime.py'
```

Tests cover persistent fallback, changed DHCP address, wrong receiver rejection,
offline/corrupt caches, bounded stalled resolution, public endpoint behavior,
and valid Kiwi status responses. Deployment also checks real CM5-to-Kiwi status
and WebSocket recovery with a simulated `.local` lookup failure.
