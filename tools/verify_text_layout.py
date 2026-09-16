"""Native measured layout, truncation and retained/immediate pixel agreement."""

import argparse
import math
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SAGA2D_SILENT"] = "1"

from PIL import ImageChops

from saga2d import Anchor, Game, Label, Scene, TextStyle, Theme, fonts
from saga2d.testing import assert_text_fits
from saga2d.testing.native_frames import tick


CASES = (
    ("Gather supplies beside the river before entering the ancient fortress.", None),
    ("An authored line\n\nA final line\n", None),
    ("AnUnbrokenResourceNameFromTheAncientFortress" * 3, 3),
)
LEFT, RIGHT, WIDTH, TOP, ROW = 45, 545, 360, 100, 150


class TextComparison(Scene):
    background_color = (12, 21, 32, 255)

    def on_enter(self):
        self.labels = []
        for index, (text, limit) in enumerate(CASES):
            self.labels.append(self.ui.add(Label(
                text, width=WIDTH, wrap=True, max_lines=limit, text_style="description",
                anchor=Anchor.TOP_LEFT, margin=(RIGHT, TOP + index * ROW),
            )))

    def draw(self):
        self.draw_text("Measured immediate text", LEFT, 35, font_size=24, anchor_y="top")
        self.draw_text("Retained labels", RIGHT, 35, font_size=24, anchor_y="top")
        for index, (text, limit) in enumerate(CASES):
            top = TOP + index * ROW
            layout = self.layout_text(text, WIDTH, style="description", max_lines=limit)
            assert self.labels[index].get_preferred_size()[1] == math.ceil(layout.height)
            assert layout.truncated == (limit is not None)
            with self.text_region(LEFT, top, WIDTH, layout.height, name=f"paragraph {index}"):
                assert self.draw_paragraph(text, LEFT, top, WIDTH, style="description",
                                           max_lines=limit) == layout.height
            assert all(self.game.backend.measure_text(line, 18, fonts.REGULAR)[0] <= WIDTH
                       for line in layout.lines)
        name = "The exceptionally long name on this small card"
        fitted = self.fit_text(name, WIDTH, font=fonts.SEMIBOLD, font_size=23)
        assert fitted.endswith("…")
        with self.text_region(LEFT, 580, WIDTH, 50, name="fitted name"):
            self.draw_text(fitted, LEFT, 580, font=fonts.SEMIBOLD, font_size=23, anchor_y="top")


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    theme = Theme(font=fonts.REGULAR, text_styles={"description": TextStyle(18, (230, 235, 240, 255))})
    game = Game("Measured text", resolution=(1000, 700), visible=False, theme=theme)
    try:
        fonts.load(game)
        game.push(TextComparison())
        for name, size in (("initial", (1000, 700)), ("resized", (1500, 1050))):
            game.set_window_size(size)
            tick(game)
            assert_text_fits(game)
            frame = game.backend.capture_frame()
            frame.save(output / f"{name}.png")
            scale = frame.width / game.width

            def crop(x):
                return frame.crop(tuple(round(value * scale) for value in
                                        (x, TOP, x + WIDTH, TOP + len(CASES) * ROW))).convert("RGB")

            assert ImageChops.difference(crop(LEFT), crop(RIGHT)).getbbox() is None, name
        print(f"Native layout, fitting and matching immediate/retained pixels passed: {output}")
    finally:
        game.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/saga2d-text-layout"))
    verify(parser.parse_args().output)
