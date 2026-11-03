"""Incremental RAM projections; published snapshots never share mutable containers.

Only the ADS-B receiver worker owns these accumulators. A row's WGS84, sky cell
and ground bearing are calculated once, rather than on every HTTP/touch poll.
"""
from bisect import bisect_left
from dataclasses import dataclass
import math

from adsb_footprint import SECTOR_DEGREES, footprint_from_peaks
from adsb_geometry import camera_hull, enu_positions
from station_profile import distance_m


@dataclass(frozen=True, slots=True)
class Position:
    stamp: float
    address: str
    east: float
    north: float
    up: float
    altitude: float
    rssi: object
    gnss: int
    label: str
    distance: float
    slant: float
    cell: object
    sector: object
    radius: float


def project_rows(rows, site, height, origin):
    """Prepare only newly inserted rows; preserve exact measurement statistics."""
    p = math.radians(site['lat'])
    prepared = []
    for row, (east, north, up) in zip(rows, enu_positions(rows, site, origin)):
        stamp, address, lat, lon, altitude, gnss, rssi, label, *_ = row
        distance = math.hypot(east, north)
        azimuth = math.degrees(math.atan2(east, north)) % 360
        elevation = math.degrees(math.atan2(up-(height or 0), distance))
        cell = (int(azimuth//4)*4, min(88, int(elevation//2)*2)) if elevation >= 0 else None
        q, delta = math.radians(lat), math.radians(lon-site['lon'])
        bearing = math.degrees(math.atan2(math.sin(delta)*math.cos(q),
                              math.cos(p)*math.sin(q)-math.sin(p)*math.cos(q)*math.cos(delta))) % 360
        radius = distance_m(site, dict(lat=lat, lon=lon))
        prepared.append(Position(stamp, address, round(east, 2), round(north, 2), round(up, 2),
                                 altitude, rssi, gnss, label, distance,
                                 math.hypot(distance, up-(height or 0)), cell,
                                 int(bearing//SECTOR_DEGREES) if radius >= 1 else None, radius))
    return prepared


class CoverageAccumulator:
    def __init__(self, site, height, since):
        self.site, self.height, self.since = site, height, since
        self.cursor = 0
        self.excluded = []
        self.clear()

    def clear(self):
        self.records = []
        self.points = []
        self.base = None
        self.addresses = []
        self.indexes = {}
        self.names = {}
        self.cells = {}
        self.peaks = {}
        self.sources = {'GNSS': 0, 'barometric approximation': 0}
        self.max_alt = self.max_range = None
        self.max_slant = 0
        self.rssi_min = self.rssi_max = None
        self.hull = []

    def advance(self, since):
        """Reuse rolling windows, including all their already projected positions."""
        self.since = since
        self.excluded = [stamp for stamp in self.excluded if stamp >= since]
        if self.records and self.records[0].stamp < since:
            cut = bisect_left(self.records, since, key=lambda r: r.stamp)
            retained = self.records[cut:]
            self.clear()
            self.append(retained)  # Expiry updates exact cells/extrema, without WGS84 work.

    def append(self, records):
        if not records:
            return
        if self.base is None:
            self.base = math.floor(records[0].stamp)
        for address in sorted({r.address for r in records} - self.indexes.keys()):
            self.indexes[address] = len(self.addresses)
            self.addresses.append(address)
        new_points = []
        for r in records:
            if r.label and r.stamp >= self.names.get(r.address, (-math.inf, ''))[0]:
                self.names[r.address] = (r.stamp, r.label)
            point = [round(r.stamp-self.base, 3), self.indexes[r.address], r.east, r.north,
                     r.up, r.altitude, r.rssi, r.gnss, r.label or r.address]
            new_points.append(point)
            self.sources['GNSS' if r.gnss else 'barometric approximation'] += 1
            if self.max_alt is None or r.altitude > self.max_alt.altitude:
                self.max_alt = r
            if self.max_range is None or r.distance > self.max_range.distance:
                self.max_range = r
            self.max_slant = max(self.max_slant, r.slant)
            if r.rssi is not None:
                self.rssi_min = r.rssi if self.rssi_min is None else min(self.rssi_min, r.rssi)
                self.rssi_max = r.rssi if self.rssi_max is None else max(self.rssi_max, r.rssi)
            if r.cell is not None:
                c = self.cells.setdefault(r.cell, [0, 0, 0, set(), 0])
                c[0] += 1
                if r.rssi is not None:
                    c[1] += r.rssi
                    c[2] += 1
                c[3].add(r.address)
                c[4] = max(c[4], r.distance)
            if r.sector is not None:
                peak = self.peaks.setdefault(r.sector, [0, 0])
                peak[0] = max(peak[0], r.radius)
                peak[1] += 1
        # Late packets touch only the short overlapping tail, not a week-long sort.
        cut = bisect_left(self.records, records[0].stamp, key=lambda r: r.stamp)
        tail = list(zip(self.records[cut:], self.points[cut:])) + list(zip(records, new_points))
        tail.sort(key=lambda item: (item[0].stamp, item[0].address))
        self.records[cut:] = [r for r, _ in tail]
        self.points[cut:] = [p for _, p in tail]
        # The convex hull of the old hull plus new points encloses the full cloud.
        self.hull = camera_hull([*self.hull, *([r.east, r.north, r.up] for r in records)]).tolist()

    def snapshot(self, meta, breaks, display_limit):
        meta.update(excluded_other_sites=len(self.excluded), coverage_site_radius_m=100)
        if not self.records:
            return dict(status='EMPTY', meta=meta, base=0, points=[], cells=[], aircraft=[],
                        breaks=[], footprint=footprint_from_peaks(self.site, {}))
        meta.update(retained_positions=len(self.records), positioned_aircraft=len(self.addresses),
                    first_position=self.records[0].stamp, last_position=self.records[-1].stamp,
                    horizontal_range_max_km=self.max_range.distance/1000,
                    slant_range_max_km=self.max_slant/1000, max_altitude_ft=self.max_alt.altitude,
                    max_altitude_source='GNSS' if self.max_alt.gnss else 'BARO ≈',
                    max_altitude_aircraft=self.max_alt.label or self.max_alt.address,
                    altitude_sources=dict(self.sources), cells_observed=len(self.cells),
                    rssi_min=self.rssi_min if self.rssi_min is not None else -40,
                    rssi_max=self.rssi_max if self.rssi_max is not None else 0)
        if len(self.points) > display_limit:
            keep = {i*(len(self.points)-1)//max(1, display_limit-1) for i in range(display_limit)}
            keep.update((self.records.index(self.max_alt), self.records.index(self.max_range), len(self.points)-1))
            points = [self.points[i] for i in sorted(keep)]
        else:
            points = self.points.copy()
        meta.update(displayed_positions=len(points), display_limit=display_limit,
                    sampled=len(points) < len(self.records))
        return dict(status='READY', meta=meta, base=self.base, points=points,
                    aircraft=[dict(hex=a, label=self.names.get(a, (0, a))[1]) for a in self.addresses],
                    cells=[[a, e, c[0], c[1]/c[2] if c[2] else None, len(c[3]), c[4]]
                           for (a, e), c in self.cells.items()],
                    breaks=breaks, hull=[p.copy() for p in self.hull],
                    footprint=footprint_from_peaks(self.site, self.peaks))
