# Saga2D backlog

Created 2026-09-16. This is the actionable queue for shared engine work; the
[September review](docs/engine-review-2026-09.md) supplies broader rationale.
Game rules and art stay in the games. The [Warband backlog](../warband/BACKLOG.md)
is the immediate consumer. Follow [DESIGN.md](DESIGN.md): add a primitive for a
concrete game need, with two independent consumers the strongest justification.

Keep IDs stable and record `in progress` plus branch when starting, then `done`
plus commit and evidence when finished. `Proposed` needs its bounded consumer
case established; `deferred` needs a new product need before implementation.
Text layout/fitting and focus/pointer ownership from the earlier review already
exist on current main; extend/adopt them rather than rebuilding them.

| ID | Priority | Status | Task |
|---|---|---|---|
| S2D-001 | First | ready | Review outstanding engine branches and preserve useful work |
| S2D-002 | First | ready | Establish native renderer baselines and locate bottlenecks |
| S2D-003 | Next | in progress | Reduce proven text/shape allocation and batching churn |
| S2D-004 | Next | proposed | Measure large-texture batching, visibility and upload costs |
| S2D-005 | Next | proposed | Add public nested clipping |
| S2D-006 | Next | proposed | Build a scrolling content viewport on clipping |
| S2D-007 | Next | proposed | Native text input and a focused text field |
| S2D-008 | Next | proposed | Explicit asset replacement and bounded resource lifetime |
| S2D-009 | Next | proposed | Extend installed-wheel native regression coverage |
| S2D-010 | Later | proposed | Make simulation/publication timing explicit and measurable |
| S2D-011 | Later | proposed | Generalize room seats for Warband online FFA |
| S2D-012 | Later | proposed | Add focused rendering effects only when a game proves the need |
| S2D-013 | Later | proposed | Positional/panned audio and owned looping effects |
| S2D-014 | Later | deferred | Action input and spatial queries through a small proof game |
| S2D-015 | Next | proposed | Fit the window and HUD to high-DPI desktops (Windows 4K) |
| S2D-016 | Next | ready | Bound the batch's groups and vertex domains: a long battle grows them without end |
| S2D-017 | Next | ready | Cut the per-frame cost of the y-sorted batch and the shape soups in a crowded scene |

## S2D-001 — Existing branch review

Local read-only snapshot on 2026-09-16, engine main `1786283`:

| Ref / worktree | Unique commits ahead | Candidate |
|---|---:|---|
| `codex/fix-openal-lifetime`, `/private/tmp/saga2d-openal-fix` | 1 | `6e942d8`: interrupted OpenAL buffer release |
| `codex/reuse-text-labels`, `/private/tmp/saga2d-text-labels` | 3 | `6ff2670`: bounded text slots; `238584d`: bounded shape buffers; `e3140c8`: audio release |
| Detached `238584d`, `/private/tmp/saga2d-audio-control` | 2 | The same text/shape candidates without the audio change |

All three worktrees were clean at inspection. The commits overlap; do not merge
both lines as independent fixes. Refresh status/ancestry and inspect the patch
and existing evidence before deciding integrate/retain/discard. Verify the audio
correctness candidate independently of renderer speed or RSS claims. Preserve
active work and detached commits before retiring redundant branches/worktrees.

**Done when:** dispositions and integration evidence are recorded, worthwhile
fixes pass current native/consumer checks, and confirmed inactive redundant
worktrees are removed. Coordinate with WB-001. This backlog does not itself
establish that the candidates are correct or faster.

## S2D-002 — Renderer baseline before optimization

