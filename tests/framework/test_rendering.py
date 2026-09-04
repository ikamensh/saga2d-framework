"""Sprites, camera, world-space drawing, particles, actions, timers, tweens."""

import pytest
from PIL import Image

from saga2d import (
    Camera, Delay, Do, FadeOut, Game, MoveTo, ParticleEmitter, Remove, RenderLayer, Scene, Sequence, Sprite,
    SpriteAnchor, tween,
)


@pytest.fixture
def world(game: Game):
    """A game with a 16×16 procedural texture registered as ``"dot"``."""
    game.assets.image_from_pil("dot", Image.new("RGBA", (16, 16), (255, 255, 255, 255)))
    return game


def test_sprite_size_and_anchor_determine_backend_rectangle(world: Game, backend) -> None:
    s = Sprite("dot", position=(100, 100), size=(40, 20))
    rec = backend.sprites[s.sprite_id]
    assert (rec["x"], rec["y"], rec["width"], rec["height"]) == (80, 90, 40, 20)
    s2 = Sprite("dot", position=(100, 100), anchor=SpriteAnchor.BOTTOM_CENTER)
    rec2 = backend.sprites[s2.sprite_id]
    assert (rec2["x"], rec2["y"], rec2["width"], rec2["height"]) == (92, 84, 16, 16)


def test_sprite_property_changes_reach_the_backend_immediately(world: Game, backend) -> None:
    s = Sprite("dot", position=(0, 0))
    s.position = (10, 20)
    s.opacity = 128
    s.tint = (1.0, 0.5, 0.0)
    s.rotation = 90
    s.visible = False
    rec = backend.sprites[s.sprite_id]
    assert (rec["x"], rec["y"]) == (2, 12)
    assert rec["opacity"] == 128 and rec["tint"] == (1.0, 0.5, 0.0) and rec["rotation"] == 90 and rec["visible"] is False


def test_layers_order_sprites_and_y_sort_orders_within_a_layer(world: Game, backend) -> None:
    ground = Sprite("dot", layer=RenderLayer.BACKGROUND)
    near = Sprite("dot", position=(0, 100), y_sort=True)
    far = Sprite("dot", position=(0, 50), y_sort=True)
    order = lambda s: backend.sprites[s.sprite_id]["order"]  # noqa: E731
    assert order(ground) < order(far) < order(near)
    far.y = 200
    assert order(far) > order(near)


def test_scene_owned_sprites_are_removed_when_the_scene_leaves(world: Game, backend) -> None:
    class S(Scene):
        def on_enter(self) -> None:
            self.add_sprite(Sprite("dot"))

    world.push(S())
    assert len(backend.sprites) == 1
    world.pop()
    assert backend.sprites == {}


def test_sprites_survive_being_covered_by_an_overlay(world: Game, backend) -> None:
    class S(Scene):
        def on_enter(self) -> None:
            self.add_sprite(Sprite("dot"))

    world.push(S())
    world.push(Scene())
    assert len(backend.sprites) == 1


def test_camera_round_trips_screen_and_world_coordinates() -> None:
    cam = Camera((800, 600), zoom=1.5)
    cam.center_on(1000, 700)
    for point in [(0, 0), (400, 300), (799, 599)]:
        wx, wy = cam.screen_to_world(*point)
        sx, sy = cam.world_to_screen(wx, wy)
        assert (round(sx, 6), round(sy, 6)) == point
    assert cam.screen_to_world(400, 300) == (1000, 700)


def test_camera_clamps_to_world_bounds_and_centres_small_worlds() -> None:
    cam = Camera((800, 600), world_bounds=(0, 0, 2000, 2000))
    cam.center_on(-500, 5000)
    assert (cam.x, cam.y) == (0, 1400)
    small = Camera((800, 600), world_bounds=(0, 0, 400, 300))
    small.center_on(0, 0)
    assert (small.x, small.y) == (-200, -150)


def test_zoom_at_keeps_the_point_under_the_cursor_fixed() -> None:
    cam = Camera((800, 600))
    cam.scroll(100, 100)
    before = cam.screen_to_world(600, 150)
    cam.zoom_at(2.0, 600, 150)
    after = cam.screen_to_world(600, 150)
    assert (round(after[0], 6), round(after[1], 6)) == before
    assert cam.zoom == 2.0


