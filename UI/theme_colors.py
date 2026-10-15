"""Pure color controls for the visual Theme editor."""

import colorsys


SHADE_LIGHTNESS = (0.18, 0.38, 0.60, 0.82)
SHADE_SATURATION = (0.30, 0.50, 0.72, 0.92)


def _rgb(hue, lightness, saturation):
    return tuple(round(255 * channel) for channel in colorsys.hls_to_rgb(
        float(hue) % 1.0, lightness, saturation,
    ))


def shade_grid(hue):
    """Return four lightness rows by four saturation columns for one hue."""
    return tuple(
        _rgb(hue, lightness, saturation)
        for lightness in SHADE_LIGHTNESS
        for saturation in SHADE_SATURATION
    )


def recolor_family(colors, keys, hue):
    """Retint selected keys while retaining their relative lightness and alpha."""
    result = {name: list(value) for name, value in colors.items()}
    for name in keys:
        value = result[name]
        _old_hue, lightness, saturation = colorsys.rgb_to_hls(
            *(channel / 255.0 for channel in value[:3])
        )
        # Keep pure black/white distinguishable as dark/light shades of the
        # chosen hue; the affine map retains every member's lightness order.
        value[:3] = _rgb(hue, 0.06 + 0.88 * lightness, max(0.22, saturation))
    return result


def recolor_family_shades(colors, keys, hue, lightness, strength):
    """Recolor a family together while retaining its shade order and alpha.

    ``lightness`` and ``strength`` are normalized to the 0..1 range. Each
    member receives the same lightness offset, so differently lit surfaces
    remain ordered while the family shifts toward the requested average.
    """
    result = {key: list(value) for key, value in colors.items()}
    samples = [
        colorsys.rgb_to_hls(*(channel / 255 for channel in colors[key][:3]))[1]
        for key in keys
    ]
    target = max(0.0, min(1.0, lightness))
    requested_offset = target - sum(samples) / len(samples)
    # Apply one bounded offset to the whole family. Independent per-key
    # clipping can collapse close shades at either endpoint.
    lower_bound, upper_bound = (
        (0.0, 1.0) if max(samples) - min(samples) > 0.96
        else (0.02, 0.98)
    )
    min_offset = max(lower_bound - sample for sample in samples)
    max_offset = min(upper_bound - sample for sample in samples)
    offset = max(min_offset, min(max_offset, requested_offset))
    saturation = max(0.0, min(1.0, strength))
    for key in keys:
        old = colors[key]
        old_light = colorsys.rgb_to_hls(
            *(channel / 255 for channel in old[:3])
        )[1]
        new_light = old_light + offset
        rgb = colorsys.hls_to_rgb(hue % 1.0, new_light, saturation)
        result[key] = [
            *(max(0, min(255, round(255 * channel))) for channel in rgb),
            *old[3:],
        ]
    return result


def transparency_percent(color):
    if len(color) != 4:
        raise ValueError("this color has no transparency channel")
    return round((255 - color[3]) * 100 / 255)


def with_transparency(color, percent):
    if len(color) != 4:
        raise ValueError("this color has no transparency channel")
    if type(percent) is not int or not 0 <= percent <= 100:
        raise ValueError("transparency must be 0–100")
    return [*color[:3], round(255 * (100 - percent) / 100)]
