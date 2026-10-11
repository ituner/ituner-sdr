"""Protocol-neutral receiver records and capability contracts.

This module is intentionally dependency-free: it imports no display, audio, or
network code so that the OpenGL renderer, the health worker, and future tools
can all share one truthful description of a receiver.  A receiver record keeps
the *transport* (``protocol``) separate from the *browser segment*
(``source_group``); a LAN Kiwi is therefore ``protocol="kiwi"`` but
``source_group="local"`` and never enters the USB local-device worker.

The contract is small on purpose: a control is either allowed, or rejected with
one human-readable reason.  That reason is the message the Home UI shows when a
fixed or unavailable control is touched, so no input is ever silently ignored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

# Browser segments, in priority order.  ``all`` is the combined view and is
# always selected last so the five segments remain readable on 1280x800.
SOURCE_FILTERS = ("local", "kiwi", "openwebrx", "fmdx", "all")
SOURCE_PRIORITY = {name: index for index, name in enumerate(SOURCE_FILTERS[:-1])}
PROTOCOLS = ("kiwi", "openwebrx", "local", "fmdx")

# Default segment for each transport.  A record may override this (a LAN Kiwi
# reports ``protocol="kiwi"`` with ``source_group="local"``).
PROTOCOL_SOURCE_GROUP = {
    "kiwi": "kiwi",
    "openwebrx": "openwebrx",
    "local": "local",
    "fmdx": "fmdx",
}

KIWI_MODES = ("AM", "SAM", "LSB", "USB", "CW", "NBFM", "NFM", "WFM", "IQ")
OPENWEBRX_MODES = ("AM", "SAM", "LSB", "USB", "CW", "NBFM", "NFM", "WFM")
LOCAL_MODES = ("AM", "NFM", "WFM", "USB", "LSB")
FMDX_MODES = ("FM",)

# The three exact reasons FM-DX must explain when a shared-server control is
# touched without an explicit, session-only acknowledgement.
FMDX_SHARED_FREQUENCY_MESSAGE = "Shared tuner: changing frequency affects every listener"
FMDX_FIXED_PASSBAND_MESSAGE = "Fixed passband on this receiver"
FMDX_FIXED_MODE_MESSAGE = "FM mode is controlled by the shared receiver"
FMDX_FIXED_SPECTRUM_MESSAGE = "Audio spectrum is fixed to 20 kHz"


def _humanize(control: str) -> str:
    return str(control).replace("_", " ").title()


@dataclass(frozen=True)
class ControlDecision:
    """Whether one control may change state, and why not when it may not."""

    allowed: bool
    message: str = ""


@dataclass(frozen=True)
class ReceiverCapabilities:
    """Truthful control and coverage contract for one receiver type."""

    protocol: str
    label: str
    controls: frozenset = frozenset()
    fixed_controls: Mapping = field(default_factory=dict)
    modes: tuple = ()
    waterfall_kind: str = "rf"
    control_scope: str = "per_session"
    frequency_ranges_khz: tuple = ()
    source_span_khz: float = 0.0

    def decide(self, control: str, *, shared_control_acknowledged: bool = False) -> ControlDecision:
        """Resolve one control against this contract.

        A shared-server frequency control stays blocked until the operator
        explicitly acknowledges it for the current session; every other scope
        ignores that flag.
        """
        control = str(control)
        if control in self.controls:
            return ControlDecision(True)
        if (
            control == "frequency"
            and self.control_scope == "shared_server"
            and shared_control_acknowledged
        ):
            return ControlDecision(True)
        reason = self.fixed_controls.get(control)
        if reason is None:
            reason = f"{_humanize(control)} is unavailable on this receiver"
        return ControlDecision(False, reason)

    def supports_frequency(self, frequency_khz: float) -> bool:
        if not self.frequency_ranges_khz:
            return True
        try:
            value = float(frequency_khz)
        except (TypeError, ValueError):
            return False
        return any(low <= value <= high for low, high in self.frequency_ranges_khz)

    def tuning_bounds(self):
        if not self.frequency_ranges_khz:
            return None
        return self.frequency_ranges_khz[0][0], self.frequency_ranges_khz[-1][1]

    @classmethod
    def kiwi(cls, *, controls=None, modes=KIWI_MODES) -> "ReceiverCapabilities":
        return cls(
            protocol="kiwi",
            label="KIWI",
            controls=frozenset(controls or (
                "frequency", "mode", "passband", "waterfall_pan",
                "waterfall_zoom", "agc", "squelch", "volume",
            )),
            modes=tuple(modes),
            waterfall_kind="rf",
            control_scope="per_session",
        )

    @classmethod
    def openwebrx(cls, *, controls=None, modes=OPENWEBRX_MODES,
                  frequency_ranges_khz=(), source_span_khz=0.0) -> "ReceiverCapabilities":
        return cls(
            protocol="openwebrx",
            label="OPENWEBRX",
            controls=frozenset(controls or (
                "frequency", "mode", "passband", "waterfall_pan",
                "waterfall_zoom", "squelch", "volume",
            )),
            modes=tuple(modes),
            waterfall_kind="rf",
            control_scope="per_session",
            frequency_ranges_khz=tuple(frequency_ranges_khz),
            source_span_khz=float(source_span_khz),
        )

    @classmethod
    def local_device(cls, *, label="LOCAL", controls=None, modes=LOCAL_MODES,
                     fixed_controls=None, waterfall_kind="rf",
                     frequency_ranges_khz=(), source_span_khz=0.0) -> "ReceiverCapabilities":
        device_controls = set(controls or ("frequency", "mode", "volume", "squelch", "waterfall_zoom"))
        reasons = {
            "passband": f"Passband is set by {label}",
            "agc": f"AGC is set by {label}",
        }
        if fixed_controls:
            reasons.update(fixed_controls)
        return cls(
            protocol="local",
            label=label,
            controls=frozenset(device_controls),
            fixed_controls=dict(reasons),
            modes=tuple(modes),
            waterfall_kind=waterfall_kind,
            control_scope="per_session",
            frequency_ranges_khz=tuple(frequency_ranges_khz),
            source_span_khz=float(source_span_khz),
        )

    @classmethod
    def fixed_audio(cls, protocol="fmdx", label="FM-DX", *, controls=None,
                    modes=FMDX_MODES, control_scope="shared_server") -> "ReceiverCapabilities":
        """A receiver whose audio path is derived and whose tuning is shared.

        FM-DX exposes only volume; frequency, mode, passband, and spectrum pan
        are fixed or shared and explain themselves when touched.
        """
        return cls(
            protocol=str(protocol),
            label=label,
            controls=frozenset(controls if controls is not None else ("volume",)),
            fixed_controls={
                "frequency": FMDX_SHARED_FREQUENCY_MESSAGE,
                "mode": FMDX_FIXED_MODE_MESSAGE,
                "passband": FMDX_FIXED_PASSBAND_MESSAGE,
                "waterfall_pan": FMDX_FIXED_SPECTRUM_MESSAGE,
                "waterfall_zoom": FMDX_FIXED_SPECTRUM_MESSAGE,
                "agc": "Gain is controlled at the shared receiver",
                "squelch": "Squelch is controlled at the shared receiver",
            },
            modes=tuple(modes),
            waterfall_kind="audio_spectrum",
            control_scope=str(control_scope),
        )


def kiwi_directory_channels(mode):
    """Advertised firmware capacity, not free channels or a connectivity test."""
    match = re.fullmatch(r"rx([0-9]+)[._]wf([0-9]+)", str(mode or "").strip().lower())
    if not match:
        return None, None
    audio, waterfall = map(int, match.groups())
    if not 1 <= audio <= 64 or not 0 <= waterfall <= audio:
        return None, None
    return audio, waterfall


def normalize_kiwi_directory_mode(mode):
    audio, waterfall = kiwi_directory_channels(mode)
    return f"rx{audio}.wf{waterfall}" if audio is not None else ""


@dataclass(frozen=True)
class ReceiverRecord:
    """One receiver, independent of how it is rendered or probed."""

    id: str
    protocol: str
    source_group: str
    endpoint: str
    name: str
    location: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    capabilities: ReceiverCapabilities = field(
        default_factory=lambda: ReceiverCapabilities.kiwi()
    )
    listeners_used: Optional[int] = None
    listeners_total: Optional[int] = None
    favorite: bool = False
    directory_mode: str = ""

    @property
    def audio_channels(self):
        return kiwi_directory_channels(self.directory_mode)[0]

    @property
    def waterfall_channels(self):
        return kiwi_directory_channels(self.directory_mode)[1]

    def legacy_row(self):
        return legacy_station_row(self)


def _as_float(value) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _as_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def canonical_endpoint(endpoint: str) -> str:
    """Cheap, dependency-free endpoint canonicalization for stable ids."""
    return str(endpoint or "").strip().rstrip("/")


def infer_protocol(endpoint: str, declared=None) -> str:
    """Pick a transport for a record that does not declare one."""
    if declared:
        return str(declared).lower()
    value = str(endpoint or "").lower()
    if value.startswith(("owrx://", "owrxs://")):
        return "openwebrx"
    if value.startswith(("local://", "usb://")):
        return "local"
    return "kiwi"


def capabilities_for(protocol: str, *, label=None, control_scope=None,
                     controls=None, modes=None, waterfall_kind=None,
                     frequency_ranges_khz=(), source_span_khz=0.0) -> ReceiverCapabilities:
    """Build the default contract for a protocol, honoring record overrides."""
    protocol = str(protocol).lower()
    if protocol == "fmdx":
        caps = ReceiverCapabilities.fixed_audio(
            "fmdx",
            label or "FM-DX",
            controls=controls,
            modes=tuple(modes) if modes else FMDX_MODES,
            control_scope=control_scope or "shared_server",
        )
    elif protocol == "openwebrx":
        caps = ReceiverCapabilities.openwebrx(
            controls=controls,
            modes=tuple(modes) if modes else OPENWEBRX_MODES,
            frequency_ranges_khz=frequency_ranges_khz,
            source_span_khz=source_span_khz,
        )
    elif protocol == "local":
        caps = ReceiverCapabilities.local_device(
            label=label or "LOCAL",
            controls=controls,
            modes=tuple(modes) if modes else LOCAL_MODES,
            waterfall_kind=waterfall_kind or "rf",
            frequency_ranges_khz=frequency_ranges_khz,
            source_span_khz=source_span_khz,
        )
    else:
        caps = ReceiverCapabilities.kiwi(
            controls=controls,
            modes=tuple(modes) if modes else KIWI_MODES,
        )
    if label is not None and protocol not in ("fmdx",):
        caps = ReceiverCapabilities(
            protocol=caps.protocol, label=str(label), controls=caps.controls,
            fixed_controls=caps.fixed_controls, modes=caps.modes,
            waterfall_kind=caps.waterfall_kind, control_scope=caps.control_scope,
            frequency_ranges_khz=caps.frequency_ranges_khz, source_span_khz=caps.source_span_khz,
        )
    if control_scope is not None:
        caps = ReceiverCapabilities(
            protocol=caps.protocol, label=caps.label, controls=caps.controls,
            fixed_controls=caps.fixed_controls, modes=caps.modes,
            waterfall_kind=caps.waterfall_kind, control_scope=str(control_scope),
            frequency_ranges_khz=caps.frequency_ranges_khz, source_span_khz=caps.source_span_khz,
        )
    if waterfall_kind is not None:
        caps = ReceiverCapabilities(
            protocol=caps.protocol, label=caps.label, controls=caps.controls,
            fixed_controls=caps.fixed_controls, modes=caps.modes,
            waterfall_kind=str(waterfall_kind), control_scope=caps.control_scope,
            frequency_ranges_khz=caps.frequency_ranges_khz, source_span_khz=caps.source_span_khz,
        )
    return caps


def normalize_receiver(record: Mapping) -> ReceiverRecord:
    """Coerce a raw mapping (directory row, cache row, static source) to a record."""
    if isinstance(record, ReceiverRecord):
        return record
    endpoint = str(record.get("endpoint") or record.get("server") or "").strip()
    protocol = infer_protocol(endpoint, record.get("protocol") or record.get("receiver_type"))
    source_group = str(record.get("source_group") or PROTOCOL_SOURCE_GROUP.get(protocol, protocol))
    if source_group not in SOURCE_PRIORITY:
        source_group = PROTOCOL_SOURCE_GROUP.get(protocol, protocol)
    name = str(record.get("name") or "Receiver").strip() or "Receiver"
    location = str(record.get("location") or record.get("loc") or "").strip()

    capabilities = record.get("capabilities")
    if not isinstance(capabilities, ReceiverCapabilities):
        frequency_ranges = record.get("frequency_ranges_khz") or ()
        capabilities = capabilities_for(
            protocol,
            label=record.get("label"),
            control_scope=record.get("control_scope"),
            controls=record.get("controls"),
            modes=record.get("modes"),
            waterfall_kind=record.get("waterfall_kind"),
            frequency_ranges_khz=frequency_ranges,
            source_span_khz=record.get("source_span_khz") or 0.0,
        )

    return ReceiverRecord(
        id=str(record.get("id") or f"{protocol}:{canonical_endpoint(endpoint)}"),
        protocol=protocol,
        source_group=source_group,
        endpoint=endpoint,
        name=name,
        location=location,
        latitude=_as_float(record.get("latitude", record.get("lat"))),
        longitude=_as_float(record.get("longitude", record.get("lon"))),
        capabilities=capabilities,
        listeners_used=_as_int(record.get("listeners_used", record.get("used"))),
        listeners_total=_as_int(record.get("listeners_total", record.get("total"))),
        favorite=bool(record.get("favorite", False)),
        directory_mode=normalize_kiwi_directory_mode(record.get("directory_mode") or record.get("mode")) if protocol == "kiwi" else "",
    )


def legacy_station_row(record: ReceiverRecord):
    """Preserve the legacy station tuple shape during migration.

    Trailing latitude/longitude and the receiver-type marker are retained so
    every existing consumer (broadcast identity, distance, map focus, health)
    keeps receiving the same facts after the catalog lands.
    """
    return (
        record.name, record.location, record.endpoint,
        record.listeners_used, record.listeners_total,
        record.latitude, record.longitude, record.protocol,
    ) + ((record.directory_mode,) if record.directory_mode else ())


def records_from_kiwi_directory(rows: Iterable[Sequence]) -> tuple:
    """Adapt legacy Kiwi directory tuples into records."""
    records = []
    for row in rows or ():
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        name = row[0]
        location = row[1] if len(row) > 1 else ""
        endpoint = row[2]
        used = row[3] if len(row) > 3 else None
        total = row[4] if len(row) > 4 else None
        lat = row[5] if len(row) > 5 else None
        lon = row[6] if len(row) > 6 else None
        declared = row[7] if len(row) > 7 else None
        records.append(normalize_receiver({
            "name": name, "location": location, "server": endpoint,
            "used": used, "total": total, "lat": lat, "lon": lon,
            "protocol": infer_protocol(endpoint, declared),
            "directory_mode": row[8] if len(row) > 8 else "",
        }))
    return tuple(records)


def records_from_fmdx_directory(receivers: Iterable[Mapping]) -> tuple:
    """Adapt the FM-DX directory's receiver dicts into records."""
    records = []
    for receiver in receivers or ():
        if not isinstance(receiver, Mapping):
            continue
        endpoint = receiver.get("server") or receiver.get("endpoint")
        if not endpoint:
            continue
        records.append(normalize_receiver({
            "name": receiver.get("name"),
            "location": receiver.get("location"),
            "server": endpoint,
            "lat": receiver.get("lat"),
            "lon": receiver.get("lon"),
            "used": receiver.get("used"),
            "total": receiver.get("total"),
            "protocol": "fmdx",
            "source_group": "fmdx",
            "frequency_ranges_khz": (
                (receiver.get("minimum_khz", 64_000.0), receiver.get("maximum_khz", 108_000.0)),
            ),
        }))
    return tuple(records)


