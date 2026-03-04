# Saga2D

Python framework for 2D sprite-based games. You write game logic, not engine plumbing.
A main menu with buttons is 10 lines. A scrolling world with animated units is 50.

## What it is

Rendering, animation, UI, audio, and scene management — the parts that are identical
whether you're building Heroes 2, Warcraft 2, or Baldur's Gate. Sprites in layers with
y-sorting. UI components with layout and theming. Scenes that push/pop like a stack.
Assets loaded by name. Input mapped to actions. Sound with channels and crossfade.
Camera over a world bigger than the screen. Tweening, timers, particles, save/load.

## What it isn't

No tile maps, pathfinding, fog of war, entity model, or combat system. Those differ
per game. The framework renders sprites wherever you put them — your game decides what
a "tile" or "unit" or "inventory" means. Sprite is visual; game objects are yours.

## Key decisions

- **Pixel positions, not tiles.** Framework is world-model agnostic. Works for hex
  grids, rect grids, and free-scrolling RPG backgrounds equally.
- **GPU-first.** Pyglet (OpenGL) as first backend, not pygame. Removes the performance
  ceiling. Hundreds of sprites and particles without worry.
- **Backend-agnostic protocol.** Opaque handles, begin/end frame batching. Pyglet can
  be swapped without touching game code or framework logic.
- **Logical coordinates, native rendering.** Game positions things in 1920x1080 (or
  whatever). Rendering happens at physical resolution — text is always sharp, even on
  retina. Asset manager loads @2x variants automatically.
- **Particles are just sprites.** No special system. An emitter manages short-lived
  sprites with velocity and lifetime. Spell effects, weather, explosions — all covered.

