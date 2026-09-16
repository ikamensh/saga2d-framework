# Saga2D: extraction opportunities and engine direction

Review date: 2026-09-16. Engine source reviewed at `3cfac2e`; released consumer
baseline is 0.2.0. This is a proposed roadmap, not an implementation or release
commitment. It includes Tribes, Warband, Shardbound, Ninefold and Absolution.
Warband worktree variants are not counted as independent consumers.

## Recommendation

Make Saga2D a dependable Python desktop 2D runtime with particularly good UI,
resource ownership, simulation timing and testing. Keep its small-interface
design. Its best next improvements are deeper existing modules, followed by a
small action-game proof that challenges the current strategy-game assumptions.

Separate releases make focused changes and deliberate migrations practical.
They do not make speculative abstractions cheaper to maintain. An extraction
should delete meaningful caller complexity, or unlock a concrete new game with
a small interface. Existing games need not be the only source of those proofs.

The engine already has scene ownership, retained sprites, batched immediate
drawing, camera insets, measured paragraphs and labels, button shortcuts,
tooltips, settings, durable saves, streaming music/crossfades, match menus,
reconnection, server persistence, packaging and installed-wheel verification.
Those should be extended or adopted, not rebuilt.

## What to factor out of games

| Priority | Candidate | Evidence | Engine responsibility; game responsibility |
|---|---|---|---|
| First | Measured text fitting | Ninefold and Absolution implement their own wrapping and ellipsis | One measured layout result used by drawing and UI; games choose widths, line budgets and content |
| First | Focus, pointer ownership and content viewports | Absolution custom buttons; Tribes tech-tree/settings focus; Warband settings and HUD hit tests | Focus/activation, pointer blocking/capture, clipped hit-testing and scrolling; games choose appearance and navigation relationships |
| Next | Match-session ownership | Three network scenes repeat polling, revisions, errors and close behavior | Match lifetime spans scenes and overlays; games decode snapshots and choose screens |
| Next | Bounded presentation-event journal | Warband event IDs/tail; Shardbound journal/inbox | Sequence/epoch, retention bounds, deduplication and explicit gaps; games define payloads, visibility and reactions |
| Next | Fixed-step clock | Warband offline, LAN and hosted paths each carry timing assumptions | Accumulator, bounded catch-up, remainder and explicit overload policy; games own simulation and pause/speed rules |
| Selectively | Square-grid geometry/search | Warband pathfinding; Tribes isometric picking; engine HexGrid precedent | Geometry and explicitly specified searches; games retain movement costs, crowding and tactical rules |
| Small follow-up | Ranked local records | Tribes and Warband duplicate identity, ranking and persistence | Record/deduplicate/order a bounded collection; games define scores, boards, schemas and tie-breaks |

### Text layout: the clearest first extraction

This is the smallest independent first increment, not the highest-leverage
change in the whole roadmap. Focus and pointer ownership affect more consumers;
their larger implementation should not block shipping a useful text improvement.

[Ninefold view](../../ninefold/ninefold/view.py) lines 541–581 and
[Absolution scenes](../../absolution/absolution/scenes.py) lines 122–151 implement
wrapping and truncation while calling backend text measurement. The engine
already has a private measured paragraph module in
[rendering/_text.py](../saga2d/rendering/_text.py), lines 8–58.

Expose one scene-aware layout operation returning measured lines and bounds,
with optional line limit and ellipsis. Let immediate drawing and retained
labels consume the same result. A bounded single line is the same problem.
Respect explicit newlines, font choice and logical/physical scaling; report
whether content was truncated. Do not shrink text silently or truncate critical
game information by default. Keep `text_region` as diagnosis, not as a
substitute for layout.

Acceptance: migrate both game helpers; test their real cards, long words,
newlines, long translated strings and font/scale changes; inspect native frames.

### UI behavior: make custom-looking controls practical

[Absolution scenes](../../absolution/absolution/scenes.py) lines 30–40, 109–119
and 341–383 implement button hit testing, focus and activation.
[Tribes scene](../../tribes/tribes/scene.py) lines 1004–1039 implement directional
tech-tree focus; its settings at 1070 onward and
[Warband scene](../../warband/warband/scene.py) at 1810 onward repeat indexed
keyboard navigation. Tribes line 224 and Warband line 1074 also duplicate
`_over_ui()` so world interactions do not pass through HUDs.