STATIC_SOURCES_PATH = Path(__file__).with_name("receiver_sources.json")


def load_static_sources(path=None) -> tuple:
    """Load the built-in OpenWebRX/local metadata schema."""
    path = Path(path) if path is not None else STATIC_SOURCES_PATH
    try:
        payload = json.loads(path.read_text())
    except (OSError, TypeError, ValueError):
        return ()
    receivers = payload.get("receivers") if isinstance(payload, Mapping) else None
    if not isinstance(receivers, list):
        return ()
    records = []
    for item in receivers:
        if isinstance(item, Mapping) and item.get("endpoint"):
            records.append(normalize_receiver(item))
    return tuple(records)


def records_from_static_sources(path=None) -> tuple:
    return load_static_sources(path)


def sort_receivers(records: Iterable[ReceiverRecord]) -> tuple:
    """Stable priority order: LAN, Kiwi, OpenWebRX, FM-DX."""
    def key(record: ReceiverRecord):
        group = record.source_group if record.source_group in SOURCE_PRIORITY else record.protocol
        return SOURCE_PRIORITY.get(group, len(SOURCE_FILTERS))

    return tuple(sorted(records, key=key))


def filter_receivers(records: Iterable[ReceiverRecord], source: str = "all") -> tuple:
    """Return one browser segment's records, always priority-sorted."""
    source = str(source or "all").lower()
    if source not in SOURCE_FILTERS:
        source = "all"
    if source == "all":
        return sort_receivers(records)
    selected = (record for record in records if record.source_group == source)
    return sort_receivers(selected)


