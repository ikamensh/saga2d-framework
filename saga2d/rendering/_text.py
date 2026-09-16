"""Measured text layout shared by immediate text and retained labels."""

from dataclasses import dataclass
import math
from typing import Callable


@dataclass(frozen=True)
class TextLayout:
    """A measured paragraph, including blank lines and its occupied height.

    Construct through :meth:`Scene.layout_text`. Measurements belong to the
    font and display scale at layout time; measure again after either changes.
    """

    lines: tuple[str, ...]
    line_height: float
    line_spacing: float
    truncated: bool = False

    @property
    def height(self) -> float:
        return self.line_height * (1 + (len(self.lines) - 1) * self.line_spacing) if self.lines else 0.0


def _validate_paragraph_size(width: float, line_spacing: float) -> None:
    if not math.isfinite(width) or width <= 0:
        raise ValueError("Paragraph width must be positive and finite")
    if not math.isfinite(line_spacing) or line_spacing <= 0:
        raise ValueError("Paragraph line spacing must be positive and finite")


def _validate_max_lines(max_lines: int | None) -> None:
    if max_lines is not None and (type(max_lines) is not int or max_lines <= 0):
        raise ValueError("max_lines must be a positive integer or None")


def _ellipsize(text: str, width: float, measure: Callable[[str], tuple[int, int]]) -> str:
    """Append an ellipsis, trimming the prefix only as far as required to fit."""
    if measure("…")[0] > width:
        raise ValueError(f"Text width {width} cannot fit an ellipsis")
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle].rstrip() + "…")[0] <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "…"


def _layout_paragraph(text: str, width: float, measure: Callable[[str], tuple[int, int]],
                      line_spacing: float = 1.4, *, max_lines: int | None = None) -> TextLayout:
    _validate_paragraph_size(width, line_spacing)
    _validate_max_lines(max_lines)
    if not text:
        return TextLayout((), 0, line_spacing)

    def fits(value: str) -> bool:
        return measure(value)[0] <= width

    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = line + " " + word if line else word
            if fits(candidate):
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            if fits(word):
                line = word
                continue
            for character in word:
                if not fits(character):
                    raise ValueError(f"Paragraph width {width} cannot fit character {character!r}")
                if line and not fits(line + character):
                    lines.append(line)
                    line = ""
                line += character
        lines.append(line)
    line_height = measure("Mg")[1]
    truncated = max_lines is not None and len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(lines[-1], width, measure)
    return TextLayout(tuple(lines), line_height, line_spacing, truncated)


#: Where a text's anchor sits inside its measured box, as a fraction of the box.
#: Both the overflow check and the test helpers measure boxes with these, so a
#: drawn string and a checked string are the same rectangle.
ANCHOR_X = {"left": 0.0, "center": 0.5, "right": 1.0}
ANCHOR_Y = {"top": 0.0, "center": 0.5, "baseline": 0.8, "bottom": 1.0}
