"""ParticleEmitter — managed lightweight sprite particles.

A :class:`ParticleEmitter` spawns short-lived :class:`Sprite` particles on
the :attr:`~saga2d.rendering.layers.RenderLayer.EFFECTS` layer.  Each
particle has randomised velocity, lifetime, and optional opacity fade-out.

Two spawning modes are supported:

* **Burst** — spawn a batch of particles at once (explosions, impacts)::

      emitter = ParticleEmitter("sprites/spark", position=(500, 300))
      emitter.burst(30)

* **Continuous** — spawn at a steady rate per second (fire, smoke)::

      emitter = ParticleEmitter("sprites/smoke", position=(100, 400))
      emitter.continuous(rate=20)

Call :meth:`stop` to halt spawning; existing particles live out their
remaining lifetime.  Call :meth:`remove` to kill everything immediately.

The emitter auto-registers in ``Game._particle_emitters`` on construction
and is updated each frame by ``Game._update_particles(dt)``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from saga2d.rendering.layers import RenderLayer, SpriteAnchor

if TYPE_CHECKING:
    from saga2d.rendering.sprite import Sprite


# ---------------------------------------------------------------------------
# Internal particle state
# ---------------------------------------------------------------------------


@dataclass
class _Particle:
    """Lightweight bookkeeping for one living particle."""

    sprite: Sprite
    vx: float  # pixels / sec
    vy: float  # pixels / sec
    remaining: float  # seconds until death
    total_lifetime: float  # initial lifetime (for fade ratio)
    fade_out: bool


# ---------------------------------------------------------------------------
# ParticleEmitter
# ---------------------------------------------------------------------------


class ParticleEmitter:
    """Managed particle spawner.

    Supports two modes: **burst** (one-shot batch) and **continuous**
    (steady rate per second).  Burst emitters are self-cleaning — the
    emitter becomes inactive once all particles expire and is
    automatically deregistered by the game loop.

    **Continuous emitters must be explicitly stopped** by calling
    :meth:`stop` (cease spawning, let particles die naturally) or
    :meth:`remove` (kill everything immediately).  Typically this is
    done in the owning scene's :meth:`~saga2d.scene.Scene.on_exit`
    to prevent the emitter from firing in the background after the
    scene is no longer active.

    Parameters:
        image:     Asset name (or list of names for variety — one chosen at
                   random per particle).
        position:  ``(x, y)`` spawn point in world coordinates.
        count:     Default number of particles for :meth:`burst`.
        speed:     ``(min, max)`` random speed range in pixels per second.
        direction: ``(min_deg, max_deg)`` random angle range in degrees
                   (0 = right, 90 = down in y-down coordinates).
        lifetime:  ``(min_sec, max_sec)`` random lifetime range.
        fade_out:  If ``True``, particle opacity lerps from 255 to 0 over
                   its lifetime.
        layer:     Render layer for particle sprites.
    """

    def __init__(
        self,
        image: str | list[str],
        position: tuple[float, float],
        count: int = 10,
        speed: tuple[float, float] = (50, 200),
        direction: tuple[float, float] = (0, 360),
        lifetime: tuple[float, float] = (0.3, 0.8),
        fade_out: bool = True,
        layer: RenderLayer = RenderLayer.EFFECTS,
    ) -> None:
        from saga2d.rendering.sprite import _current_game

        if _current_game is None:
            raise RuntimeError(
                "No active Game. Create a Game instance before creating "
                "a ParticleEmitter."
            )

        self._game: Any = _current_game
        self._images: list[str] = image if isinstance(image, list) else [image]
        self._x = float(position[0])
        self._y = float(position[1])
        self._count = count
        self._speed = speed
        self._direction = direction
        self._lifetime = lifetime
        self._fade_out = fade_out
        self._layer = layer

        # Living particles.
        self._particles: list[_Particle] = []

        # Continuous spawning state.
        self._continuous_rate: float = 0.0  # particles per second (0 = off)
        self._spawn_accum: float = 0.0  # fractional particle accumulator

        # Register for automatic updates.
        self._game._particle_emitters.add(self)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def position(self) -> tuple[float, float]:
        """The spawn point for new particles."""
        return (self._x, self._y)

    @position.setter
    def position(self, value: tuple[float, float]) -> None:
        self._x = float(value[0])
        self._y = float(value[1])

    @property
    def is_active(self) -> bool:
        """``True`` if the emitter is still spawning or any particles live."""
        return self._continuous_rate > 0 or len(self._particles) > 0

    # ------------------------------------------------------------------
    # Spawning modes
    # ------------------------------------------------------------------

    def burst(self, count: int | None = None) -> None:
        """Spawn *count* particles at once.

        Uses the constructor's *count* if the argument is ``None``.
        """
        n = self._count if count is None else count
        if n <= 0:
            return
        # Ensure the emitter is registered (may have been auto-removed).
        self._game._particle_emitters.add(self)
        for _ in range(n):
            self._spawn_particle()

    def continuous(self, rate: float) -> None:
        """Start spawning at *rate* particles per second.

        Call ``stop()`` to cease continuous spawning.
        """
        self._continuous_rate = rate
        self._spawn_accum = 0.0
        # Ensure the emitter is registered (may have been auto-removed).
        self._game._particle_emitters.add(self)

    def stop(self) -> None:
        """Stop spawning.  Existing particles continue until death."""
        self._continuous_rate = 0.0
        self._spawn_accum = 0.0

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        """Advance all particles: move, age, fade, remove dead ones.

        Also spawns new particles if in continuous mode.
        """
        # --- Continuous spawning ---
        if self._continuous_rate > 0:
            self._spawn_accum += self._continuous_rate * dt
            while self._spawn_accum >= 1.0:
                self._spawn_particle()
                self._spawn_accum -= 1.0

        # --- Update existing particles ---
        alive: list[_Particle] = []
        for p in self._particles:
            p.remaining -= dt
            if p.remaining <= 0:
                p.sprite.remove()
                continue

            # Move.
            p.sprite.x = p.sprite._x + p.vx * dt
            p.sprite.y = p.sprite._y + p.vy * dt

            # Fade.
            if p.fade_out and p.total_lifetime > 0:
                ratio = p.remaining / p.total_lifetime
                p.sprite.opacity = int(255 * max(0.0, ratio))

            alive.append(p)

        self._particles = alive

    # ------------------------------------------------------------------
    # Immediate removal
    # ------------------------------------------------------------------

    def remove(self) -> None:
        """Stop spawning and remove all living particles immediately."""
        self.stop()
        for p in self._particles:
            p.sprite.remove()
        self._particles.clear()
        self._game._particle_emitters.discard(self)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _spawn_particle(self) -> None:
        """Create one particle sprite with randomised velocity and lifetime."""
        from saga2d.rendering.sprite import Sprite

        image_name = random.choice(self._images)

        sprite = Sprite(
            image_name,
            position=(self._x, self._y),
            anchor=SpriteAnchor.CENTER,
            layer=self._layer,
        )

        speed = random.uniform(self._speed[0], self._speed[1])
        angle_deg = random.uniform(self._direction[0], self._direction[1])
        angle_rad = math.radians(angle_deg)
        vx = speed * math.cos(angle_rad)
        vy = speed * math.sin(angle_rad)

        lt = random.uniform(self._lifetime[0], self._lifetime[1])

        self._particles.append(
            _Particle(
                sprite=sprite,
                vx=vx,
                vy=vy,
                remaining=lt,
                total_lifetime=lt,
                fade_out=self._fade_out,
            )
        )