Measure current pyglet rendering using existing
[frame pacing tools](tools/verify_frame_pacing.py), FrameTimer and
[Warband's battle tool](../warband/tools/perf.py). Include static UI, changing
text, moving/y-sorted sprites, repeated scene turnover, large backgrounds,
mostly offscreen maps and many transient effects. Compare with another concrete
game scene before claiming a framework-wide improvement.

Record revisions, host/OS/GPU, resolution/pixel scale, warmup, asset sizes,
counts and p50/p95/max. Separate simulation, view sync, draw submission and
flip/pacing; distinguish CPU submission from GPU/present waits. Measure batch/
texture switches, live resources and allocation churn where useful. Run native
allocation/RSS investigations separately from frame-time measurements.

**Done when:** repeatable scenes expose the leading costs and bounded next
fixes, including whether large textures are material. Preserve Warband's
existing p95 < 16 ms reference gate and record justified budgets for other
scenes. No universal entity limit, native rewrite or FPS gain is assumed.

## S2D-003 — Proven text/shape and batch hot spots

Started during WB-004 acceptance on `codex/wb004-render-shapes`.
[Acceptance and current evidence](docs/warband-renderer-performance.md) cover
recovered shape/text reuse, unchanged uploads, camera culling, redundant GL
state and a native opacity bug found during that review. Warband now passes
its full-run gate at p95 15.58 ms (baseline 17.8 ms), with identical crowd
pixels and simulation state. The verified fixes are published in 0.3.3 (`9a1a58c`, `v0.3.3`);
the broader scene matrix and long-run resource audit remain open, so this
engine item is not marked wholly done by the focused WB-004 dependency.

Depends on S2D-001/002. Review text-slot and shape-buffer candidates first.
Optimize only measured hot paths: changing labels, short-lived layer/order
groups, redundant state changes, or immediate geometry rebuilds. Preserve
draw order, y-sorting, camera transforms, transparency and scene ownership.

**Done when:** the same before/after workload shows a measured benefit without
unbounded pool growth, and inspected native frames preserve pixels/layering.
Scene turnover, text changes and long runs retain bounded resources. Allocation
churn, RSS growth and leaks are separate findings; report only what was measured.

## S2D-004 — Large textures, culling and uploads

[The backend](saga2d/backends/pyglet_backend.py) puts images up to 1024 pixels
per dimension in a 2048-square TextureBin; larger images use standalone
textures. Separate textures can fragment batching, but the size threshold alone
does not prove a bottleneck or one draw call per sprite. Measure texture/order
combinations, offscreen work, load/upload spikes and GPU memory first.

Try the smallest demonstrated fix: appropriate atlas packing/regions, reusable
uploads, culling, or game-owned terrain chunks. Warband already chunks ground
and warms some assets incrementally; identify the actual missing engine seam
before adding a second system. World streaming/LOD is a separate product scope.

**Done when:** a representative large-art/map scene improves with bounded
memory and no filtering seams, edge bleed, clipping or sort errors. Verify
HiDPI and different zooms with native frames. Depends on S2D-002.

## S2D-005 — Public nested clipping

The backend currently scissors the letterboxed canvas; there is no public
content clip. Add a small scoped clip interface whose nested rectangles
intersect and whose state restores after exit. Specify logical/physical pixels,
world/screen transforms and interaction with ordered retained drawing; clipping
must be associated with the draws that consume it, not accidentally lost when
batched work is submitted later.

Use a real overflowing game panel as the first consumer and the scrolling
viewport as the second exercise. Keep mock and native behavior aligned.

**Done when:** nested partially visible text, sprites and shapes stay inside
their clip under scaling/resize; clipped controls cannot receive pointer
activation; sibling/modal draw state is unaffected. Native input and screenshots
agree with the mock. This is a useful capability, not a claim that current
unclipped components violate an existing clipping contract.

## S2D-006 — Scrolling content viewport

Depends on S2D-005 and uses the existing focus/pointer APIs. Implement a bounded
content viewport with content measurement, scroll limits, wheel/trackpad input,
focus reveal and matching clipped hit-testing. Choose actual long codex,
settings, replay-list or log screens as consumers; keep their content and
styling local. Preserve deliberate pagination where it suits a game.

**Done when:** a long list and nested viewport work with pointer and keyboard,
focus stays visible, resizing/reflow preserves sensible position, and hidden
children cannot activate. Add virtualization only if measured list sizes need
it; do not bundle dropdowns, inventory drag/drop and tables into this task.

## S2D-007 — Native text entry

[The event union](saga2d/backends/base.py) has keys, mouse and window events;
[MatchMenu](saga2d/multiplayer_ui.py) translates key names into restricted text.
Add native text/composition events separate from gameplay bindings, then a
focused field with cursor, selection and clipboard behavior. Room codes can
retain their validation rules; nickname/free-text entry must not inherit ASCII
key-name restrictions. Reuse current focus ownership.

**Done when:** the actual room form and a free-text field handle Unicode,
selection, paste and composition on supported native platforms; typing cannot
fire game shortcuts. Keep composition and shortcut tests distinct, including
focus loss and field removal. Document native platform limitations explicitly.

## S2D-008 — Asset replacement and resource lifetime

Start with the existing preview/image replacement use case described in the
[engine review](docs/engine-review-2026-09.md), then measure repeated scene/map
transitions. Define replacement behavior for live sprite handles and different
image sizes. Design bundle/release semantics only when needed; removing a cache
entry does not by itself reclaim atlas or GPU memory. Keep procedural generation
in Sagaforge and games.

**Done when:** migrated callers no longer touch private image caches, repeated
transitions keep relevant live resources bounded after warmup, and texture
replacement is visibly correct. Stage preparation/uploads only when measured
startup stalls justify them. Keep the audio correctness fix in S2D-001 independent.

## S2D-009 — Native regression coverage for released wheels

Build on existing distribution, display, text, input and audio verification.
Add a small installed-wheel desktop matrix and representative consumer journeys
that catch problems hidden by the mock. Establish what virtual CI proves and
what still needs real hardware; keep timed benchmarks on controlled hosts.

**Done when:** supported-platform smoke jobs exercise render/input/audio and
packaging from the wheel, preserve diagnostic frames/logs on failure, and have
explicit hardware follow-ups. Candidate checks use isolated game environments;
normal engine development does not silently repin consumers.

## S2D-010 — Explicit timing and networking costs

Current hosted matches step every 50 ms and publish on alternating steps;
missed time is discarded after overload. Expose rates/overload policy through
the concrete game contract and measure per-room step time, encoding cost,
snapshot bytes and end-to-end latency before choosing deltas or isolation.
Keep game-specific interpolation in the game until a second consumer proves
a useful shared interface.

**Done when:** real server/client tests cover cadence, overload, slow readers,
reconnection and version compatibility; one expensive room's effect on others
is measured. Record the first bounded performance fix separately. A shared
fixed-step clock, match-session ownership and bounded event journal remain
distinct extractions from the existing review, not one networking rewrite.

## S2D-011 — N-player room contract

Warband's proposed online FFA (WB-012) is the concrete consumer. Current
[Room](saga2d/server/__init__.py) has two peers/seats; parameterize capacity
through game registration, then update joining, ready/start, private seat
tokens, reconnect, persistence and the shared lobby. Retain correct two-seat
behavior for existing games. Decide protocol migration explicitly.

**Done when:** real three-/four-client journeys cover full rooms, disconnected
seats, rejoin, restart recovery and departure, with all existing two-player
consumer journeys passing. Spectators and rollback are separate requirements.

## S2D-012 — Small rendering-effect additions

There is no public blend-mode, shader/material or offscreen-target interface.
For a proven game effect, evaluate an additive blend option first; keep alpha
blending as the existing default. If an effect requires composition, add one
owned render-target use case with clear resize/lifetime semantics before
considering custom shaders, masks, lighting or a post-processing pipeline.

**Done when:** a concrete effect cannot reasonably use existing sprites, its
smallest new primitive works with ordering/clipping and context/scene lifetime,
and native pixels plus performance prove the result. Warband blood, walking
and melee polish do not inherently require a shader system. No commitment to
normal maps, dynamic shadows or a generalized material graph is made here.

## S2D-013 — Audio controls for actual battles/ambience

The public SFX API has volume/pitch, while music already loops, streams and
crossfades. There is no public pan, positioned effect, looping SFX handle or
playback-clock query. Prototype camera-relative pan/attenuation for Warband
combat and an explicitly stoppable loop for an actual ambience use case.
Keep handles owned and cleaned up on scene exit; preserve silent-driver tests.

**Done when:** off-centre sounds and loop start/update/stop behave through native
playback, pause, scene transitions and interruption without growing player/
buffer counts. Do not describe all audio as mono without inspecting sources
and playback. Audio-clock/latency APIs wait for a concrete synchronized-audio
game; rhythm-game support is a separate project.

## S2D-014 — Action input and collision: deferred proof

A bounded top-down movement/aim/dash prototype could justify named actions,
axes, controller connect/disconnect and remapping, then spatial hashing,
ray/sweep queries and fixed stepping. Begin only when pursuing that concrete
game direction. Keep response rules in the prototype and extract the smallest
repeated primitives. Warband's crowd steering is not a reason to build a
rigid-body physics engine.

**Done when activated:** the proof works through native and mock input, handles
controller removal and fast movement without tunnelling, and has measured
population limits. A physics solver, platformer controller, touch UI or couch
split-screen each needs its own demonstrated requirement.

## Triage of the supplied “hard walls” critique

Source-checked against engine `1786283` on 2026-09-16; this was an inspection,
not a fresh performance benchmark or native reproduction.

| Claim | Finding and disposition |
|---|---|
| No shader/blend/target seam | Public limitation confirmed; fixed alpha blending. Capture reads a window buffer, not a public offscreen target. S2D-012, after a consumer exists. |
| No physics | Collision utilities supply rectangles/overlap, not a solver or swept collision. S2D-014; no general physics project now. |
| Mouse/keyboard only, no text input | Event contract lacks controller and text/composition events. Text input is S2D-007; action/controller input is deferred in S2D-014. |
| Two-seat snapshot netcode | Confirmed for hosted rooms. Warband sends full-world snapshots; local 2–4 player AI skirmish is already possible. S2D-010/011 and WB-010/011/012 address separate problems. Existing multiplayer is not categorically impossible. |
| Seven widgets, no clipping | Exact widget count is misleading: Minimap, measured layout, focus, pointer blocking/capture and tooltips also exist. Public clipping/scrolling remain missing: S2D-005/006. |
| Fire-and-forget mono audio | Public SFX controls are limited, but managed players, streaming music, looping music and crossfades exist. The blanket mono claim is not established. S2D-013. |
| Desktop-only distribution | Current packaging targets desktop. Browser/mobile/console require a separate platform/product decision, not an incremental Warband fix. |
| Large art never batches; everything eager | The large-image atlas bypass is real; draw cost needs measurement. Music streams, and Warband already stages some asset preparation. S2D-002/004/008. |
| Python cannot support entire genres or thousands of entities | Unsupported as a universal capacity claim. Entity work, draw workload and hardware determine limits; measure an actual proof scene. Missing tools raise development cost, not proof of impossibility. |

Do not turn genre examples into promised engine features. Clipping/scrolling
and measured rendering improvements are the strongest near-term additions;
full physics, per-pixel simulation, rollback/prediction, browser/mobile export,
open-world streaming and a general editor stay outside this queue until a
concrete project makes them worthwhile.

## Completion contract

For engine behavior changes: integration-test the public interface, inspect
real native frames for rendering/UI changes, and test each affected game with
the candidate engine explicitly installed. Restore released game environments
afterward and follow [the engine release guide](docs/releases.md) for adoption.
Run at most one expensive job at once. Record evidence from the final revision;
an old report or a mock-only pass does not establish current native performance.

## S2D-015 — Window fit and HUD scale on high-DPI desktops

Reported 2026-09-17 from a Windows 10 desktop at 3840×2160 (Warband WB-021):
`Game(resolution=None)` opened a window covering about half of the desktop,
letterboxed inside its own frame, with the HUD at native pixels and so tiny;
the first match then crashed on the scale change between the title and the
match (fixed in Warband, covered by `tests/warband/test_startup.py`).
Establish on a Windows session with display scaling: the units
`screen_size()` and the window sizes report under `pyglet.options.dpi_scaling`,
what `_fit_screen` should ask for, and how the logical canvas and
`scale_factor` should be chosen so the HUD stays readable on a 4K desktop
(the games lay out for 1280 wide and up; `scale_factor` ≥ 2 keeps text sharp).
Consumers: Warband today; every game using `resolution=None` tomorrow.

**Done when:** on a 4K Windows desktop the window uses the desktop, letterboxes
only for an aspect mismatch and shows a readable HUD; the mock backend's screen
size can be set so a startup matrix covers such desktops headlessly; the
native package check captures a frame on a resized window (Warband already
does). Proposed; no implementation is started.

## S2D-016 — Bound the batch's groups and vertex domains

Found 2026-09-18 by Warband's WB-009 (`tools/perf.py`, the 150-unit reference
battle on the M4 reference Mac, Saga2D 0.3.3, 1280×800): over 720 frames the
pyglet batch grew from 129 to 347 top groups, 359 to 969 groups and 165 to 489
vertex domains, and its draw list from 703 to 1474 entries. Every new domain
builds a `VertexList` class (properties, functions, descriptors: the tracked
objects grew from 159,691 to 218,012 in twelve seconds, `function +6859`,
`property +2946`), so the collector's full passes walk more each time: gen2
pauses went from 17 ms to 41 ms across the run, one every two seconds, which
is the battle's p99 (26–45 ms frames; the p95 is the world step's path
planning). The draw list is rebuilt whenever a group changes, so
`Batch._update_draw_list` (70,804 `visit`s in 120 profiled frames, about
2.5 ms a frame under the profiler) grows with it too. Warband freezes its
match out of the collector once warmed up, which cuts a pause to about
10 ms; the growth itself is the engine's.

