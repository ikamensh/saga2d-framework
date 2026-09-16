# Changelog

## 0.3.0 — unreleased

Text that does not fit the rectangle it was drawn into.

- `Scene.text_region(x, y, width, height, name=...)` declares the box that text
  drawn inside the scope must fit in. Immediate drawing has no layout to check
  itself against, so a card's label one character too long runs off its own edge
  and nothing notices: `assert_no_text_overlap` cannot see it, because text over
  nothing is not text over text.
- A string that leaves its region is logged as a warning the first time it is
  drawn — once per string per process, not once per frame — so it is visible
  while the game runs, and `saga2d.testing.assert_text_fits(game)` makes it a
  test failure. Where no region is declared, screen-space text is measured
  against the window; world text is exempt.
- `game.check_text_fit` and `SAGA2D_CHECK_TEXT=0` turn the check off. It costs
  one cached text measurement per drawn string. UI components lay themselves out
  and are not covered.
- The anchor fractions that turn a draw call into a rectangle moved to
  `saga2d/rendering/_text.py` and are shared by the drawing and checking sides,
  so the drawn box and the measured box cannot drift apart.
- `Scene.draw_polygon`'s docstring now says it is convex only: the backend
  fan-triangulates, so a concave outline fills as its hull.

No breaking changes; a game on 0.2.0 upgrades by changing its pin.

## 0.2.0 — 2026-09-16

First standalone PyPI release of the engine after the Saga repository split.
This is the baseline for games switching from an editable engine checkout to
an explicitly pinned release.

- Scene lifecycle, input, cameras, sprites, animation, audio, saves and settings.
- GPU rendering through pyglet, a UI toolkit and bundled Nunito fonts.
- LAN and online sessions, shared match screens and the authoritative room server.
- Standalone game packaging and headless integration-test support.
- Source and wheel distributions with one version source and installed-package
  verification in CI.

Game rules and procedural asset generation are separate packages.
