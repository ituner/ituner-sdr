"""Small, render-independent helpers for the receiver map and station picker."""

from collections import defaultdict, deque
import math
import time


def globe_native_matrix(
    yaw, pitch, center_x, center_y, radius, desktop, orientation,
    native_height, active_height,
):
    """Column-major fixed-function matrix matching the CPU globe projection."""
    sin_yaw, cos_yaw = math.sin(yaw), math.cos(yaw)
    sin_pitch, cos_pitch = math.sin(pitch), math.cos(pitch)
    camera_x = (cos_yaw, 0.0, -sin_yaw)
    camera_y = (
        -sin_pitch * sin_yaw,
        cos_pitch,
        -sin_pitch * cos_yaw,
    )
    camera_z = (
        cos_pitch * sin_yaw,
        sin_pitch,
        cos_pitch * cos_yaw,
    )
    if desktop:
        row_x = tuple(radius * value for value in camera_x)
        row_y = tuple(-radius * value for value in camera_y)
        translate_x, translate_y = center_x, center_y
    elif orientation == "normal":
        row_x = tuple(radius * value for value in camera_y)
        row_y = tuple(radius * value for value in camera_x)
        translate_x, translate_y = active_height - center_y, center_x
    else:
        row_x = tuple(-radius * value for value in camera_y)
        row_y = tuple(-radius * value for value in camera_x)
        translate_x, translate_y = center_y, native_height - center_x
    return (
        row_x[0], row_y[0], camera_z[0], 0.0,
        row_x[1], row_y[1], camera_z[1], 0.0,
        row_x[2], row_y[2], camera_z[2], 0.0,
        translate_x, translate_y, 0.0, 1.0,
    )


def health_prioritized_stations(stations, station_health, sort_mode):
    """Keep the configured station order inside stable availability groups."""
    now = time.time()

    def health_group(station):
        server = station[2]
        entry = station_health.get(server, {})
        fresh = now - entry.get("checked", 0) <= 86400
        if not fresh:
            return 2
        audio_active = entry.get("audio") is True
        waterfall_active = entry.get("waterfall") is True
        if audio_active and waterfall_active:
            return 0
        if waterfall_active:
            return 1
        if audio_active:
            return 2
        return 3

    return tuple(
        station
        for _index, station in sorted(
            enumerate(stations), key=lambda item: (health_group(item[1]), item[0])
        )
    )


class StationOrderCache:
    """Memoize health ordering until either source object is replaced."""

    def __init__(self):
        self._stations = None
        self._station_health = None
        self._sort_mode = None
        self._ordered = ()
        self._expires_at = math.inf

    def get(self, stations, station_health, sort_mode):
        now = time.time()
        if (
            stations is not self._stations
            or station_health is not self._station_health
            or sort_mode != self._sort_mode
            or now >= self._expires_at
        ):
            self._stations = stations
            self._station_health = station_health
            self._sort_mode = sort_mode
            self._ordered = health_prioritized_stations(stations, station_health, sort_mode)
            expirations = [
                entry.get("checked", 0) + 86400
                for entry in station_health.values()
                if isinstance(entry, dict) and entry.get("checked", 0) > now - 86400
            ]
            self._expires_at = min(expirations, default=math.inf)
        return self._ordered

    def clear(self):
        self._stations = None
        self._station_health = None
        self._sort_mode = None
        self._ordered = ()
        self._expires_at = math.inf


def visible_station_range(station_count, scroll, columns, rows, overscan_rows=0):
    """Return the only station indexes whose tiles can intersect the viewport."""
    columns = max(1, int(columns))
    rows = max(1, int(rows))
    scroll_rows = float(scroll) / columns
    first_row = max(0, int(math.floor(scroll_rows)) - overscan_rows)
    last_row = int(math.ceil(scroll_rows + rows)) + overscan_rows
    return range(
        min(station_count, first_row * columns),
        min(station_count, last_row * columns),
    )


def receiver_health_rank(receiver, station_health, now=None):
    """Rank map candidates by usable audio first, without treating stale data as fact."""
    now = time.time() if now is None else now
    entry = station_health.get(receiver.get("server"), {})
    fresh = now - entry.get("checked", 0) <= 86400
    if fresh and entry.get("audio") is True and entry.get("waterfall") is True:
        stream_rank = 0
    elif fresh and entry.get("audio") is True:
        stream_rank = 1
    elif fresh and entry.get("waterfall") is True:
        stream_rank = 2
    elif not fresh:
        stream_rank = 3
    else:
        stream_rank = 4
    try:
        at_capacity = int(receiver.get("total", 0)) > 0 and int(receiver.get("used", 0)) >= int(receiver.get("total", 0))
    except (TypeError, ValueError):
        at_capacity = False
    return int(at_capacity), stream_rank


def choose_nearby_receivers(
    anchor, receivers, station_health, distance_between, limit=3, pool_size=24,
):
    """Choose a local trio, preferring receivers already proven to deliver audio."""
    if not anchor or not receivers or limit <= 0:
        return ()
    nearby = sorted(
        receivers,
        key=lambda receiver: (
            0 if receiver.get("server") == anchor.get("server") else 1,
            distance_between(anchor, receiver),
        ),
    )[:max(limit, pool_size)]
    distance_cache = {
        receiver.get("server"): distance_between(anchor, receiver)
        for receiver in nearby
    }
    return tuple(sorted(
        nearby,
        key=lambda receiver: (
            *receiver_health_rank(receiver, station_health),
            distance_cache.get(receiver.get("server"), math.inf),
        ),
    )[:limit])


