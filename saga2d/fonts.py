"""The bundled UI font: Nunito (SIL OFL) in three weights.

pyglet cannot pick a weight out of a variable font, so each weight is a
static file registered as its own family (see ``tools/build_fonts.py``)::

    from saga2d import fonts
    fonts.load(game)
    Theme(font=fonts.REGULAR, text_styles={"title": TextStyle(22, GOLD, fonts.EXTRABOLD)})
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from saga2d.game import Game

FONT_DIR = Path(__file__).parent / "assets" / "fonts"
REGULAR = "Nunito"
SEMIBOLD = "Nunito SemiBold"
EXTRABOLD = "Nunito ExtraBold"
FILES: dict[str, str] = {REGULAR: "Nunito.ttf", SEMIBOLD: "Nunito-SemiBold.ttf", EXTRABOLD: "Nunito-ExtraBold.ttf"}


def load(game: Game) -> None:
    """Register the three families with the game's backend."""
    for name, file in FILES.items():
        game.backend.load_font(name, str(FONT_DIR / file))