Likely cause: y-sorted sprite groups are keyed by `(space, order)` where
`order` carries the y band (`layers.py`, `Y_SORT_STEP` 8 px), so every band a
sprite ever crosses gets a group and, per texture and program, a domain that
is never released. **Done when:** a battle that wanders over the whole map
keeps a bounded set of groups and domains (bands reused, empty ones released
or pooled), the tracked-object count of the reference battle stays flat over
a minute, and the draw list length stays within a small multiple of the
visible bands; measured with Warband's `tools/perf.py` (`batch:` and
`tracked objects:` lines) before and after, and the reference gate re-run.

## S2D-017 — Per-frame cost of the y-sorted batch and the shape soups

Measured 2026-09-18 with Warband's WB-009 (`tools/perf.py`, the 150-unit
reference battle, M4 reference Mac, Saga2D 0.3.3, 1280×800, unpaced): a
median frame is 9.3 ms, of which `end_frame` is 4.5 ms (`batch.draw` 2.6,
`window.flip` 1.2, the soups and labels the rest), `view.sync` 1.55, the
scene's draw 1.1 and the UI's 0.9; frames with a world step are 12.6 ms at
p50 and 19.3 at p95, so the late p95 is 16.7–18.1 ms across the reference,
four-player, pan-zoom and deaths scenarios against the 16 ms gate. In the
renderer: pyglet's `Batch._update_draw_list` runs whenever the y-sort moved a
sprite between groups, which in a battle is every frame (70,804 `visit`s in
120 profiled frames, about 2.5 ms a frame under the profiler; S2D-016 makes
the walk longer as groups accumulate); the immediate-mode shapes go through
`_push_triangles` in Python (113,849 calls in 120 frames: 950 triangles a
frame, most of them the 127 `draw_box` health bars over the wounded), about
1 ms a frame. **Done when:** a y-sort change no longer rebuilds the whole draw
list every frame (or the rebuild is bounded to the touched groups), boxes and
bars are pushed without a Python call per triangle, and the reference battle's
median frame drops by the measured amount with the frame-pacing and Warband
gates re-run before a release; the game side keeps its own draw calls.


