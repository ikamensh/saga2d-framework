# Changelog

## 0.3.9 — 2026-09-20

- A game wears its icon while it runs, not only once it is built: `Game(icon=…)`
  names the square picture, `saga2d.desktop` shapes it for the platform exactly
  as the built app carries it, and the window hands it to the Dock, the taskbar
  and the title bar. A game that names no picture wears the engine's mark. The
  picture belongs in the game package's `assets`, which a built game carries.
- macOS also learns what to call the game. Only Launch Services names a process
  there, and one without an application bundle keeps the interpreter's name, so
  a game started from a checkout sat in the Dock as a blank page called
  "python3.13" however its window was captioned.
- The engine's mark moved to `saga2d/assets/icon.png` from the packaging recipe,
  which the wheel ships but a built game does not carry;
  `saga2d.packaging.icon.DEFAULT` still names it and builds are unchanged.

## 0.3.8 — 2026-09-18

- Rooms of more than two seats (S2D-011, for Warband's free-for-all): a
  `GameSpec` says how many seats a room of a match has (`seats(match)`) and
  whether a seat must be connected for play to go on (`needed(match, player)`),
  two seats, every one needed, unless it says otherwise. `join` takes the next
  free seat; a room is ready when every needed seat is connected and somebody
  is in it, so a player who is out of the match may leave without pausing the
  rest. The welcome and every state carry the room's `seats` and how many are
  `present`; the lobby says "Waiting for players · k of N" for larger rooms.
- Compatible migration, no protocol bump: a client's hello says how many seats
  it handles (`seats`, two when absent). A room larger than that is refused as
  incompatible, with an update message, before a seat is taken; clients from
  before this release keep playing in rooms of two and ignore the new fields.
  `OnlineClient` handles four (`saga2d.online.SEATS`) and keeps `seats` and
  `present`.
- `saga2d.testing.online` registers `counter-seats-v1`, a counter of two to
  four seats whose players can drop out.
- The centring of a new window under Windows (0.3.6) keeps a window larger
  than its screen from starting with its title bar above the screen's top:
  a fixed 1280×800 game on a 1366×768 laptop opened at y −16.

## 0.3.7 — 2026-09-18

- Online clients take compressed frames (`OnlineClient` asks for
  permessage-deflate, which the room server has always offered): a real-time
  game's state, 70 to 140 KB of JSON ten times a second in Warband, is about
  an eighth of that on the wire. Older clients keep working uncompressed.
- A realtime room publishes on its clock: an accepted order marks the room and
  its next tick (at most 50 ms later) publishes, instead of building and
  encoding the whole state for both seats on every order. Turn-based rooms
  still answer every order at once.
- LAN matches: a poll sends and reads all the socket takes and holds (it moved
  one chunk each way, 64 KB in, which tied the link's speed to the frame
  rate), a state still waiting whole in the host's queue is replaced by the
  newer one, and what a peer said before hanging up is read before the
  hang-up is raised. A guest rendering slowly now sees the newest state a
  little late, where it used to fall behind without bound until the host
  dropped it.
- A `Toast`'s words are checked against its own box, not the window: the box
  slides in from beyond the edge, so every toast was reported as text that
  does not fit on its first frames.

## 0.3.6 — 2026-09-18

- Window sizes are in desktop units on every platform. On Windows and X11
  pyglet reports physical pixels with the display's scale beside them; the
  backend ignored the scale, so on a 3840×2160 desktop at 200 % a 1280×800
  game opened at a quarter of its intended area and `Game(resolution=None)`
  made a 3760×2040 canvas with the HUD at native pixels (Warband's report,
  measured on a real desktop at 100 %, 150 % and 200 %). `screen_size`,
  `window_size`, `windowed_size`, `set_window_size` and the size a window opens
  at now divide or multiply by that scale at the pyglet boundary (macOS already
  worked in points and is unchanged), and `scale_factor` carries the desktop's
  scale: 2.0 on that desktop, for a 1840×960 canvas.
- `Game(resolution=None)` keeps the fitted canvas at most `MAX_FITTED_HEIGHT`
  (1440) units high by raising the scale in quarter steps: 3840×2160 at 100 %
  gives 2506×1360 at 1.5 instead of a wall-sized canvas; 2560×1440 and smaller
  desktops are as before. Its margin and canvas are in desktop units, so the
  window clears the title bar and the taskbar at every scale.
- Under Windows a new window is centred on its screen instead of taking the
  next cascade position, which hung a fitted window under the taskbar.
- `MockBackend(screen=..., desktop_scale=...)` names the desktop a test runs
  on, and the mock's `scale_factor` follows it as the real backend's does.
  `Backend.create_window` takes an optional `window_size` for a window that is
  not canvas-sized; a custom backend must accept it.

## 0.3.5 — 2026-09-18

- Built games carry an icon instead of PyInstaller's default picture.
  `GamePackage.icon` names the game's square PNG (1024 px or more, painted to
  the edges); a game that names none gets the engine's mark
  (`saga2d/packaging/icon.png`). The build shapes the picture for the platform
  (the Mac grid's rounded square with its margin and shadow, a rounded full
  canvas on Windows), writes the `.ico` that the executable and the Inno Setup
  installer embed or the `.icns` the bundle names in `CFBundleIconFile`,
  records both files in the build manifest and copies the converted icon
  beside it. `verify` fails an executable or a bundle that does not carry
  exactly that file. A picture that is not square or is too small stops the
  build. Upgrade note: `game.iss` now requires the `SetupIcon` define, which
  `saga2d.packaging.build` supplies.

## 0.3.4 — 2026-09-17

- The mock backend derives `scale_factor` from the window the way the pyglet
  backend does, so `inject_resize`, `set_window_size` and `set_fullscreen` in a
  test rasterise textures at the scale a player's desktop would. Warband's
  startup matrix reproduces its Windows crash at match start with it: a
  Medium map's ground images registered at one scale and redrawn at another.

## 0.3.3 — 2026-09-17

- Text labels reuse bounded slots by font, size, anchors and layer while their
  content, colour and position change. Hidden slots draw nothing and can return
  without repeated label/domain allocation.

- Shape blending is set only by shape groups; parent view groups no longer
  duplicate the blend-state calls already made by pyglet sprites and text.
- World sprite groups wholly outside the camera are omitted from the draw
  batch, including rotated sprite extents and a filtering margin. Camera
  movement and immediate images/shapes restore affected groups before drawing;
  ownership, order and screen-space UI are unchanged.
- Immediate shape drawing reuses bounded vertex buffers across frames and
  temporary layer changes, skipping unchanged position/colour uploads. This avoids repeatedly constructing and discarding
  pyglet domains while preserving shape order, transparency and disappearance.
  Recovered independently from the shape portion of `238584d`.
- Sprite transforms skip unchanged translation and scale uploads, including
  retained moving sprites and pooled HUD images. Image-size swaps still
  recompute the scale and preserve rotation.
- Retained sprites preserve opacity when their tint or position changes.
  Sending RGB to pyglet reset alpha to 255 after each opacity update; the
  backend now sends one RGBA value, so fades actually reach transparency.

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
