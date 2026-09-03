"""ParticleEmitter — short-lived sprites with velocity and fade.

::

    burst = ParticleEmitter("spark", position=(500, 300))
    burst.burst(30)                          # explosion
    smoke = ParticleEmitter("puff", position=(100, 400))
    smoke.continuous(rate=20)                # steady stream; call stop()

Burst emitters clean themselves up once every particle has died.
Continuous emitters run until :meth:`stop` or :meth:`remove`; registering
one with :meth:`Scene.add_emitter` removes it when the scene exits.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from saga2d.rendering.layers import RenderLayer, SpriteAnchor

if TYPE_CHECKING:
    from saga2d.backends.base import Space
    from saga2d.rendering.sprite import Sprite


@dataclass
class _Particle:
    sprite: Sprite
    vx: float
    vy: float
    remaining: float
    lifetime: float


class ParticleEmitter:
    """Parameters:
        image:     Asset name, or a list of names (random pick per particle).
        position:  Spawn point.
        count:     Default particle count for :meth:`burst`.
        speed:     ``(min, max)`` pixels per second.
        direction: ``(min_deg, max_deg)``; 0 = right, 90 = down.
        lifetime:  ``(min_s, max_s)``.
        size:      Drawn particle size, or ``None`` for image pixel size.
        fade_out:  Fade opacity to zero over each particle's life.
        shrink:    Scale size to zero over each particle's life.
        tint:      Sprite tint for every particle.
        rng:       Seeded :class:`random.Random` for deterministic output.
    """

    def __init__(
        self,
        image: str | list[str],
        position: tuple[float, float],
        *,
        count: int = 10,
        speed: tuple[float, float] = (50, 200),
        direction: tuple[float, float] = (0, 360),
        lifetime: tuple[float, float] = (0.3, 0.8),
        size: tuple[float, float] | None = None,
        fade_out: bool = True,
        shrink: bool = False,
        tint: tuple[float, float, float] = (1.0, 1.0, 1.0),
        layer: RenderLayer = RenderLayer.EFFECTS,
        space: Space = "world",
        rng: random.Random | None = None,
    ) -> None:
        from saga2d.rendering.sprite import _require_game

        self._game = _require_game()
        self._images = list(image) if isinstance(image, (list, tuple)) else [image]
        self._x, self._y = float(position[0]), float(position[1])
        self._count = count
        for name, (lo, hi) in (("speed", speed), ("direction", direction), ("lifetime", lifetime)):
            if not (math.isfinite(lo) and math.isfinite(hi)):
                raise ValueError(f"{name} range must be finite, got ({lo}, {hi})")
        if lifetime[0] < 0 or lifetime[1] < 0:
            raise ValueError(f"lifetime must be >= 0, got {lifetime}")
        self._speed = speed
        self._direction = direction
        self._lifetime = lifetime
        self._size = size
        self._fade_out = fade_out
        self._shrink = shrink
        self._tint = tint
        self._layer = layer
        self._space: Space = space
        self._rng: Any = rng if rng is not None else random
        self._particles: list[_Particle] = []
        self._rate = 0.0
        self._accum = 0.0
        self._game._particle_emitters.add(self)

    @property
    def position(self) -> tuple[float, float]:
        return (self._x, self._y)

    @position.setter
    def position(self, value: tuple[float, float]) -> None:
        self._x, self._y = float(value[0]), float(value[1])

    @property
    def is_active(self) -> bool:
        return self._rate > 0 or bool(self._particles)

    @property
    def particle_count(self) -> int:
        return len(self._particles)

    def burst(self, count: int | None = None) -> None:
        n = self._count if count is None else count
        self._game._particle_emitters.add(self)
        for _ in range(n):
            self._spawn()

    def continuous(self, rate: float) -> None:
        if not math.isfinite(rate) or rate < 0:
            raise ValueError(f"rate must be a finite number >= 0, got {rate}")
        self._rate = rate
        self._accum = 0.0
        self._game._particle_emitters.add(self)

    def stop(self) -> None:
        self._rate = 0.0
        self._accum = 0.0

    def remove(self) -> None:
        self.stop()
        for p in self._particles:
            p.sprite.remove()
        self._particles.clear()
        self._game._particle_emitters.discard(self)

    def update(self, dt: float) -> None:
        if self._rate > 0:
            self._accum += self._rate * dt
            while self._accum >= 1.0:
                self._spawn()
                self._accum -= 1.0
        alive: list[_Particle] = []
        for p in self._particles:
            p.remaining -= dt
            if p.remaining <= 0:
                p.sprite.remove()
                continue
            p.sprite.position = (p.sprite.x + p.vx * dt, p.sprite.y + p.vy * dt)
            ratio = p.remaining / p.lifetime if p.lifetime > 0 else 0.0
            if self._fade_out:
                p.sprite.opacity = int(255 * ratio)
            if self._shrink:
                w, h = self._base_size(p.sprite)
                p.sprite.size = (w * ratio, h * ratio)
            alive.append(p)
        self._particles = alive

    def _base_size(self, sprite: Sprite) -> tuple[float, float]:
        if self._size is not None:
            return self._size
        return (float(sprite._img_w), float(sprite._img_h))

    def _spawn(self) -> None:
        from saga2d.rendering.sprite import Sprite

        sprite = Sprite(
            self._rng.choice(self._images), position=(self._x, self._y), size=self._size,
            anchor=SpriteAnchor.CENTER, layer=self._layer, space=self._space, tint=self._tint,
        )
        speed = self._rng.uniform(*self._speed)
        angle = math.radians(self._rng.uniform(*self._direction))
        life = self._rng.uniform(*self._lifetime)
        self._particles.append(_Particle(sprite, speed * math.cos(angle), speed * math.sin(angle), life, life))
