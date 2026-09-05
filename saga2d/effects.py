"""Transient visual effects: floating text, pulses, bursts, hit reactions, banners, toasts.

A scene keeps an :class:`Effects` list, adds effects in response to game
events and calls ``update(dt)`` and ``draw(scene)`` every frame::

    self.effects = Effects()
    self.effects.add(FloatingText("-3", (x, y), (255, 96, 84, 255)))
    self.effects.add(Pulse((x, y), color, radius=(12, 60), rings=3))

World-space effects take a world position, so they work under any tile
projection.  Sprite effects (flash, knockback, dissolve) only touch the
sprite they are given and restore it when they finish.  :class:`Pulse`
and :class:`Burst` draw an image the game registers (a soft ring and a
spark by default: ``"ring"`` and ``"spark"``); text effects use the
theme's ``"floating"``, ``"banner"``, ``"banner_sub"``, ``"heading"``
and ``"body"`` styles, all of which have defaults.
"""

from __future__ import annotations

import math
import random

from saga2d.actions import MoveTo, Sequence
from saga2d.rendering import ParticleEmitter, RenderLayer, Sprite
from saga2d.scene import Scene

Color = tuple[int, int, int, int]


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in(t: float) -> float:
    return t * t * t


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _quantize(alpha: float) -> int:
    """Alpha in steps of 16 so fading text reuses cached labels."""
    return max(0, min(255, int(alpha) // 16 * 16))


def hop(sprite: Sprite | None, home: tuple[float, float], height: float = 9.0, speed: float = 260.0) -> None:
    """Quick bounce of *sprite* up from *home* and back (selection feedback)."""
    if sprite is None or sprite.is_removed:
        return
    x, y = home
    sprite.do(Sequence(MoveTo((x, y - height), speed=speed), MoveTo((x, y), speed=speed)))


class Effect:
    """Waits *delay* seconds, then runs for *duration*.  Subclasses override
    :meth:`start`, :meth:`advance`, :meth:`finish` and :meth:`draw`."""

    def __init__(self, duration: float, delay: float = 0.0) -> None:
        self.duration = duration
        self.elapsed = -delay
        self.started = False
        self.done = False
        self.cancelled = False

    @property
    def t(self) -> float:
        """Progress 0..1 through the active phase."""
        if self.duration <= 0:
            return 1.0
        return max(0.0, min(1.0, self.elapsed / self.duration))

    @property
    def active(self) -> bool:
        return self.started and not self.done

    def update(self, dt: float) -> bool:
        """Advance; returns ``True`` once the effect is over."""
        self.elapsed += dt
        if self.elapsed < 0:
            return False
        if not self.started:
            self.started = True
            self.start()
        if self.cancelled or self.elapsed >= self.duration:
            self.end()
            return True
        self.advance()
        return False

    def end(self) -> None:
        if not self.done:
            self.done = True
            if self.started:
                self.finish()

    def start(self) -> None:
        pass

    def advance(self) -> None:
        pass

    def finish(self) -> None:
        pass

    def draw(self, scene: Scene) -> None:
        pass


class Effects:
    """The scene's list of live effects."""

    def __init__(self) -> None:
        self._items: list[Effect] = []

    def add(self, effect: Effect) -> Effect:
        if isinstance(effect, Banner):
            for old in [e for e in self._items if isinstance(e, Banner)]:
                old.end()
                self._items.remove(old)
        self._items.append(effect)
        return effect

    def update(self, dt: float) -> None:
        self._items = [e for e in self._items if not e.update(dt)]

    def draw(self, scene: Scene) -> None:
        for effect in self._items:
            if effect.active:
                effect.draw(scene)

    def clear(self) -> None:
        for effect in self._items:
            effect.end()
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


class FloatingText(Effect):
    """Text that rises and fades: damage numbers, "+1 pop", "Level 2!".

    Anchored to a world position but drawn in screen space (font scaled by
    the camera zoom) so it always sits above city labels and health bars;
    a dark pill behind it keeps it readable on any terrain.  Uses the
    theme's ``"floating"`` text style.
    """

    def __init__(
        self, text: str, position: tuple[float, float], color: Color, *,
        font_size: int = 18, rise: float = 30.0, duration: float = 0.9, delay: float = 0.0,
    ) -> None:
        super().__init__(duration, delay)
        self.text = text
        self.x, self.y = position
        self.color = color
        self.font_size = font_size
        self.rise = rise

    def draw(self, scene: Scene) -> None:
        t = self.t
        alpha = _quantize(self.color[3] * (1 - t * t))
        if alpha == 0:
            return
        camera = scene.camera
        assert camera is not None
        theme = scene.game.theme
        style = theme.get_text_style("floating")
        sx, sy = camera.world_to_screen(self.x, self.y - self.rise * ease_out(t))
        size = max(8, round(self.font_size * camera.zoom))
        tw, th = scene.game.backend.measure_text(self.text, size, style.font or theme.font)
        pill_h = th + 2
        scene.draw_rect(sx - tw / 2 - pill_h / 2, sy - pill_h / 2, tw + pill_h, pill_h, (10, 12, 20, _quantize(alpha * 0.55)), radius=pill_h / 2)
        scene.draw_text(self.text, sx, sy, style="floating", font_size=size, color=(*self.color[:3], alpha), anchor_x="center", anchor_y="center")


class Pulse(Effect):
    """Rings of *color* expanding from a world position: a capture, a level up, a rally point."""

    def __init__(
        self, position: tuple[float, float], color: Color, *,
        radius: tuple[float, float] = (14.0, 58.0), rings: int = 2, duration: float = 0.9, delay: float = 0.0, image: str = "ring",
    ) -> None:
        super().__init__(duration, delay)
        self.x, self.y = position
        self.color = color
        self.radius = radius
        self.rings = rings
        self.image = image

    def draw(self, scene: Scene) -> None:
        r0, r1 = self.radius
        for i in range(self.rings):
            t = max(0.0, min(1.0, self.t * (1 + 0.25 * i) - 0.25 * i))
            if t <= 0:
                continue
            radius = lerp(r0, r1, ease_out(t))
            alpha = int(self.color[3] * (1 - t) * 0.6)
            scene.draw_circle(self.x, self.y, radius, (*self.color[:3], alpha), space="world", layer=RenderLayer.EFFECTS)
            ring = radius / 0.42  # the "ring" texture's radius is 42% of its size
            scene.draw_image(self.image, self.x - ring / 2, self.y - ring / 2, ring, ring, opacity=(1 - t) * 0.9, space="world", layer=RenderLayer.EFFECTS)


class Burst(Effect):
    """Spark burst at a world position.

    Holds the emitter until every particle has died: ``Game`` tracks emitters
    weakly, so a fire-and-forget burst is collected at once and its particles
    are never updated or removed.
    """

    LIFETIME = (0.25, 0.6)

    def __init__(
        self, position: tuple[float, float], color: Color, count: int, *,
        rng: random.Random | None = None, delay: float = 0.0, image: str = "spark", size: float = 14.0, speed: tuple[float, float] = (60, 220),
    ) -> None:
        super().__init__(self.LIFETIME[1] + 0.1, delay)
        self.count = count
        self.emitter = ParticleEmitter(
            image, position=position, speed=speed, lifetime=self.LIFETIME, size=(size, size), shrink=True,
            tint=(color[0] / 255, color[1] / 255, color[2] / 255), rng=rng,
        )

    def start(self) -> None:
        self.emitter.burst(self.count)

    def advance(self) -> None:
        if not self.emitter.is_active:
            self.cancelled = True

    def finish(self) -> None:
        self.emitter.remove()


class HitReaction(Effect):
    """Flash a sprite white, wobble it, and nudge it away from *source*.

    *knockback* moves the sprite and restores it, so use it only on sprites
    that are standing still; a moving sprite gets the flash and wobble only.
    """

    def __init__(
        self, sprite: Sprite, base_tint: tuple[float, float, float], *,
        source: tuple[float, float] | None = None, knockback: float = 6.0, wobble: float = 12.0,
        duration: float = 0.35, delay: float = 0.0,
    ) -> None:
        super().__init__(duration, delay)
        self.sprite = sprite
        self.base_tint = base_tint
        self.knockback = knockback if source is not None else 0.0
        self.wobble = wobble
        self.direction = (0.0, 0.0)
        self.origin = (0.0, 0.0)
        if source is not None:
            dx, dy = sprite.position[0] - source[0], sprite.position[1] - source[1]
            length = math.hypot(dx, dy) or 1.0
            self.direction = (dx / length, dy / length)

    def start(self) -> None:
        if self.sprite.is_removed:
            self.cancelled = True
            return
        self.origin = self.sprite.position
        self.sprite.tint = (1.0, 1.0, 1.0)

    def advance(self) -> None:
        sprite = self.sprite
        if sprite.is_removed:
            self.cancelled = True
            return
        t = self.t
        sprite.rotation = self.wobble * math.sin(t * math.pi * 5) * (1 - t)
        if self.knockback:
            k = self.knockback * math.sin(math.pi * t)
            sprite.position = (self.origin[0] + self.direction[0] * k, self.origin[1] + self.direction[1] * k)
        if t > 0.4:
            sprite.tint = self.base_tint

    def finish(self) -> None:
        if self.sprite.is_removed:
            return
        self.sprite.rotation = 0.0
        self.sprite.tint = self.base_tint
        if self.knockback:
            self.sprite.position = self.origin


class Dissolve(Effect):
    """Shrink, spin and fade a sprite, then remove it (a unit dying)."""

    def __init__(self, sprite: Sprite, *, duration: float = 0.45, delay: float = 0.0) -> None:
        super().__init__(duration, delay)
        self.sprite = sprite
        self.size = sprite.size

    def start(self) -> None:
        if self.sprite.is_removed:
            self.cancelled = True

    def advance(self) -> None:
        sprite = self.sprite
        if sprite.is_removed:
            self.cancelled = True
            return
        t = self.t
        scale = 1 - ease_in(t)
        sprite.size = (self.size[0] * scale, self.size[1] * scale)
        sprite.opacity = int(255 * (1 - t))
        sprite.rotation = 40 * t

    def finish(self) -> None:
        self.sprite.remove()


class Banner(Effect):
    """Turn banner: slides in from the left, holds, slides out to the right."""

    SLIDE = 0.35

    def __init__(self, text: str, *, subtitle: str = "", accent: Color = (255, 255, 255, 255), hold: float = 1.2) -> None:
        super().__init__(hold + 2 * self.SLIDE)
        self.text = text
        self.subtitle = subtitle
        self.accent = accent
        self.hold = hold

    def _phase(self, width: int) -> tuple[float, float]:
        """``(x offset, opacity)`` for the current moment."""
        e = self.elapsed
        if e < self.SLIDE:
            p = ease_out(e / self.SLIDE)
            return lerp(-width * 0.6, 0.0, p), p
        if e < self.SLIDE + self.hold:
            return 0.0, 1.0
        p = ease_in((e - self.SLIDE - self.hold) / self.SLIDE)
        return lerp(0.0, width * 0.6, p), 1 - p

    def draw(self, scene: Scene) -> None:
        w, h = scene.game.resolution
        offset, opacity = self._phase(w)
        alpha = _quantize(255 * opacity)
        band_y, band_h = h * 0.40, 84
        scene.draw_rect(0, band_y, w, band_h, (0, 0, 0, int(175 * opacity)))
        scene.draw_rect(0, band_y, w, 2, (*self.accent[:3], int(180 * opacity)))
        scene.draw_rect(0, band_y + band_h - 2, w, 2, (*self.accent[:3], int(180 * opacity)))
        cx = w / 2 + offset
        scene.draw_text(self.text, cx, band_y + 34, style="banner", color=(255, 255, 255, alpha), anchor_x="center", anchor_y="center")
        if self.subtitle:
            scene.draw_text(self.subtitle, cx, band_y + 66, style="banner_sub", color=(*self.accent[:3], alpha), anchor_x="center", anchor_y="center")


class Toast(Effect):
    """Notice that slides in at the top right: a title and a few lines."""

    SLIDE = 0.4
    MARGIN = 14
    TOP = 56
    PAD = 12

    def __init__(self, title: str, lines: list[str], *, accent: Color = (255, 120, 90, 255), hold: float = 6.0, top: int | None = None) -> None:
        super().__init__(hold + 2 * self.SLIDE)
        self.title = title
        self.lines = lines
        self.accent = accent
        self.hold = hold
        self.top = self.TOP if top is None else top

    def _offset(self, box_w: float) -> float:
        e = self.elapsed
        if e < self.SLIDE:
            return lerp(box_w + self.MARGIN, 0.0, ease_out(e / self.SLIDE))
        if e < self.SLIDE + self.hold:
            return 0.0
        return lerp(0.0, box_w + self.MARGIN, ease_in((e - self.SLIDE - self.hold) / self.SLIDE))

    def draw(self, scene: Scene) -> None:
        theme = scene.game.theme
        backend = scene.game.backend
        heading, body = theme.get_text_style("heading"), theme.get_text_style("body")
        widths = [backend.measure_text(self.title, heading.font_size, heading.font or theme.font)[0]]
        widths += [backend.measure_text(line, body.font_size, body.font or theme.font)[0] for line in self.lines]
        line_h = body.font_size + 8
        box_w = max(260, max(widths) + 2 * self.PAD + 6)
        box_h = 2 * self.PAD + heading.font_size + 10 + line_h * len(self.lines)
        w, _ = scene.game.resolution
        x = w - self.MARGIN - box_w + self._offset(box_w)
        y = self.top
        scene.draw_rect(x, y, box_w, box_h, (16, 20, 32, 240), border_color=(255, 255, 255, 30), border_width=1, radius=10)
        scene.draw_rect(x + 8, y + 10, 3, box_h - 20, self.accent, radius=1.5)
        tx = x + self.PAD + 8
        scene.draw_text(self.title, tx, y + self.PAD + heading.font_size / 2, style="heading", anchor_y="center")
        ly = y + self.PAD + heading.font_size + 10
        for line in self.lines:
            scene.draw_text(line, tx, ly + line_h / 2, style="body", anchor_y="center")
            ly += line_h