Extend the existing Component/UI-root interface with focus and activation,
explicit pointer blocking, capture and optional directional neighbors. Custom
cards and nodes must be able to use those behaviors while drawing their own
appearance. Avoid a second parallel immediate-widget framework.

Add a bounded content viewport whose drawing, picking, wheel handling and focus
agree on the same clip rectangle. Current children are not clipped by their
parent ([ui/base.py](../saga2d/ui/base.py), lines 172–185, 310–341). This unlocks
inventories, logs, dialogue, settings and catalogs. Preserve Shardbound's
deliberate whole-entry pagination; a ScrollView is an option, not a forced UX.

Treat reading-size changes as logical layout changes. Resizing the native window
currently preserves the logical canvas ([game.py](../saga2d/game.py), lines
202–206); it is not typography scaling. Reusable remeasurement/reflow and focus
visibility would remove part of Shardbound's accessibility plumbing and make
longer translated strings practical. String catalogs and translation policy can
stay with games initially.

The engine's own [MatchMenu](../saga2d/multiplayer_ui.py), lines 242–264, manually
translates key names into restricted ASCII text. Add actual text input events,
a focused text field, cursor/selection/clipboard behavior, then test Unicode
entry and composition on supported native platforms. Key bindings and text
entry must be separate so typing cannot trigger gameplay shortcuts.

Acceptance: a custom card, a tech node, a nested scrolling list and the room
form all use the same focus/input rules. Disabled and clipped controls cannot
receive pointer activation; disabled controls cannot activate by any route.
Keyboard navigation reveals an offscreen control before activation.
Focus/capture cannot survive removal; real mouse/keyboard dispatch and native
pixels agree with the mock. Controller navigation can use this seam later.

### Match sessions and event delivery

The common lifecycle code appears in
[Tribes multiplayer](../../tribes/tribes/multiplayer.py), lines 105–137,
[Warband multiplayer](../../warband/warband/multiplayer.py), lines 161–224, and
[Shardbound multiplayer](../../shardbound/eador/multiplayer.py), lines 90–129.
Shardbound's `_transferring` flag prevents scene replacement from closing a
connection that the replacement still needs. That is evidence for match-owned
session lifetime, rather than connection lifetime tied to one scene.

Start with one explicit session handle shared between scenes: poll on the game
thread; report state, revision and status changes; close exactly when leaving
the match. Give it one identifiable owner and explicit disposal; only introduce
a separate scope type if it removes additional caller complexity. Individual
scenes subscribe and unsubscribe. Preserve polling under menus. Leave snapshot
decoding, model identity, authority, pause rules and scene routing in games.
Do not promote the games' `__dict__.update` reconciliation into an engine pattern.

Separately, [Warband](../../warband/warband/multiplayer.py), lines 27–37 and
206–220, retains a 128-event tail and remembers the consumed ID.
[Shardbound CombatJournal](../../shardbound/eador/combat_journal.py), lines 24–57,
and [CombatInbox](../../shardbound/eador/concurrent_playback.py), lines 9–61,
already address epochs, gaps, count/byte limits and pending playback.
The server intentionally coalesces snapshots ([server](../saga2d/server/__init__.py),
lines 70–124). Latest state and ordered presentation events are different needs.

A small journal/cursor module can return new records or an explicit reset/gap.
It cannot promise exactly-once delivery or replay of history that has expired.
Keep visibility filtering, combat grouping, replay rules, digests and recovery
choices in games. Never include hidden game information merely to simplify a
shared event stream.

Acceptance: real local-server tests with reconnects, slow readers, duplicate
snapshots, an exhausted tail, scene replacement and nested menus. Both LAN and
online adapters exercise the same session interface.

### Grid/search and scores: useful, but not the first release

[Warband path.py](../../warband/warband/path.py) supplies optimized eight-way
A*, regions and distance fields. [Tribes view](../../tribes/tribes/view.py),
line 47 onward, supplies isometric projection/picking. A square-grid counterpart
to [HexGrid](../saga2d/hexgrid.py) is sensible, but geometry and optimized search
need not be one universal topology framework.

Specify connectivity, diagonal corner rules, tie-breaking and unreachable
results. Preserve deterministic path choices and benchmark Warband before
replacing its byte-grid implementation with callbacks. Tribes' movement rule
can consume all remaining movement when entering certain tiles
([model.py](../../tribes/tribes/model.py), line 343); ordinary weighted A* does
not automatically model that. Formation, work assignment, avoidance and
replanning remain local. A shared movement-search abstraction may never be worth
extracting; square-grid geometry does not depend on making that decision.

