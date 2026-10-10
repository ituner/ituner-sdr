"""Public OpenWebRX receiver discovery through Receiverbook.

Receiverbook is the public directory referenced by current OpenWebRX
installations.  Its map page embeds the complete receiver catalog as JSON, so
one request supplies names, endpoints, and coordinates without walking the
paginated human-facing list.
"""

from __future__ import annotations

from client_identity import CLIENT_NAME

import html
import json
import re
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


DIRECTORY_URL = "https://www.receiverbook.de/map?type=openwebrx"
DEFAULT_CACHE = Path.home() / ".local/state/ituner-openwebrx-directory.json"
_DIRECTORY_PATTERN = re.compile(
    r"\bvar\s+receivers\s*=\s*(\[.*?\])\s*;\s*",
    re.DOTALL,
)
_TAG_PATTERN = re.compile(r"<[^>]*>")


def clean_label(value) -> str:
    """Reduce directory-supplied display HTML to safe single-line text."""
    text = html.unescape(_TAG_PATTERN.sub("", str(value or "")))
    return " ".join(text.split()).strip()


def directory_endpoint(url) -> str:
    """Mark an HTTP URL explicitly as OpenWebRX while preserving subpaths."""
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    scheme = "owrxs" if parsed.scheme == "https" else "owrx"
    path = parsed.path or "/"
    return urlunsplit((scheme, parsed.netloc, path, "", ""))


def flatten_directory(groups: Iterable[Mapping]) -> list[dict]:
    """Flatten Receiverbook locations into protocol-neutral receiver rows."""
    rows = []
    seen = set()
    for group in groups or ():
        if not isinstance(group, Mapping):
            continue
        location = clean_label(group.get("label"))
        coordinates = (group.get("location") or {}).get("coordinates")
        try:
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
        except (IndexError, TypeError, ValueError):
            latitude = longitude = None
        receivers = group.get("receivers") or ()
        for receiver in receivers:
            if not isinstance(receiver, Mapping):
                continue
            if str(receiver.get("type") or "").casefold() != "openwebrx":
                continue
            endpoint = directory_endpoint(receiver.get("url") or group.get("url"))
            canonical = endpoint.rstrip("/")
            if not endpoint or canonical in seen:
                continue
            seen.add(canonical)
            name = clean_label(receiver.get("label")) or location or "OpenWebRX receiver"
            rows.append({
                "id": f"openwebrx:{canonical}",
                "protocol": "openwebrx",
                "source_group": "openwebrx",
                "endpoint": endpoint,
                "name": name,
                "location": location if location.casefold() != name.casefold() else "",
                "latitude": latitude,
                "longitude": longitude,
                "version": clean_label(receiver.get("version")),
            })
    return rows


def parse_directory_page(page: str) -> list[dict]:
    """Extract and normalize the embedded public directory JSON."""
    match = _DIRECTORY_PATTERN.search(str(page or ""))
    if not match:
        return []
    try:
        groups = json.loads(match.group(1))
    except (TypeError, ValueError):
        return []
    return flatten_directory(groups if isinstance(groups, list) else ())


def load_cached_directory(cache_path=DEFAULT_CACHE) -> list[dict]:
    try:
        payload = json.loads(Path(cache_path).read_text())
    except (OSError, TypeError, ValueError):
        return []
    return [row for row in payload if isinstance(row, Mapping) and row.get("endpoint")]


def save_directory(rows, cache_path=DEFAULT_CACHE) -> None:
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(list(rows), ensure_ascii=False))
    temporary.replace(path)


def fetch_directory(url=DIRECTORY_URL, timeout=15) -> list[dict]:
    request = Request(url, headers={"User-Agent": CLIENT_NAME})
    with urlopen(request, timeout=timeout) as response:
        page = response.read().decode("utf-8", "replace")
    rows = parse_directory_page(page)
    if not rows:
        raise ValueError("Receiverbook returned no OpenWebRX receivers")
    return rows


def load_directory(cache_path=DEFAULT_CACHE, *, fetch=True) -> list[dict]:
    """Return the live directory, or the last successful cached copy."""
    cached = load_cached_directory(cache_path)
    if fetch:
        try:
            rows = fetch_directory()
        except (OSError, TypeError, ValueError):
            pass
        else:
            try:
                save_directory(rows, cache_path)
            except OSError:
                pass
            return rows
    return cached
