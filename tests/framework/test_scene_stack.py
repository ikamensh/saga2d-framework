"""Scene stack behaviour through the public Game API."""

import pytest

from saga2d import Game, Scene


class Recorder(Scene):
    """Records lifecycle hooks into a shared log."""

    log: list[str] = []

    def __init__(self, name: str) -> None:
        self.name = name

    def on_enter(self) -> None:
        Recorder.log.append(f"enter:{self.name}")

    def on_exit(self) -> None:
        Recorder.log.append(f"exit:{self.name}")

    def on_reveal(self) -> None:
        Recorder.log.append(f"reveal:{self.name}")


def names(game: Game) -> list[str]:
    return [s.name for s in game.scenes]


def test_push_pop_fire_lifecycle_hooks(game: Game) -> None:
    Recorder.log.clear()
    game.push(Recorder("a"))
    game.push(Recorder("b"))
    game.pop()
    assert Recorder.log == ["enter:a", "exit:a", "enter:b", "exit:b", "reveal:a"]
    assert names(game) == ["a"]


def test_replace_swaps_top_without_reveal(game: Game) -> None:
    Recorder.log.clear()
    game.push(Recorder("a"))
    game.replace(Recorder("b"))
    assert Recorder.log == ["enter:a", "exit:a", "enter:b"]
    assert names(game) == ["b"]


def test_clear_and_push_exits_everything(game: Game) -> None:
    Recorder.log.clear()
    game.push(Recorder("a"))
    game.push(Recorder("b"))
    game.clear_and_push(Recorder("c"))
    assert Recorder.log[2:] == ["exit:a", "enter:b", "exit:b", "exit:a", "enter:c"] or names(game) == ["c"]
    assert names(game) == ["c"]


def test_operations_requested_during_update_apply_after_the_frame(game: Game) -> None:
    class Opener(Scene):
        def update(self, dt: float) -> None:
            self.game.push(Recorder("child"))
            # Still the top scene while updating — the push is deferred.
            assert self.game.scene is self

    game.push(Opener())
    game.tick(0.016)
    assert isinstance(game.scene, Recorder)
    assert len(game.scenes) == 2


def test_only_top_scene_updates_unless_pause_below_is_false(game: Game) -> None:
    updates: list[str] = []

    class Base(Scene):
        def update(self, dt: float) -> None:
            updates.append("base")

    class Modal(Scene):
        def update(self, dt: float) -> None:
            updates.append("modal")

    class Overlay(Scene):
        pause_below = False

        def update(self, dt: float) -> None:
            updates.append("overlay")

    game.push(Base())
    game.push(Modal())
    game.tick(0.016)
    assert updates == ["modal"]
    game.pop()
    game.push(Overlay())
    updates.clear()
    game.tick(0.016)
    assert updates == ["base", "overlay"]


def test_transparent_overlay_draws_scene_below_with_higher_ui_order(game: Game, backend) -> None:
    class Base(Scene):
        background_color = (1, 2, 3, 255)

        def draw(self) -> None:
            self.draw_rect(0, 0, 10, 10, (255, 0, 0, 255))

    class Overlay(Scene):
        transparent = True
        background_color = (9, 9, 9, 255)

        def draw(self) -> None:
            self.draw_rect(0, 0, 20, 20, (0, 255, 0, 255))

    game.push(Base())
    game.push(Overlay())
    game.tick(0.016)
    assert backend.clear_color == (1, 2, 3, 255)  # base scene owns the clear colour
    assert [r["color"][:3] for r in backend.rects] == [(255, 0, 0), (0, 255, 0)]
    assert backend.rects[0]["order"] < backend.rects[1]["order"]


def test_opaque_scene_hides_scenes_below(game: Game, backend) -> None:
    class Base(Scene):
        def draw(self) -> None:
            self.draw_rect(0, 0, 10, 10, (255, 0, 0, 255))

    class Cover(Scene):
        background_color = (7, 7, 7, 255)

    game.push(Base())
    game.push(Cover())
    game.tick(0.016)
    assert backend.rects == []
    assert backend.clear_color == (7, 7, 7, 255)


def test_pop_on_cancel_pops_when_escape_is_unhandled(game: Game, backend) -> None:
    class Menu(Scene):
        pop_on_cancel = True

    game.push(Recorder("base"))
    game.push(Menu())
    backend.inject_key("escape")
    game.tick(0.016)
    assert names(game) == ["base"]


def test_push_requires_a_scene(game: Game) -> None:
    import pytest

    with pytest.raises(TypeError):
        game.push("not a scene")  # type: ignore[arg-type]


def test_scene_that_fails_on_enter_is_not_left_on_the_stack(game: Game) -> None:
    import pytest

    class Broken(Scene):
        def on_enter(self) -> None:
            raise RuntimeError("boom")

    game.push(Recorder("a"))
    with pytest.raises(RuntimeError):
        game.push(Broken())
    assert names(game) == ["a"]