[Tribes scores](../../tribes/tribes/scores.py), line 39 onward, and
[Warband scores](../../warband/warband/scores.py), line 89 onward, offer a small
ranked-record extraction. Do it if it deletes the duplicate algorithms without
requiring games to adopt a generic score schema. It has less leverage than UI.

## General engine limitations and significant improvements

### 1. Explicit clocks and lifetimes

`Game.tick(dt)` couples one scene update and one render. It advances actions,
particles, timers, tweens and animation globally after scene updates
([game.py](../saga2d/game.py), lines 398–481). `pause_below` only selects which
scenes receive `update`. Scene timers are cancelled on removal but keep running
under a paused overlay; arbitrary tween targets have no scene ownership.

A public-interface probe in this review confirmed: after a 0.5-second paused
frame, the underlying scene had zero updates, its timer had fired and its tween
was halfway complete. Removing the scene and ticking another 0.5 seconds still
completed the tween on its ordinary Python target. This is a limitation of the
current ownership contract, not proof that all background advancement is wrong.
Network scenes deliberately depend on it.

Add explicit scene/session clock domains and owned cancellable animation work.
Preserve existing behavior during migration. Add an opt-in fixed-step clock
with remainder/interpolation information, a maximum catch-up budget and a
declared policy for dropped time. Keep variable-rate UI animation.

Offline [Warband](../../warband/warband/scene.py), lines 1206–1217, and its
[LAN path](../../warband/warband/multiplayer.py), lines 168–180, use separate
accumulators. The [hosted loop](../saga2d/server/__init__.py), lines 359–388,
steps every 50 ms, publishes every second step and discards missed time. Make
simulation/publication rates explicit per hosted game before supporting another
real-time genre. An accumulator alone does not make a model deterministic.

Acceptance: equal elapsed time split into different frame intervals produces
the same fixed steps outside the declared overload case; local/LAN/server policy
is explicit; pausing freezes intended work while session polling continues;
removing a scene cancels its callbacks/tweens without cancelling global music.

### 2. Asset and native-resource lifetime

[AssetManager](../saga2d/assets.py), lines 26–97, caches loaded images/sounds
without a release interface; same-key registration returns the old image and
in-place update requires the same dimensions. [Warband title](../../warband/warband/title.py),
lines 248–254, deletes `assets._images` directly when preview dimensions change.
The renderer retains padded atlas images
([pyglet_backend.py](../saga2d/backends/pyglet_backend.py), lines 484–486).

First add a public replacement operation with clear behavior for existing
sprites. Then use actual map/scene transitions to design asset bundles and
release semantics. Removing a dictionary entry is not GPU-memory reclamation:
atlas allocation and outstanding sprite handles must be part of the design.
Expose a small read-only resource snapshot for diagnostics and set explicit
budgets from measurements. Do not claim an unbounded leak merely because a
cache grows to accommodate new content.

Support staged preparation/progress and game-thread uploads when needed.
Warband already advances texture warmup a few items per frame
([scene.py](../../warband/warband/scene.py), line 1182), and has a background
sound-generation queue ([sound.py](../../warband/warband/sound.py), line 80).
Keep generation, compositions and content-cache rules in Sagaforge/games;
prebuilt assets should not require background generation at runtime.

An immediate correctness item already has separate evidence: Absolution's
[OpenAL lifetime investigation](../../absolution/docs/OPENAL_LIFETIME.md)
records interrupted native buffers not being reclaimed and an isolated
audio-only fix, `6e942d8` at `/tmp/saga2d-openal-fix`. Review/integrate that
candidate before redesigning audio. It is not in this reviewed engine revision.
Its native checks were not rerun for this review. The separate
[renderer investigation](../../absolution/docs/MEMORY_DIAGNOSIS.md) proves
allocation churn; it explicitly does not establish an unbounded renderer leak
or a successful full-game RSS fix. Keep those claims separate.

Acceptance: repeated preview resizing, scene changes, music interruption and
long sessions have bounded relevant resource counts after warmup. Measure frame
time, native allocations and RSS separately; validate exact pixels where pooling
changes storage reuse.

### 3. An input interface suitable for action games

