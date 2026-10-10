# Local KiwiSDR discovery and live occupancy

Local `.local` names use multicast discovery. A Wi-Fi extender, isolated guest
network or multicast filter can interrupt discovery even while the receiver's
IP address remains reachable. This is separate from CPU load and available
Kiwi listening channels.

The shared connection layer covers the main radio, WSPR, SSTV, Hell, QRSS and CW.
It never fetches `/status`, including for local address recovery. Normal local
name discovery runs off the connection thread, with at most a one-second wait
and one outstanding lookup per hostname/port. Discovered private addresses are
cached in memory briefly; fresh lookups learn DHCP changes. Old persistent
address files are no longer used: without an identity check, a stale address
might belong to a different receiver.

If discovery fails, the app reports the failure. Reserve the Kiwi's IP in the
router and select that LAN IP when multicast cannot cross a Wi-Fi extender.
The extender should bridge to the same LAN and permit mDNS (UDP 5353). No LAN
scan, router changes, system DNS changes or `/etc/hosts` edits are performed.
Host/Origin headers and TLS hostname verification retain the selected hostname.

After successful Kiwi authentication, the existing sound/waterfall connection
sends `SET GET_USERS`, and parses `MSG user_cb` replies. All streams to the same
selected receiver URL share one 2.5-second request schedule within the app,
including all digital decoders. No new socket or listening slot is allocated.
The response includes every channel; the presence of the `n` field identifies
an occupied channel, including anonymous/private users. Counts expire after
15 seconds without replies; directory metadata is the fallback. Paused or
stopped sessions do not open a connection to obtain occupancy. Different URL
aliases are not automatically treated as one receiver.

This implements the official Kiwi browser client's existing protocol:
https://github.com/jks-prv/KiwiSDR/blob/master/web/kiwi/kiwi.js
https://github.com/jks-prv/KiwiSDR/blob/master/rx/rx_util.cpp

Receiver location comes from saved directory metadata or configured WSPR
reporter settings, not a status fetch. No reporting identity is changed.

Validation covers authenticated message handling, shared request cadence,
anonymous users, malformed responses, stale counts, zero standalone status
requests, bounded local DNS, and no stale-address fallback.
