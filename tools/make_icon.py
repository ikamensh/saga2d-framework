"""Draw the engine's default application icon, ``saga2d/assets/icon.png``.

    uv run python tools/make_icon.py            # writes the committed picture
    uv run python tools/make_icon.py out.png    # writes somewhere else

A game that names no picture of its own in its ``GamePackage`` is built with
this one.  It is a square painted to the edges; ``saga2d.packaging.icon``
gives it each platform's shape when a game is built.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE = 1024
OVERSAMPLE = 4
TARGET = Path(__file__).resolve().parents[1] / "saga2d" / "assets" / "icon.png"

NIGHT_TOP, NIGHT_BOTTOM = (52, 58, 140), (16, 20, 56)
GOLD_TOP, GOLD_BOTTOM = (255, 222, 128), (236, 150, 44)
CREAM = (255, 244, 214)


def gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    column = Image.new("RGB", (1, size))
    column.putdata([tuple(round(a + (b - a) * y / (size - 1)) for a, b in zip(top, bottom)) for y in range(size)])
    return column.resize((size, size))


def letter(size: int) -> Image.Image:
    """The mask of a round-capped S made of two three-quarter rings."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius, stroke = 0.155 * size, 0.108 * size
    centre_x = size / 2
    upper, lower = size / 2 - radius, size / 2 + radius
    for centre_y, start, end in ((upper, 90, 360), (lower, 270, 180)):
        box = (centre_x - radius - stroke / 2, centre_y - radius - stroke / 2,
               centre_x + radius + stroke / 2, centre_y + radius + stroke / 2)
        draw.arc(box, start, end, fill=255, width=round(stroke))
        for angle in (start, end):
            x = centre_x + radius * math.cos(math.radians(angle))
            y = centre_y + radius * math.sin(math.radians(angle))
            draw.ellipse((x - stroke / 2, y - stroke / 2, x + stroke / 2, y + stroke / 2), fill=255)
    return mask


def spark(size: int, centre: tuple[float, float], reach: float) -> Image.Image:
    """The mask of a four-pointed star."""
    mask = Image.new("L", (size, size), 0)
    x, y = centre
    waist = reach * 0.22
    points = []
    for index in range(8):
        length = reach if index % 2 == 0 else waist
        angle = math.radians(45 * index - 90)
        points.append((x + length * math.cos(angle), y + length * math.sin(angle)))
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def draw() -> Image.Image:
    size = SIZE * OVERSAMPLE
    picture = gradient(size, NIGHT_TOP, NIGHT_BOTTOM).convert("RGBA")
    glow = Image.new("L", (size, size), 0)
    ImageDraw.Draw(glow).ellipse((size * 0.12, size * 0.02, size * 0.88, size * 0.78), fill=70)
    picture.paste(Image.new("RGBA", (size, size), (120, 140, 255, 255)), (0, 0), glow.filter(ImageFilter.GaussianBlur(size * 0.12)))
    shape = letter(size)
    shadow = ImageChops.offset(shape, 0, round(size * 0.022)).filter(ImageFilter.GaussianBlur(size * 0.02))
    picture.paste(Image.new("RGBA", (size, size), (6, 8, 30, 255)), (0, 0), shadow.point(lambda value: value * 0.6))
    picture.paste(gradient(size, GOLD_TOP, GOLD_BOTTOM).convert("RGBA"), (0, 0), shape)
    picture.paste(Image.new("RGBA", (size, size), (*CREAM, 255)), (0, 0), spark(size, (size * 0.775, size * 0.235), size * 0.08))
    return picture.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else TARGET
    draw().save(target, optimize=True)
    print(target)