def receiver_server_index(receiver, candidates):
    """Return the exact candidate slot for a receiver server, if present."""
    server = receiver.get("server") if receiver else None
    if not server:
        return None
    return next(
        (index for index, candidate in enumerate(candidates)
         if candidate.get("server") == server),
        None,
    )


def receiver_scroll_for_server(stations, server, columns, rows):
    """Center a receiver in the visible list, clamped at either list edge."""
    columns = max(1, int(columns))
    rows = max(1, int(rows))
    index = next(
        (
            index for index, station in enumerate(stations)
            if len(station) > 2 and station[2] == server
        ),
        None,
    )
    if index is None:
        return 0
    station_count = len(stations)
    selected_row = index // columns
    total_rows = math.ceil(station_count / columns)
    first_row = max(0, selected_row - rows // 2)
    first_row = min(first_row, max(0, total_rows - rows))
    return first_row * columns


def closest_strong_spectrum_frequency(values, center_khz, span_khz, minimum_contrast=0.12):
    """Return the strongest clear local spectrum peak, or None for noise-only data."""
    values = tuple(float(value) for value in values)
    if len(values) < 5 or span_khz <= 0:
        return None
    ordered = sorted(values)
    baseline = ordered[len(ordered) // 2]
    threshold = max(0.35, baseline + minimum_contrast)
    center_index = (len(values) - 1) / 2.0
    peaks = [
        index for index in range(1, len(values) - 1)
        if values[index] >= threshold
        and values[index] >= values[index - 1]
        and values[index] >= values[index + 1]
    ]
    if not peaks:
        return None
    peak_index = min(
        peaks,
        key=lambda index: (-values[index], abs(index - center_index), index),
    )
    fraction = (peak_index + 0.5) / len(values) - 0.5
    return float(center_khz) + fraction * float(span_khz)


class ReceiverProjectionSnapshot:
    """One map state's projected receivers, reused by drawing and hit testing."""

    BUCKET_SIZE = 64.0

    def __init__(self, receivers, yaw, pitch, box, scale, projector):
        self.receivers = receivers
        self.yaw = yaw
        self.pitch = pitch
        self.box = box
        self.scale = scale
        self.visible = []
        self.by_server = {}
        self.points_by_server = {}
        self.buckets = defaultdict(list)
        for index, receiver in enumerate(receivers):
            server = receiver.get("server")
            if server:
                self.by_server[server] = receiver
            point = projector(receiver, yaw, pitch, box, scale)
            if point is None:
                continue
            self.visible.append((receiver, point))
            if server:
                self.points_by_server[server] = point
            self.buckets[self._bucket(point[0], point[1])].append((index, receiver, point))

    def matches(self, receivers, yaw, pitch, box, scale):
        return (
            receivers is self.receivers
            and yaw == self.yaw
            and pitch == self.pitch
            and box == self.box
            and scale == self.scale
        )

    def receiver(self, server):
        return self.by_server.get(server)

    def point(self, server):
        return self.points_by_server.get(server)

    def nearest(self, x, y, maximum_distance=42.0):
        bucket_x, bucket_y = self._bucket(x, y)
        reach = max(1, int(math.ceil(maximum_distance / self.BUCKET_SIZE)))
        best = None
        for candidate_x in range(bucket_x - reach, bucket_x + reach + 1):
            for candidate_y in range(bucket_y - reach, bucket_y + reach + 1):
                for index, receiver, point in self.buckets.get((candidate_x, candidate_y), ()):
                    distance = math.hypot(point[0] - x, point[1] - y)
                    if best is None or (distance, index) < best[:2]:
                        best = (distance, index, receiver)
        return best[2] if best is not None and best[0] <= maximum_distance else None

    @classmethod
    def _bucket(cls, x, y):
        return int(math.floor(x / cls.BUCKET_SIZE)), int(math.floor(y / cls.BUCKET_SIZE))


class PickerFrameProfiler:
    """Optional low-overhead frame/phase timing for the two receiver views."""

    def __init__(self, enabled=False, report_every=120, history=240):
        self.enabled = enabled
        self.report_every = max(1, int(report_every))
        self.samples = defaultdict(lambda: defaultdict(lambda: deque(maxlen=history)))
        self.frames = defaultdict(int)

    def record(self, view, timings):
        if not self.enabled:
            return None
        self.frames[view] += 1
        for phase, seconds in timings.items():
            self.samples[view][phase].append(float(seconds) * 1000.0)
        if self.frames[view] % self.report_every:
            return None
        return self.report(view)

    def percentile(self, view, phase, percentile=0.95):
        values = sorted(self.samples[view][phase])
        if not values:
            return None
        index = min(len(values) - 1, math.ceil(len(values) * percentile) - 1)
        return values[max(0, index)]

    def report(self, view):
        fields = []
        for phase in sorted(self.samples[view]):
            values = sorted(self.samples[view][phase])
            if not values:
                continue
            p95 = self.percentile(view, phase)
            fields.append(f"{phase}=p50:{values[len(values) // 2]:.2f}/p95:{p95:.2f}/max:{values[-1]:.2f}ms")
        return f"picker perf {view} " + " ".join(fields)
