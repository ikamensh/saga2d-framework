# Saga2D

A Python framework for 2D games where the developer writes game logic,
not engine plumbing — and Tribes, the Polytopia-style strategy game that
keeps it honest.

## What it is

Sprites in ordered layers under a zoomable camera, immediate-mode shapes
and text, a small UI toolkit with reactive labels, a scene stack with
overlays, declarative hotkeys, actions and particles for juice, and a
mock backend that makes all of it testable without a window.

## What it isn't

No tile maps, pathfinding, fog of war, entity model, combat system, drag
and drop, palette swaps or settings screens.  Those differ per game;
Tribes implements its own in a few hundred lines on top of the framework
and that is the intended shape of any saga2d game.

## Key decisions

- **GPU-first via pyglet.**  A view matrix moves the camera; a triangle
  soup draws the shapes; text is rasterised at native pixel density.
- **Two coordinate spaces, one integer draw order.**  World content sits
  below screen content; layers and stack position decide the rest.
- **Sprites have a logical size.**  Procedural art is generated at the
  display's density and drawn crisp at any zoom.
- **Hotkeys are first-class.**  A class-level dict, chords included,
  validated at import time.
- **Delete rather than deprecate.**  Features exist because a concrete
  game needed them in that exact form.
