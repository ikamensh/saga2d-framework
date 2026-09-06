"""Texts drawn over other texts are found from the mock backend's frame, anchors and all."""

import pytest

from saga2d import Anchor, Game, Label, Scene
from saga2d.testing import assert_no_text_overlap, overlapping_texts, text_boxes


class Screen(Scene):
    def __init__(self, draws) -> None:
        super().__init__()
        self.draws = draws

    def draw(self) -> None:
        for text, x, y, kwargs in self.draws:
            self.draw_text(text, x, y, font_size=20, **kwargs)


class Overlay(Screen):
    transparent = True  # the scene beneath keeps drawing, dimmed by a panel in a real game


@pytest.fixture
def frame():
    games = []

    def make(draws, ui=()):
        game = Game("overlap", backend="mock", resolution=(640, 400))
        games.append(game)
        scene = Screen(draws)
        game.push(scene)
        for component in ui:
            scene.ui.add(component)
        game.tick(1 / 60)
        return game

    yield make
    for game in games:
        game._teardown()


def test_boxes_follow_anchors_and_the_backend_measure(frame) -> None:
    game = frame([("Hello", 100, 50, {"anchor_x": "center", "anchor_y": "center"}), ("Hi", 0, 0, {"anchor_x": "left", "anchor_y": "top"})])
    boxes = {b.text: b for b in text_boxes(game.backend)}
    width, height = game.backend.measure_text("Hello", 20, None)
    assert (boxes["Hello"].left, boxes["Hello"].top) == (100 - width / 2, 50 - height / 2)
    assert (boxes["Hi"].left, boxes["Hi"].top) == (0, 0)


def test_a_tagline_drawn_over_a_button_is_reported_and_a_shadow_pass_is_not(frame) -> None:
    draws = [
        ("WARBAND", 320, 100, {"anchor_x": "center", "anchor_y": "center"}),
        ("WARBAND", 322, 102, {"anchor_x": "center", "anchor_y": "center"}),  # the shadow behind the title
        ("Gather · Build · Conquer", 320, 160, {"anchor_x": "center", "anchor_y": "center"}),
        ("Far away", 20, 380, {"anchor_x": "left", "anchor_y": "bottom"}),
    ]
    game = frame(draws, ui=[Label("New game", anchor=Anchor.CENTER, margin=0)])  # the centre of 640x400 is (320, 200)
    assert overlapping_texts(game) == []
    game._teardown()
    draws[2] = ("Gather · Build · Conquer", 320, 195, {"anchor_x": "center", "anchor_y": "center"})
    game = frame(draws, ui=[Label("New game", anchor=Anchor.CENTER, margin=0)])
    pairs = overlapping_texts(game)
    assert [(a.text, b.text) for a, b in pairs] == [("Gather · Build · Conquer", "New game")]
    with pytest.raises(AssertionError, match="Gather · Build · Conquer.*over.*New game"):
        assert_no_text_overlap(game)


def test_an_overlay_is_checked_without_the_scene_beneath_it(frame) -> None:
    game = frame([("Score 12", 320, 200, {"anchor_x": "center", "anchor_y": "center"})])
    game.push(Overlay([("Paused", 320, 200, {"anchor_x": "center", "anchor_y": "center"})]))
    game.tick(1 / 60)
    assert [(a.text, b.text) for a, b in overlapping_texts(game)] == [("Score 12", "Paused")]
    assert overlapping_texts(game, top_scene_only=True) == []


def test_world_text_is_left_alone_unless_asked(frame) -> None:
    draws = [("12", 100, 100, {"space": "world"}), ("12", 104, 101, {"space": "world"}), ("7", 101, 100, {"space": "world"})]
    game = frame(draws)
    assert overlapping_texts(game) == []
    assert [(a.text, b.text) for a, b in overlapping_texts(game, spaces=("world",))] == [("12", "7"), ("12", "7")]