[InputEvent/InputManager](../saga2d/input.py), lines 21–48 and 97–107, expose
keys/pointer events and key state. The [backend event union](../saga2d/backends/base.py),
line 80, has no controller or text/composition events. Current scene controls
are key-to-method declarations, not remappable device-independent actions.

Add named actions with pressed/released/held state and axes; bind keyboard,
pointer and controller through that interface. Support dead zones, rebinding,
device disconnect and UI/gameplay contexts without losing the concise controls
interface for simple games. This is a substantial capability gain for arcade,
platform, action and couch-play games. Native focus and text entry come first.

Prove it with a small top-down action game: move/aim/dash, pause, remap controls,
disconnect/reconnect a controller, resume. The same action transcript should
exercise the mock and native input routes. Do not attempt rollback networking
as part of this proof.

### 4. A modest path beyond today's renderer and spatial tools

The runtime currently chooses one world camera per frame
([game.py](../saga2d/game.py), lines 460–473). There is no public composition of
multiple viewports, offscreen render targets or materials. Animation uses named
images at a uniform frame duration ([animation.py](../saga2d/animation.py),
lines 45–74). The public collision module provides rectangles and overlap tests,
not spatial indexing, sweep tests or physics ([collision.py](../saga2d/util/collision.py)).

These constrain split-screen, lighting/postprocessing, large moving populations
and action collisions. Prioritize sprite-sheet regions, flip/filter controls,
per-frame animation timing and a bounded spatial-query module only as a proof
game needs them. A top-down action proof can justify a spatial hash and sweep
query; collision response remains in that game. A later split-screen proof can
justify viewport/camera composition. Add render targets before considering a
large shader framework. Concave polygon triangulation is another bounded
improvement; current convex-only behavior is now documented.

Do not replace pyglet, introduce an ECS or write a rigid-body physics engine
on the strength of missing features alone. Measure actual draw/update cost
before considering native acceleration. Existing batching, label/image reuse
and FrameTimer are useful foundations, not evidence of any universal scale limit.
For large maps, benchmark mostly-offscreen content before extracting culling or
tile/chunk drawing; keep terrain and world-generation rules out of that module.

### 5. Packaging and release confidence are engine features

[GamePackage](../saga2d/packaging/__init__.py), lines 39–50, has no game-data
declaration; the [PyInstaller recipe](../saga2d/packaging/game.spec), line 13,
explicitly adds engine fonts and release metadata. Absolution owns a parallel
freeze pipeline with `--collect-data absolution`
([freeze.py](../../absolution/tools/freeze.py), lines 138–149). Add game package
data and required supplemental runtime notices to the shared recipe. Avoid
copying all of Absolution's release policy into the engine. Offline verification
already exists when `GamePackage.online` is empty.

Engine [CI](../.github/workflows/tests.yml) currently has one Ubuntu/Python 3.12
job. It builds and tests an installed wheel, but uses the mock for distribution
rendering; native tests skip without a display. This is insufficient coverage
for a desktop engine's cross-platform native claims.

Add a small installed-wheel matrix: core behavior, native render/input/audio
smokes on supported desktop platforms, and oldest/current supported Python.
Use managed displays and silent audio where appropriate. Keep an explicit
manual/hardware lane for what virtual CI cannot prove. Add representative
consumer journeys in isolated candidate environments; do not repin all games
on every engine commit or run every expensive game suite for every patch.

Before native optimization, establish repeatable scenes for idle UI, changing
text, many sprites, scene turnover and interrupted audio. Record p50/p95 frame
time and resource counts; performance acceptance needs stable host conditions.

### 6. Multiplayer scope must be explicit

The server already has a versioned handshake, bounded queues, snapshot
coalescing, reconnects and durable rooms. It nevertheless models two seats
([Room](../saga2d/server/__init__.py), lines 133–154), fixed rates, full JSON
snapshots and sequential match stepping in one event loop. One expensive match
can delay others; dropping missed time is an overload policy, not isolation.

Configurable rates and explicit compatibility capabilities are a reasonable
next step. Independent engine releases do not automatically make independently
evolving game rules/wire schemas compatible. Games should declare their game
identity/schema expectations clearly and surface useful mismatch errors.

Add N-player rooms or spectators only with a concrete consumer. Measure
snapshot sizes, encoding time and per-room simulation cost before adding deltas,
worker processes or interest management. Twitch multiplayer, prediction,
rollback, public matchmaking and MMO-style hosting are separate projects.

## What should stay out