## S2D-018 — Built games carry an icon

Asked for 2026-09-18: the Windows executable, its installer and the Mac app
bundle of every game show PyInstaller's default picture (the Python-coloured
snake), because the recipe (`packaging/game.spec`, `game.iss`) names no icon.
A build should carry the engine's own mark unless the game supplies its
picture; Warband supplies one (WB-026). Consumers: every packaged game.

**Done 2026-09-18**, commits `7f13be7`, `7a7924f`, `aea32d7`; released as
**Saga2D 0.3.5** (tag `v0.3.5`, wheel SHA-256
`6374965477152dc76a496ca38cd0b83c74d75111f2797fe2ac23461712557de2`, sdist
`ec39f66e178beff6ae1b68e57314f855d9b39bbaf6011b3f853d7e0ae1d0eed2`;
[Tests 35333175476](https://github.com/ikamensh/saga2d-framework/actions/runs/35333175476);
the installed-distribution check passed from the built wheel and again from
PyPI in a fresh environment). Every criterion below holds: 413 tests pass
(nine new in `tests/framework/test_packaging.py`); the default mark and
Warband's picture looked at in both platform shapes at every stored size on
light and dark ground; a Warband bundle built from the candidate on the
reference Mac passed `verify` with the icon check and shows the picture in
Finder; Warband's native checks on the released engine are green on Windows
and macOS ([35337133223](https://github.com/ikamensh/warband/actions/runs/35337133223)),
and the CI-built executable and Inno Setup installer hold all seven images of
the converted `.ico` byte for byte. Found on the way: `*.png` is git-ignored
here, which also keeps a file out of the sdist and so out of the wheel; the
default picture has its own exception in `.gitignore` and the distribution
check now requires it. Tribes, Shardbound and Ninefold get the engine's mark
when their mains move to 0.3.5 (the shared server already runs it:
[saga-online](../saga-online/docs/engine-035-rollout.md)).

**Acceptance (recorded 2026-09-18 before implementation):**

1. `GamePackage.icon` is an optional path to the game's picture: a square
   PNG, 1024 px or larger, painted to the edges. A game that names none gets
   the engine's mark, `saga2d/packaging/icon.png`, committed together with
   the script that draws it (`tools/make_icon.py`) and shipped in the wheel.
2. A picture that is not square or is smaller than 1024 px stops the build
   with an error that names the file and its size; no silent rescue.
3. Windows: the executable carries the picture as its first icon group in
   the sizes 16, 24, 32, 48, 64, 128 and 256 (Explorer, the taskbar and the
   pyglet window read that group), and the installer shows it as well;
   shortcuts take it from the executable.
4. macOS: the bundle holds an `.icns` that `CFBundleIconFile` names, shaped to
   the platform's rounded square with its margin, so the same edge-to-edge
   picture suits both systems.
5. The build manifest records the picture's and the converted file's SHA256;
   `verify` fails a build whose executable (Windows) or bundle (macOS) does
   not carry exactly the converted icon.
6. Tests without PyInstaller: the conversion's sizes, the Mac shape's
   transparent corners, both refusals, the manifest record, the verify check
   on a fixture; the wheel check (`tools/check_distribution.py`) finds the
   default picture in the installed distribution.
7. Looked at: the default mark at 16, 32, 64, 256 and 1024 px on light and
   dark ground; a bundle built from the candidate engine on the reference Mac
   with its Finder thumbnail; Warband's native checks on Windows and macOS
   green on the released engine.
