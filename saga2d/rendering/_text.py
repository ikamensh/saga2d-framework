"""Private measured paragraph layout shared by immediate text and retained labels."""

from dataclasses import dataclass
import math
from typing import Callable


@dataclass(frozen=True)
class _Paragraph:
    lines: tuple[str, ...]
    line_height: float
    line_spacing: float

    @property
    def height(self) -> float:
        return self.line_height * (1 + (len(self.lines) - 1) * self.line_spacing) if self.lines else 0.0


def _validate_paragraph_size(width: float, line_spacing: float) -> None:
    if not math.isfinite(width) or width <= 0:
        raise ValueError("Paragraph width must be positive and finite")
    if not math.isfinite(line_spacing) or line_spacing <= 0:
        raise ValueError("Paragraph line spacing must be positive and finite")


def _layout_paragraph(text: str, width: float, measure: Callable[[str], tuple[int, int]],
                      line_spacing: float = 1.4) -> _Paragraph:
    _validate_paragraph_size(width, line_spacing)
    if not text:
        return _Paragraph((), 0, line_spacing)

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
    return _Paragraph(tuple(lines), line_height, line_spacing)
