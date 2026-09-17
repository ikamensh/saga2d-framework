# Changelog

## Unreleased

- Immediate shape drawing reuses bounded vertex buffers across frames and
  temporary layer changes. This avoids repeatedly constructing and discarding
  pyglet domains while preserving shape order, transparency and disappearance.
  Recovered independently from the shape portion of `238584d`.
- Sprite transforms skip unchanged translation and scale uploads, including
  retained moving sprites and pooled HUD images. Image-size swaps still
  recompute the scale and preserve rotation.

## 0.3.2 — 2026-09-16

- `Banner` keeps its title and subtitle inside the window for every frame of the
  slide. The wipe used to start 60 % of the window width to the left of centre,
  which put both strings wholly outside the window over the opening frames —
  Warband's match intro reported `text does not fit … left by 286px` on a new
  game. The banner now slides only as far as the room the longer string has
  beside it, and a string wider than the window is ellipsized to fit.

## 0.3.1 — 2026-09-16

- Packaging ships every snapshotted package's `assets` folder (`saga2d`,
  `sagaforge`, the game) in the frozen application. Before this the recipe
  bundled only the engine's fonts, so a game's committed art and sound pieces
  were missing from its Windows and Mac builds: painted sprites fell back to
  procedural renders, and a module that counts its pieces at import failed
  the native package check.

## 0.3.0 — 2026-09-16

Shared measured text and opt-in interaction for standard and custom game UI.

- `Scene.layout_text` returns immutable `TextLayout` lines and height without
  drawing. `Scene.fit_text` fits a single line with a measured ellipsis.
  `draw_paragraph` and wrapped `Label` accept `max_lines`; all share the same
  wrapping, long-word splitting and truncation. See [text layout](docs/framework-text-layout.md).
- `scene.ui.enable_focus` opts into Tab, vertical or spatial keyboard navigation.
  Custom controls expose `focusable`, `focused`, `hovered` and `on_activate`;
  games can supply candidate sets while retaining their eligibility rules.
  Existing explicit button shortcuts take precedence. See [focus and pointer
  handling](docs/framework-ui-focus.md).
- `Component(blocks_pointer=True)` owns its click area, including while disabled,
  so HUD clicks cannot reach the world beneath it. Buttons and minimaps opt in.
  Pointer capture keeps a drag with its control outside its bounds and cancels
  on hiding, disabling, removal, a covering scene or window deactivation.
- `Game.mouse_position` exposes the last pointer position in logical coordinates.
- Named text styles without an explicit font inherit the theme font consistently
  for measurement, immediate text and retained labels.
- `Sprite(ground=...)` offsets y-sorting to the line a sprite stands on when its
  image has padding below its feet. Simultaneous toast notifications stack.

Text overflow diagnostics:

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

No removed public interfaces. Focus is opt-in, leaving existing gameplay keys
unchanged. Disabled buttons and minimaps now consume clicks in their area;
motion and wheel events still pass through unless a control handles them.

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