- Armies, combat systems, fog knowledge, economies, cards/decks, campaigns,
  progression, AI and game-state schemas: shared words do not make shared rules.
- A universal strategy scene, inventory, codex, save browser, tutorial or
  settings screen: share mechanics underneath, retain game-specific presentation.
- Automatic object serialization/migration: games own semantic validation and
  old-state conversion; durable envelope storage already exists.
- Procedural art/music generation: Sagaforge is the correct separate package.
- A full editor, ECS rewrite, general 3D runtime, browser/mobile export or console
  port as the next milestone. These require separate product and platform work.
- Premature global-context removal: only one live Game is currently allowed
  ([game.py](../saga2d/game.py), lines 119–123). That limits embedding/multi-window
  use, but does not need a rewrite before one concrete use case requires it.

## Suggested sequence

1. **Two independent starting lanes.** First, review/integrate the existing
   audio fix, rerun its native ownership regression on the integrated revision,
   and verify affected consumers before a compatible patch release. Ninefold's
   audio adoption fix is a separate game commit. Second, consolidate existing
   native checks and performance evidence into a repeatable installed-wheel
   smoke matrix and recorded resource/frame baseline. The infrastructure lane
   must not hold a verified correctness patch hostage, or vice versa.
2. **UI depth.** Text layout/fitting, focus/activation and true text input as
   separate tested increments; then clipping/pointer ownership and ScrollView.
   Migrate at least two real consumers, including a custom-drawn control.
   Alongside this work, run a bounded, throwaway top-down action spike with
   game-local movement/aim/dash and pause. Use it to discover requirements before
   committing new action-input, clock or spatial interfaces to the engine.
3. **Resource depth.** Public image replacement, measured bundle lifetime and
   staged preparation; complete package-data support. Keep audio correctness
   independent of speculative renderer optimization.
4. **Simulation and matches.** Explicit clocks, match-owned session lifetime,
   journal/cursor and configurable hosted rates. Introduce each independently
   so pause policy and networking changes remain reviewable.
5. **Complete the new-genre proof.** Promote only the primitives the early
   action spike proves: remappable/controller input, fixed stepping, animation
   and spatial queries as needed. This is not a new full game-production project.
   Add grid/search or viewports when their respective consumer is ready.

Stages are an ordering, not a promise to bundle everything into 0.3.0. That
version already has unreleased changes. Compatible fixes and additive features
can ship separately; changed behavior needs an explicit migration. Every
extraction is complete only when its duplicate callers are deleted and the
affected games pass against the candidate, then regain their released engines.

## Verification and adoption findings

This review changed documentation only. No game dependency, installed engine,
server or runtime behavior was changed. Source inspection was split across
independent engine/strategy/new-game reviews and then reconciled locally.

- Focused existing engine checks: scene stack, Game.close, frame pacing and audio,
  **42 passed**. This is not a full-stack test result or performance benchmark.
- Public clock probe: covered-scene timer/tween behavior and an unowned tween
  continuing after scene removal, as described above.
- Public Ninefold mock probe: its SoundBank constructs a separate AudioManager
  ([sound.py](../../ninefold/ninefold/sound.py), lines 324, 348, 358) that is never
  advanced by Game.tick. After 120 ticks a 1.5-second music fade remained at
  volume 0; directly updating the bank completed it. Use the existing
  `game.audio` with absolute paths, as Warband does. This is a game adoption fix,
  not a reason to build a generic subsystem-registration framework.
- `Game.close`, Settings, wrapped Label, button shortcuts, camera insets and
  offline packaging verification already exist. Private teardown and older
  workarounds in consumers should be removed through adoption, not duplicate
  engine features.
- Native audio/renderer findings above are attributed to existing Absolution
  evidence, not claimed as fresh native reproductions in this review.
- Independent advisory review used `claude-opus-4-8` through the
  [second-opinion skill](/Users/ikamen/.agents/skills-inactive/second-opinion/SKILL.md).
  Its useful changes were an earlier action spike, independent correctness and
  baseline lanes, and a smaller initial session handle. Its claims that absent
  parent clipping is already a contract violation and that native acceptance is
  currently unfalsifiable were rejected: source inspection establishes a missing
  capability, and existing native tools/evidence remain usable despite the
  incomplete CI matrix. Warband's private image-cache deletion needs a new
  replacement interface, not just adoption of an existing one. The raw advisory
  response is in [review evidence](evidence/engine-review-2026-09/second-opinion.json).
