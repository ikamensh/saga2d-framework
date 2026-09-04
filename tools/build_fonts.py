"""Regenerate ``tribes/assets/fonts`` from Nunito's variable font (SIL OFL 1.1).

    uv run --with fonttools python tools/build_fonts.py "Nunito[wght].ttf"

pyglet resolves fonts by family name and cannot pick a weight out of a
variable font (CoreText hands back the default instance for every
weight), so each weight becomes a static font with its own family name:
``Nunito``, ``Nunito SemiBold`` and ``Nunito ExtraBold``.  Game code then
asks for the family it wants and gets the right weight on every platform.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

WEIGHTS = {"Nunito": 400, "Nunito SemiBold": 600, "Nunito ExtraBold": 800}
OUT = Path(__file__).resolve().parent.parent / "tribes" / "assets" / "fonts"


def instantiate(source: Path, family: str, weight: int) -> None:
    font = instancer.instantiateVariableFont(TTFont(source), {"wght": weight}, updateFontNames=True)
    postscript = family.replace(" ", "") + "-Regular"
    for record in font["name"].names:
        if record.nameID in (1, 4, 16):
            record.string = family
        elif record.nameID in (2, 17):
            record.string = "Regular"
        elif record.nameID == 6:
            record.string = postscript
    font["OS/2"].fsSelection = (font["OS/2"].fsSelection & ~0b100001) | 0b1000000  # regular, not bold/italic
    font["head"].macStyle = 0
    target = OUT / (family.replace(" ", "-") + ".ttf")
    font.save(target)
    print(f"{target.name}: family {family!r}, weight {weight}")


def main() -> None:
    source = Path(sys.argv[1])
    for family, weight in WEIGHTS.items():
        instantiate(source, family, weight)


if __name__ == "__main__":
    main()