def merge_catalogs(*groups) -> tuple:
    """Merge every input into one deduplicated, priority-sorted catalog."""
    merged = []
    seen_ids = set()
    seen_endpoints = set()
    for group in groups:
        for item in group or ():
            record = normalize_receiver(item)
            endpoint = canonical_endpoint(record.endpoint)
            if not endpoint:
                continue
            if record.id in seen_ids or endpoint in seen_endpoints:
                # Preserve first-source labels/ordering while filling missing
                # advertised capacity from another directory for the same URL.
                if record.directory_mode:
                    for index, existing in enumerate(merged):
                        if canonical_endpoint(existing.endpoint) == endpoint and existing.protocol == "kiwi" and not existing.directory_mode:
                            merged[index] = replace(existing, directory_mode=record.directory_mode)
                            break
                continue
            seen_ids.add(record.id)
            seen_endpoints.add(endpoint)
            merged.append(record)
    return sort_receivers(merged)


def load_receiver_catalog(*, kiwi_rows=(), openwebrx_rows=(), local_rows=(),
                          fmdx_receivers=(), static_path=None) -> tuple:
    """Build the one shared receiver catalog from every input adapter."""
    static_records = load_static_sources(static_path)
    return merge_catalogs(
        records_from_kiwi_directory(kiwi_rows),
        records_from_kiwi_directory(openwebrx_rows),
        static_records,
        tuple(normalize_receiver(item) for item in local_rows),
        records_from_fmdx_directory(fmdx_receivers),
    )


