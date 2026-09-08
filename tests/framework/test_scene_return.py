"""Returning to a retained scene through the public Game and input interfaces."""

import pytest
from PIL import Image

from saga2d import Game, Label, Scene, Sprite


def test_input_returns_to_retained_scene_without_revealing_removed_overlays(game: Game) -> None:
    """One input closes all covers after its handler and discards stale input."""
    events = []

    class Page(Scene):
        def __init__(self, name):
            self.name = name

        def on_reveal(self):
            events.append(f"reveal:{self.name}")

        def on_close(self):
            events.append(f"close:{self.name}")

    base, middle, top = (Page(name) for name in ("base", "middle", "top"))
    for scene in (base, middle, top):
        scene.bind_key("space", lambda: events.append("stale input"))
        game.push(scene)

    def return_to_base():
        game.pop_to(base)
        assert game.scenes == [base, middle, top]
        events.append("handler completed")

    top.bind_key("enter", return_to_base)
    game.backend.inject_key("enter")
    game.backend.inject_key("space")
    game.tick(.01)

    assert game.scenes == [base]
    assert game.scene is base
    assert events == ["handler completed", "close:top", "close:middle", "reveal:base"]


def test_returning_to_current_top_is_a_noop_including_remaining_input(game: Game) -> None:
    """No scene change means no reveal, cleanup or discarded follow-up key."""
    events = []

    class Page(Scene):
        def on_reveal(self):
            events.append("reveal")

        def on_close(self):
            events.append("close")

    page = Page()
    page.bind_key("enter", lambda: game.pop_to(page))
    page.bind_key("space", lambda: events.append("space"))
    game.push(page)
    game.backend.inject_key("enter")
    game.backend.inject_key("space")
    game.tick(.01)
    assert game.scenes == [page]
    assert events == ["space"]


@pytest.mark.parametrize("failed_close", [False, True])
def test_return_releases_all_removed_resources_once_and_preserves_target(game: Game, failed_close) -> None:
    """Timers and sprites follow scene ownership even when an exit hook fails."""
    game.assets.image_from_pil("dot", Image.new("RGBA", (2, 2)))
    callbacks, revealed = [], []
    close_error = RuntimeError("close failed")

    class Page(Scene):
        def __init__(self, name):
            self.name = name
            self.closes = 0

        def on_enter(self):
            self.sprite = self.add_sprite(Sprite("dot"))
            self.every(.01, lambda: callbacks.append(self.name))
            self.ui.add(Label(self.name))

        def on_close(self):
            self.closes += 1
            if failed_close and self.name == "top":
                raise close_error

        def on_reveal(self):
            revealed.append(self.name)

    base, middle, top = (Page(name) for name in ("base", "middle", "top"))
    for page in (base, middle, top):
        game.push(page)
    base_ui = base.ui
    if failed_close:
        with pytest.raises(RuntimeError) as caught:
            game.pop_to(base)
        assert caught.value is close_error
    else:
        game.pop_to(base)

    assert game.scenes == [base]
    assert base.game is game and base.ui is base_ui and not base.sprite.is_removed
    assert base.closes == 0
    assert revealed == ["base"]
    for removed in (middle, top):
        assert removed.game is None and removed.sprite.is_removed
        assert removed.closes == 1
    game.tick(.02)
    assert callbacks and set(callbacks) == {"base"}
    assert [text["text"] for text in game.backend.texts] == ["base"]
    game.close()
    assert [page.closes for page in (base, middle, top)] == [1, 1, 1]


def test_missing_target_fails_atomically_after_the_input_handler(game: Game) -> None:
    """An equal but absent scene cannot cause partial removal or a wrong return."""
    events = []

    class EqualPage(Scene):
        def __eq__(self, other):
            return isinstance(other, EqualPage)

        def on_reveal(self):
            events.append("reveal")

        def on_close(self):
            events.append("close")

    base, top, absent = EqualPage(), EqualPage(), EqualPage()
    game.push(base)
    game.push(top)

    def return_to_absent():
        game.pop_to(absent)
        events.append("handler completed")

    top.bind_key("enter", return_to_absent)
    game.backend.inject_key("enter")
    with pytest.raises(ValueError, match="not on the scene stack"):
        game.tick(.01)
    assert len(game.scenes) == 2 and game.scenes[0] is base and game.scene is top
    assert events == ["handler completed"]
    game.pop_to(base)
    assert len(game.scenes) == 1 and game.scene is base


@pytest.mark.parametrize("phase", ["on_enter", "update"])
def test_return_stays_deferred_during_lifecycle_and_update(game: Game, phase) -> None:
    """Callbacks finish with their original top scene before a return applies."""
    base, middle = Scene(), Scene()
    finished = []

    class Return(Scene):
        def request_return(self):
            self.game.pop_to(base)
            assert self.game.scene is self
            assert len(self.game.scenes) == 3
            finished.append(phase)

        def on_enter(self):
            if phase == "on_enter":
                self.request_return()

        def update(self, dt):
            if phase == "update":
                self.request_return()

    game.push(base)
    game.push(middle)
    game.push(Return())
    game.tick(.01)
    assert game.scenes == [base]
    assert finished == [phase]


def test_queued_return_applies_after_preceding_pushes(game: Game) -> None:
    """A return sees earlier queued operations, including newly entered targets."""
    events = []

    class Page(Scene):
        def on_reveal(self):
            events.append("reveal")

        def on_close(self):
            events.append("close")

    base, target, cover = Page(), Page(), Page()
    game.push(base)

    def open_and_return():
        game.push(target)
        game.push(cover)
        game.pop_to(target)
        assert game.scene is base

    base.bind_key("enter", open_and_return)
    game.backend.inject_key("enter")
    game.tick(.01)
    assert game.scenes == [base, target]
    assert events == ["close", "reveal"]

    def briefly_cover():
        game.push(cover)
        game.pop_to(target)

    target.bind_key("space", briefly_cover)
    game.backend.inject_key("space")
    game.tick(.01)
    assert game.scenes == [base, target]
    assert events == ["close", "reveal", "close", "reveal"]
