# Changelog

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
