# Detecting station location

Open **SYSTEM → RADIO / USER INFORMATION → Location → Detect location**.
The saved coordinates remain active until **Confirm location** is tapped.
Cancel leaves the station unchanged. Manual coordinate entry remains available.

Detection uses the public internet address through `https://api.ipapi.is/` over
HTTPS. It works on Wi-Fi or Ethernet; it does not scan nearby Wi-Fi networks,
read phone location, or send saved coordinates or station identity. The preview
identifies the provider, approximate place, coordinates, proposed Maidenhead grid,
and estimate age. The anonymous provider does not report an accuracy radius;
the UI labels it unavailable. A VPN or ISP gateway can locate a different city.

Confirmation saves latitude and longitude through the shared station profile,
updates its grid and local consumers, and disables automatic GPS position
updates so the accepted saved location is used. The confirmation explains this.
GPS automation can be re-enabled under **GPS & movement**. Height and identity
fields are not overwritten. Other unsaved edits still require **Save radio information**.

One short-lived `location-lookup` worker performs the request with an eight-second
network timeout. There is no polling. Estimates are cached for 24 hours in
`location-estimate.json` beside `radio-user.json`, with owner-only permissions.
**Refresh estimate** requests a new result, with a one-minute minimum interval.
Rate-limit errors pause new requests for 24 hours in the running process.
No failed request changes the station position.

Provider documentation: https://ipapi.is/free-tier.html