def test_world_draw_calls_and_camera_reach_the_backend(world: Game, backend) -> None:
    class S(Scene):
        def on_enter(self) -> None:
            self.camera = Camera(self.game.resolution, zoom=2.0)
            self.camera.scroll(30, 40)

        def draw(self) -> None:
            self.draw_rect(0, 0, 10, 10, (1, 1, 1, 255), space="world", layer=RenderLayer.BACKGROUND)
            self.draw_text("x", 0, 0, space="world")
            self.draw_rect(0, 0, 10, 10, (2, 2, 2, 255))

    world.push(S())
    world.tick(0.016)
    assert backend.camera == (30.0, 40.0, 2.0)
    assert [r["space"] for r in backend.rects] == ["world", "screen"]
    assert backend.rects[0]["order"] < backend.rects[1]["order"]
    assert backend.texts[0]["space"] == "world"


def test_camera_key_scroll_moves_while_keys_are_held(world: Game, backend) -> None:
    class S(Scene):
        def on_enter(self) -> None:
            self.camera = Camera(self.game.resolution)
            self.camera.enable_key_scroll(speed=100, bindings={"right": ("d",), "left": ("a",), "up": ("w",), "down": ("s",)})

    scene = S()
    world.push(scene)
    backend.inject_key("d")
    world.tick(0.5)
    assert scene.camera.x == pytest.approx(50)
    backend.inject_key("d", type="key_release")
    world.tick(0.5)
    assert scene.camera.x == pytest.approx(50)


def test_burst_particles_live_then_die_and_the_emitter_retires(world: Game, backend) -> None:
    emitter = ParticleEmitter("dot", position=(50, 50), lifetime=(0.2, 0.2), fade_out=True)
    emitter.burst(5)
    assert len(backend.sprites) == 5
    world.tick(0.1)
    assert all(0 < s["opacity"] < 255 for s in backend.sprites.values())
    world.tick(0.15)
    assert backend.sprites == {}
    assert not emitter.is_active


def test_action_sequence_moves_then_removes_the_sprite(world: Game, backend) -> None:
    hits: list[str] = []
    s = Sprite("dot", position=(0, 0))
    s.do(Sequence(MoveTo((100, 0), speed=200), Do(lambda: hits.append("arrived")), Delay(0.1), FadeOut(0.1), Remove()))
    world.tick(0.25)
    assert s.position == (50, 0) and hits == []
    world.tick(0.25)
    assert s.position == (100, 0) and hits == ["arrived"]
    world.tick(0.1)
    world.tick(0.1)
    assert s.is_removed and backend.sprites == {}


def test_scene_timers_fire_and_are_cancelled_when_the_scene_leaves(world: Game) -> None:
    fired: list[str] = []

    class S(Scene):
        def on_enter(self) -> None:
            self.after(0.1, lambda: fired.append("once"))
            self.every(0.1, lambda: fired.append("tick"))

    world.push(S())
    world.tick(0.1)
    world.tick(0.1)
    assert fired == ["once", "tick", "tick"]
    world.pop()
    world.tick(0.1)
    assert fired == ["once", "tick", "tick"]


def test_tween_interpolates_a_property_and_completes(world: Game) -> None:
    s = Sprite("dot", position=(0, 0), opacity=0)
    done: list[bool] = []
    tween(s, "opacity", 0, 200, 1.0, on_complete=lambda: done.append(True))
    world.tick(0.5)
    assert s.opacity == 100
    world.tick(0.5)
    assert s.opacity == 200 and done == [True]


def test_save_and_load_round_trip_through_the_top_scene(tmp_path) -> None:
    class S(Scene):
        def __init__(self) -> None:
            self.turn = 1

        def get_save_state(self) -> dict:
            return {"turn": self.turn}

        def load_save_state(self, state: dict) -> None:
            self.turn = state["turn"]

    game = Game("Save Test", backend="mock", save_dir=tmp_path)
    try:
        scene = S()
        game.push(scene)
        scene.turn = 9
        game.save(1)
        scene.turn = 1
        assert game.load(1)["state"] == {"turn": 9}
        assert scene.turn == 9
        assert game.load(2) is None
    finally:
        game._teardown()


def test_fire_and_forget_burst_finishes_even_when_nothing_references_the_emitter(world: Game, backend) -> None:
    ParticleEmitter("dot", position=(10, 10), lifetime=(0.1, 0.1)).burst(4)
    import gc

    gc.collect()
    assert len(backend.sprites) == 4
    world.tick(0.2)
    assert backend.sprites == {}
