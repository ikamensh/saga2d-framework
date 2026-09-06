"""saga2d.effects: text that rises and fades, pulses, bursts, sprite reactions, banners and toasts."""

import random

from PIL import Image

from saga2d import Camera, Game, Scene, Sprite
from saga2d.effects import Banner, Burst, Dissolve, Effects, FloatingText, HitReaction, Pulse, Toast, hop


class Stage(Scene):
    def on_enter(self) -> None:
        self.camera = Camera(self.game.resolution)
        self.effects = Effects()
        for key in ("ring", "spark", "blank"):
            self.game.assets.image_from_pil(key, Image.new("RGBA", (16, 16), (255, 255, 255, 255)))

    def update(self, dt: float) -> None:
        self.effects.update(dt)

    def draw(self) -> None:
        self.effects.draw(self)


def stage(game: Game) -> Stage:
    scene = Stage()
    game.push(scene)
    game.tick(1 / 60)
    return scene


def tick(game: Game, seconds: float) -> None:
    for _ in range(int(seconds * 60) + 1):
        game.tick(1 / 60)


def texts(backend) -> list[dict]:
    return list(backend.texts)


def test_floating_text_rises_fades_and_is_gone_after_its_duration(game: Game, backend) -> None:
    scene = stage(game)
    scene.effects.add(FloatingText("-7", (100, 100), (255, 96, 84, 255), duration=0.6, rise=30))
    game.tick(1 / 60)
    first = next(t for t in texts(backend) if t["text"] == "-7")
    tick(game, 0.3)
    later = next(t for t in texts(backend) if t["text"] == "-7")
    assert later["y"] < first["y"] and later["color"][3] < first["color"][3]
    tick(game, 0.5)
    assert not any(t["text"] == "-7" for t in texts(backend)) and len(scene.effects) == 0


def test_pulse_draws_growing_rings_with_the_image_it_is_given(game: Game, backend) -> None:
    scene = stage(game)
    scene.effects.add(Pulse((50, 50), (255, 200, 0, 255), radius=(10, 40), rings=2, duration=0.5, image="blank"))
    game.tick(1 / 60)
    early = [c["radius"] for c in backend.circles]
    tick(game, 0.25)
    late = [c["radius"] for c in backend.circles]
    assert early and late and max(late) > max(early)
    assert backend.images and backend.images[0]["image"] == game.assets.image("blank")
    tick(game, 0.5)
    assert not backend.circles and len(scene.effects) == 0


def test_burst_spawns_particles_and_removes_every_one(game: Game, backend) -> None:
    scene = stage(game)
    before = len(backend.sprites)
    scene.effects.add(Burst((80, 80), (255, 255, 255, 255), 12, rng=random.Random(1)))
    game.tick(1 / 60)
    assert len(backend.sprites) == before + 12
    tick(game, 1.0)
    assert len(backend.sprites) == before and len(scene.effects) == 0


def test_hit_reaction_and_dissolve_restore_then_remove_the_sprite(game: Game, backend) -> None:
    scene = stage(game)
    sprite = scene.add_sprite(Sprite("blank", position=(200, 200), size=(20, 20), tint=(0.2, 0.4, 0.6)))
    scene.effects.add(HitReaction(sprite, (0.2, 0.4, 0.6), source=(150, 200), duration=0.3))
    game.tick(1 / 60)
    assert sprite.tint == (1.0, 1.0, 1.0)
    tick(game, 0.4)
    assert sprite.tint == (0.2, 0.4, 0.6) and sprite.rotation == 0.0 and sprite.position == (200, 200)
    scene.effects.add(Dissolve(sprite, duration=0.3))
    tick(game, 0.2)
    assert sprite.size[0] < 20 and sprite.opacity < 255
    tick(game, 0.3)
    assert sprite.is_removed and sprite.sprite_id not in backend.sprites


def test_banner_replaces_a_running_banner_and_toast_lists_its_lines(game: Game, backend) -> None:
    scene = stage(game)
    scene.effects.add(Banner("Round 1", subtitle="go", hold=0.5))
    scene.effects.add(Banner("Round 2", hold=0.5))
    game.tick(1 / 60)
    shown = [t["text"] for t in texts(backend)]
    assert "Round 2" in shown and "Round 1" not in shown and len(scene.effects) == 1
    scene.effects.add(Toast("News", ["one", "two"], hold=0.5))
    tick(game, 0.5)
    shown = [t["text"] for t in texts(backend)]
    assert "News" in shown and "one" in shown and "two" in shown
    tick(game, 2.0)
    assert len(scene.effects) == 0


def test_hop_bounces_a_sprite_and_returns_it_home(game: Game) -> None:
    scene = stage(game)
    sprite = scene.add_sprite(Sprite("blank", position=(50, 50), size=(8, 8)))
    hop(sprite, (50, 50), height=10, speed=400)
    game.tick(1 / 60)
    assert sprite.y < 50
    tick(game, 0.5)
    assert sprite.position == (50, 50)
