"""Text that does not fit the rectangle it was drawn into.

``assert_no_text_overlap`` catches a string drawn over another string; it
structurally cannot catch a string that runs off its own card, because that one
is over nothing at all.  ``Scene.text_region`` names the rectangle so the
framework can, as a warning while the game runs and an assertion in a test.
"""

from __future__ import annotations

import logging

import pytest

from saga2d import Scene
from saga2d.testing import assert_text_fits, text_overflows

CARD = (10, 10, 80, 30)


class Cards(Scene):
    """Draws whatever it is given, inside a declared card-sized region."""

    background_color = (0, 0, 0, 255)

    def __init__(self, inside=(), outside=(), region=CARD) -> None:
        self.inside, self.outside, self.region = list(inside), list(outside), region

    def draw(self) -> None:
        x, y, w, h = self.region
        with self.text_region(x, y, w, h, name="card"):
            for text in self.inside:
                self.draw_text(text, x + 2, y + 20, font_size=12)
        for text in self.outside:
            self.draw_text(text, x + 2, y + 20, font_size=12)


def test_a_string_inside_its_region_is_not_reported(game):
    game.push(Cards(inside=["ok"]))
    game.tick(1 / 60)
    assert text_overflows(game) == []
    assert_text_fits(game)


def test_a_string_that_runs_out_of_its_region_is_reported(game):
    game.push(Cards(inside=["a name far too long for this little card"]))
    game.tick(1 / 60)
    spills = text_overflows(game)
    assert len(spills) == 1
    assert spills[0].region == "card"
    assert spills[0].over[2] > 0, "it should spill to the right"
    with pytest.raises(AssertionError, match="does not fit"):
        assert_text_fits(game)


def test_the_window_is_the_region_when_none_is_declared(game):
    class OffScreen(Scene):
        background_color = (0, 0, 0, 255)

        def draw(self) -> None:
            self.draw_text("far off the right edge", 5000, 40, font_size=14)

    game.push(OffScreen())
    game.tick(1 / 60)
    spills = text_overflows(game)
    assert len(spills) == 1 and spills[0].region == "the window"


def test_regions_nest_and_the_innermost_one_is_the_one_that_must_be_fitted(game):
    class Nested(Scene):
        background_color = (0, 0, 0, 255)

        def draw(self) -> None:
            with self.text_region(0, 0, 400, 300, name="panel"):
                with self.text_region(10, 10, 40, 20, name="badge"):
                    self.draw_text("far too wide for a badge", 12, 24, font_size=12)
                self.draw_text("but this fits the panel", 12, 120, font_size=12)

    game.push(Nested())
    game.tick(1 / 60)
    spills = text_overflows(game)
    assert [spill.region for spill in spills] == ["badge"]


def test_a_region_is_restored_after_the_scope_even_when_drawing_raises(game):
    class Boom(Scene):
        background_color = (0, 0, 0, 255)

        def draw(self) -> None:
            try:
                with self.text_region(0, 0, 10, 10, name="tiny"):
                    raise RuntimeError("drawing blew up")
            except RuntimeError:
                pass
            self.draw_text("this is measured against the window, not the tiny region", 5, 40, font_size=12)

    game.push(Boom())
    game.tick(1 / 60)
    assert text_overflows(game) == []


def test_the_report_is_cleared_between_frames(game):
    scene = Cards(inside=["a name far too long for this little card"])
    game.push(scene)
    game.tick(1 / 60)
    assert len(text_overflows(game)) == 1
    scene.inside = ["ok"]
    game.tick(1 / 60)
    assert text_overflows(game) == []


def test_the_first_offence_is_warned_about_so_it_is_noticed_while_playing(game, caplog):
    with caplog.at_level(logging.WARNING, logger="saga2d.game"):
        game.push(Cards(inside=["a name far too long for this little card"]))
        game.tick(1 / 60)
    assert any("does not fit" in record.getMessage() for record in caplog.records)


def test_the_same_offence_is_warned_about_once_not_every_frame(game, caplog):
    with caplog.at_level(logging.WARNING, logger="saga2d.game"):
        game.push(Cards(inside=["a name far too long for this little card"]))
        for _ in range(30):
            game.tick(1 / 60)
    warnings = [record for record in caplog.records if "does not fit" in record.getMessage()]
    assert len(warnings) == 1, "a 60 FPS game must not print the same warning sixty times a second"


def test_world_text_is_left_alone(game):
    """Floating damage numbers leave the screen on purpose."""
    class Floating(Scene):
        background_color = (0, 0, 0, 255)

        def draw(self) -> None:
            self.draw_text("-12", 9000, 9000, font_size=12, space="world")

    game.push(Floating())
    game.tick(1 / 60)
    assert text_overflows(game) == []


def test_the_check_can_be_switched_off(game):
    game.check_text_fit = False
    game.push(Cards(inside=["a name far too long for this little card"]))
    game.tick(1 / 60)
    assert text_overflows(game) == []


def test_a_paragraph_is_checked_line_by_line(game):
    class Paragraph(Scene):
        background_color = (0, 0, 0, 255)

        def draw(self) -> None:
            with self.text_region(10, 10, 120, 24, name="slot"):
                self.draw_paragraph("one two three four five six seven eight", 12, 20, 110, font_size=12)

    game.push(Paragraph())
    game.tick(1 / 60)
    spills = text_overflows(game)
    assert spills and all(spill.region == "slot" for spill in spills)
    assert any(spill.over[3] > 0 for spill in spills), "the paragraph runs out of the bottom"