def migrate_remembered_view(payload: Mapping) -> dict:
    """Upgrade a remembered receiver view to the stable-id schema.

    Legacy ``receiver_type`` and tuple-based favorites keep loading for one
    migration cycle.  FM-DX shared-control acknowledgement is *never* restored:
    the migrated view always starts read-only.
    """
    payload = payload if isinstance(payload, Mapping) else {}
    endpoint = str(payload.get("server") or payload.get("endpoint") or "").strip()
    protocol = infer_protocol(endpoint, payload.get("receiver_type") or payload.get("protocol"))
    canonical = canonical_endpoint(endpoint)
    if protocol == "fmdx":
        receiver_id = f"fmdx:{canonical}"
    else:
        receiver_id = str(payload.get("receiver_id") or f"{protocol}:{canonical}")
    migrated = {
        "receiver_id": receiver_id,
        "protocol": protocol,
        "endpoint": endpoint,
        "frequency_khz": _as_float(payload.get("frequency_khz")),
        "mode": payload.get("mode"),
        "zoom": payload.get("zoom"),
        "source": payload.get("source") if payload.get("source") in SOURCE_FILTERS else "kiwi",
        "view": payload.get("view") if payload.get("view") in ("list", "map") else "list",
        "shared_control": False,
    }
    if migrated["frequency_khz"] is None:
        migrated.pop("frequency_khz")
    if migrated["mode"] is None:
        migrated.pop("mode")
    if migrated["zoom"] is None:
        migrated.pop("zoom")
    return migrated


def self_test() -> None:
    assert SOURCE_FILTERS == ("local", "kiwi", "openwebrx", "fmdx", "all")
    caps = ReceiverCapabilities.fixed_audio("fmdx", "FM-DX")
    assert caps.decide("passband").message == FMDX_FIXED_PASSBAND_MESSAGE
    record = normalize_receiver({
        "id": "fm:test", "protocol": "fmdx", "endpoint": "https://fm.test",
        "name": "FM test", "control_scope": "shared_server",
    })
    assert record.capabilities.decide("frequency").message == FMDX_SHARED_FREQUENCY_MESSAGE
    assert record.capabilities.decide(
        "frequency", shared_control_acknowledged=True
    ).allowed


if __name__ == "__main__":
    self_test()
    print("receiver_catalog self-test passed")
