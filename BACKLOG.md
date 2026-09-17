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
