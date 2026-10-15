"""Native-pixel PeppyMeter derivatives; source graphics/credits remain bundled."""
from PIL import Image, ImageDraw


def linear_cell_boxes(identifier, size):
    """Use whole pixel cells and gaps, never shrink a high-frequency source grid."""
    width, height = size
    if identifier == "peppy_dash":
        columns, rows = min(13, max(1, width // 3)), 1
        gap_x, gap_y = max(1, round(width / 80)), 0
    elif identifier == "peppy_bar":
        columns, rows = min(47, max(1, width // 4)), 1
        gap_x, gap_y = 1, max(1, round(height * .10))
    elif identifier == "peppy_gas":
        columns, rows = max(1, width // 4), max(1, height // 7)
        gap_x, gap_y = 1, 1
    else:
        raise ValueError("Unknown linear artwork: " + identifier)
    cells = []
    for row in range(rows):
        for column in range(columns):
            left, right = round(column * width / columns), round((column + 1) * width / columns)
            top, bottom = round(row * height / rows), round((row + 1) * height / rows)
            # Inclusive drawing bounds leave identical dark gaps in both states.
            cells.append((left, top + gap_y, max(left, right - gap_x - 1),
                          max(top + gap_y, bottom - gap_y - 1)))
    return cells


def linear_strip_image(identifier, size, active):
    """Crisp final-size interpretations of the credited Bar/Dash/Gas artwork.

    Preserve source bar/grid shapes and light character; Gas uses green VFD phosphor,
    with deliberately restrained glow so adjacent cells remain distinguishable.
    """
    image = Image.new("RGBA", size, (3, 9, 12, 255))
    draw = ImageDraw.Draw(image)
    width, _height = size
    for left, top, right, bottom in linear_cell_boxes(identifier, size):
        red = (left + right) / (2 * width) >= .72
        if identifier == "peppy_gas":
            fill, core = ((28, 222, 87), (146, 255, 166)) if active else ((5, 33, 15), (8, 46, 21))
        elif identifier == "peppy_bar":
            fill, core = (((231, 45, 35), (255, 95, 64)) if red else
                          ((71, 171, 178), (147, 234, 230))) if active else (
                          ((43, 13, 12), (61, 18, 15)) if red else ((12, 34, 38), (21, 48, 51)))
        else:
            fill, core = (((231, 43, 37), (255, 78, 61)) if red else
                          ((145, 193, 44), (179, 219, 72))) if active else (
                          ((43, 13, 12), (51, 17, 13)) if red else ((24, 33, 12), (32, 43, 15)))
        draw.rectangle((left, top, right, bottom), fill=fill)
        if identifier == "peppy_gas":
            # A small luminous core; the one-pixel dark grid is never filtered.
            draw.line((left, (top + bottom) // 2, right, (top + bottom) // 2), fill=core)
        elif identifier == "peppy_bar":
            draw.line(((left + right) // 2, top + 1, (left + right) // 2, bottom - 1), fill=core)
        else:
            draw.line((left, top, right, top), fill=core)
    return image