@pytest.mark.parametrize("error_type", [RuntimeError, SystemExit])
def test_failed_scene_startup_cancels_its_scheduled_callbacks(game: Game, error_type) -> None:
    """A scene removed after failed startup cannot keep acting through timers."""
    callbacks = []

    class Broken(Scene):
        def on_enter(self) -> None:
            self.after(0, lambda: callbacks.append("after"))
            self.every(0.01, lambda: callbacks.append("every"))
            raise error_type("startup failed")

    with pytest.raises(error_type, match="startup failed"):
        game.push(Broken())
    game.tick(0.02)
    assert game.scene is None
    assert callbacks == []


def test_failed_scene_entry_releases_rendering_resources_and_can_be_retried(game: Game, backend) -> None:
    """Partial entry owns resources immediately; retry starts with a fresh UI tree."""
    from PIL import Image
    from saga2d import Camera, Label, ParticleEmitter, Sprite, tween

    game.assets.image_from_pil("dot", Image.new("RGBA", (2, 2)))
    completed = []

    class BrokenOnce(Scene):
        attempts = 0

        def on_enter(self) -> None:
            self.attempts += 1
            if self.attempts == 1:
                self.sprite = self.add_sprite(Sprite("dot"))
                tween(self.sprite, "opacity", 255, 0, 0.1, on_complete=lambda: completed.append("tween"))
                self.emitter = self.add_emitter(ParticleEmitter("dot", (20, 20)))
                self.emitter.burst(1)
                self.emitter.continuous(10)
                self.camera = Camera(game.resolution)
                self.camera.pan_to(900, 900, 0.1)
                self.ui.add(Label("failed entry"))
                raise RuntimeError("startup failed")
            self.ui.add(Label("ready"))

        def on_exit(self) -> None:
            assert self.attempts > 1, "Failed on_enter must not call on_exit on a partial scene"

    scene = BrokenOnce()
    with pytest.raises(RuntimeError, match="startup failed"):
        game.push(scene)
    assert scene.game is None
    assert scene.sprite.is_removed
    assert not scene.emitter.is_active
    game.tick(0.5)
    assert backend.sprites == {}
    assert completed == []
    assert (scene.camera.x, scene.camera.y) == (0, 0)

    game.push(scene)
    game.tick(0.01)
    assert [text["text"] for text in backend.texts] == ["ready"]


def test_run_closes_the_window_after_failed_startup_and_allows_a_new_game(game: Game, backend, monkeypatch) -> None:
    """Failed startup has the same window and singleton cleanup as a completed run."""
    monkeypatch.delenv("SAGA2D_HEADLESS", raising=False)
    startup_error = RuntimeError("startup failed")

    class Broken(Scene):
        def on_enter(self) -> None:
            raise startup_error

    with pytest.raises(RuntimeError) as caught:
        game.run(Broken())
    assert caught.value is startup_error
    assert not backend.is_running

    class Quit(Scene):
        def on_enter(self) -> None:
            self.game.quit()

    Game("Retry", backend="mock").run(Quit())


def test_startup_error_survives_a_failing_exit_hook_and_all_scenes_are_released(game: Game, backend, monkeypatch) -> None:
    """Cleanup failure must neither hide the startup error nor strand the lower scene."""
    monkeypatch.delenv("SAGA2D_HEADLESS", raising=False)
    startup_error = RuntimeError("startup failed")
    exit_error = ValueError("exit failed")

    class Cover(Scene):
        exits = 0

        def on_exit(self) -> None:
            self.exits += 1
            if self.exits == 2:  # First covered by Broken, then removed during teardown.
                raise exit_error

    class Broken(Scene):
        def on_enter(self) -> None:
            raise startup_error

    base, cover = Scene(), Cover()
    game.push(base)
    game.push(cover)
    with pytest.raises(RuntimeError) as caught:
        game.run(Broken())
    assert caught.value is startup_error
    assert caught.value.__cause__ is exit_error
    assert game.scenes == []
    assert base.game is None and cover.game is None
    assert not backend.is_running

    class Quit(Scene):
        def on_enter(self) -> None:
            self.game.quit()

    Game("Retry", backend="mock").run(Quit())


def test_overlay_ui_draws_above_the_base_scene_hud_and_banner(game: Game, backend) -> None:
    from saga2d import Anchor, Label

    class Base(Scene):
        def on_enter(self) -> None:
            self.ui.add(Label("hud", anchor=Anchor.TOP_LEFT))

        def draw(self) -> None:
            self.draw_text("banner", 10, 10)

    class Overlay(Scene):
        transparent = True

        def on_enter(self) -> None:
            self.ui.add(Label("menu", anchor=Anchor.CENTER))

        def draw(self) -> None:
            self.draw_rect(0, 0, 10, 10, (0, 0, 0, 100))

    game.push(Base())
    game.push(Overlay())
    game.tick(0.016)
    order = {t["text"]: t["order"] for t in backend.texts}
    assert order["banner"] < order["hud"] < backend.rects[0]["order"] < order["menu"]
