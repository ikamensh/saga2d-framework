# Renderer follow-up from Warband melee acceptance

Warband `25c1f3c` on Saga2D 0.3.2 misses its existing 150-unit W10
p95 <16 ms gate. The ordinary native battle at 1280×800 (Retina scale 2,
Apple M4, macOS 26.6.2) has late p95 33.2 ms with cooperative CPU pacing
and 17.9 ms with the benchmark's ordinary unpaced loop. The same paced
comparison with pre-melee view/scene `7655d0e` gives 34.4 ms, with identical
final simulation state. These are failures, not accepted performance results.

A separate last-120-frame cProfile run shows 9,962 shape vertex-list
allocations and 120 batch draw-list reconstructions. Profiling is diagnostic
only; its frame times are not acceptance evidence. Melee trails account for
0.040 s total and body lunges for 0.007 s under that profile. The existing
shape-buffer candidate `238584d` directly addresses the measured churn.
Review and adapt that change independently of its text-slot parent and the
separate OpenAL lifetime candidate; do not assume the old branch is current.

The temporary Warband timing wrapper also paced the scene's incremental
image warmer inside early ticks. Correct the wrapper before further timing;
the late-frame window is after that warmer finishes. Preserve the failed
measurements with this qualification rather than treating startup sleeps as
rendering work.

## Acceptance before implementation

- Repeated shape draws and alternating layer orders reuse bounded storage:
  the native public Scene draw path must not build a new set of discarded
  renderer cycles on every frame. Use the old candidate's actual allocation
  regression as the initial red signal, separately from timing.
- Drawn pixels match fresh windows after shape resizing, recolouring,
  transparency, overlapping layers, disappearance and return, in world and
  screen space under camera movement/zoom. Inactive cached geometry must
  draw nothing. Inspect native output as well as pixel assertions.
- Keep the backend protocol and draw ordering unchanged. Bound retained idle
  buffers relative to observed concurrent use; review scene-turnover behavior.
- Compare the same warmed Warband battle before/after without a profiler or
  simultaneous expensive work, with explicit pacing and source metadata.
  Keep all units, terrain, AI, art and effects. Verify its unchanged model
  fingerprint and native crowded frame. Require the existing W10 gate;
  report any remaining miss honestly.
- Exercise a second game's real scene before claiming shared benefit, run
  engine and affected consumer suites, and complete installed-wheel/release
  verification before migrating Warband's released engine dependency.

This is a focused S2D-003 investigation needed by WB-004. It does not complete
the broader S2D-001 branch inventory or S2D-002 scene matrix.

## Initial shape candidate

The public native Scene regression on current main failed with **277,854
bytes** of discarded cycles after 60 alternating shape-layer frames. Adapting
only the shape changes from `238584d` makes that regression pass. All seven
native backend checks pass, including a new comparison against fresh windows
through geometry resizing, overlapping transparency, camera pan/zoom, hidden
frames and return after layer churn. The existing text cache and audio path
are unchanged. Native battle timing and consumer/release acceptance remain
outstanding; the allocation result alone is not a performance claim.

The first shape-only battle run still misses the gate (late p50 11.4 ms,
p95 19.5 ms). It fixes the demonstrated allocation churn, but is not sufficient
to claim faster gameplay. The profile also shows 32,253 sprite synchronizations
over 120 frames. Pyglet's `Sprite.update` rewrites translation and scale arrays
for every supplied non-None argument, even when unchanged. The backend now
passes those arguments only when the desired value changes. A native public
Sprite journey compares movement, resizing, image-dimension swaps and rotation
against fresh windows. All eight native backend tests pass and captured shapes,
empty frames and rotated sprites were inspected. Repeat battle timings with
the corrected measurement wrapper before accepting a performance claim.

The corrected-wrapper comparison remains above the target: released 0.3.2
has late p50 10.9 / p95 18.4 ms; candidate `829b4cf` has 10.5 / 18.5 ms.
Whole-run p95 is 17.8 versus 17.1 ms. These small differences are insufficient
to accept W10. No performance acceptance is inferred from this comparison.

Inspecting the repeated colour uploads exposed a correctness bug: pyglet's RGB
setter resets alpha to 255. A public native Sprite test failed with rendered
RGB `(127, 255, 63)` where opacity zero required black. Sending the desired
RGBA together instead of updating opacity and then RGB makes the test pass
at 0, 64, 128 and 255 opacity after movement. The quarter-opacity frame was
opened and inspected. This also removes the two conflicting colour uploads
on every fading sprite update.

The complete engine suite passes **398 tests in 19.16 s**, including native
tests on the awake display (`docs/evidence/render-shapes/engine-tests.log`).
This verifies the current candidate, not the still-open game timing or release
gates.

## Offscreen group probe

The exact Warband battle supplied 1,398 path requests. A bounded neighbour-grid
prototype preserved every path and reduced isolated path work by about 10–12%,
but did not bring the battle under budget. No model/path change was adopted.

A separate rendering-only probe skips world groups when all their visible
sprites fall outside the camera. Groups containing immediate shapes remain
visible. Sprite extents include rotation and a filtering margin. On unchanged
model code and engine `830d69f`, late p95 becomes **15.6 ms**, while whole-run
p95 remains **16.2 ms**. The final crowded frame is byte-for-byte equal to the
unculled frame, and was opened. This is promising but not complete acceptance.

Before adopting culling: native checks must cover camera pan/zoom, rotation
reaching across the viewport edge, visibility and removal, changing images,
and immediate images/shapes sharing a group with offscreen retained sprites.
Keep screen-space UI and independent text groups unaffected. Re-run the same
battle with culling enabled/disabled on the implemented candidate, with both
late and whole-run percentiles recorded. All rendering and consumer checks
remain required before a release.

## Implemented culling and text reuse

On `e020089`, the same battle with culling enabled gives late p95 **15.1 ms**
and whole-run p95 **16.9 ms**. Disabling only that method gives **19.8 / 18.8
ms** respectively. The final model digest and rendered crowd are unchanged.
Native culling checks cover camera/rotation, shared groups, immediate draws,
hiding, removal and return. The whole-run acceptance remains open. A 4096px
atlas probe gives 15.0 / 16.4 ms while allocating 448 MiB of RGBA atlases; it
is not adopted on that weak evidence.

The separately recovered text-slot candidate `6ff2670` addresses another
confirmed lifetime fault: alternating text layers retain **610,989 bytes** of
discarded renderer cycles in 60 frames before the change. The bounded slot
implementation passes that regression and all **13 native backend checks**.
Fresh-window pixel comparisons include content and opacity changes, duplicate
labels, empty text, hiding/return, anchors, layers, camera movement and zoom.
The translucent overlapping text frame was opened. This proves correctness
and bounded reuse; repeat battle timing before claiming a speed improvement.

Text reuse on `ef4bc39` leaves whole-run p95 at **16.9 ms** (late 17.1 ms).
Do not infer a battle speed gain from that allocation fix. The next bounded
change retains each view group's sprite membership and recalculates camera
visibility only for changed groups or camera movement. Native acceptance must
still cover adding/removing/reordering sprites, immediate images moving between
groups, shapes disappearing, pan/zoom and shared-group visibility. Require the
same battle gate; stationary scenery must remain visible without rechecking
its bounds each frame.

On `5668c80`, dirty-group culling gives late/whole p95 **15.9 / 16.5 ms**.
Moving blend setup from the parent view group to the shape shader avoids
duplicating pyglet SpriteGroup state calls; `59b6967` gives **15.6 / 16.2 ms**.
An analytic native shape/image/shape alpha check passes before and after, and
the full engine suite passes **403 tests in 25.11 s**. The next bounded change
skips unchanged shape position/colour uploads; the existing fresh-window
comparisons cover resizing, colour changes, hiding and return.

Tribes `888cdac`, using its ordinary 19×19 map with fog/HUD and two camera pans,
compares release 0.3.2 with `59b6967`: 360 unprofiled frames have p50/p95
**1.79 / 3.48 ms** before and **1.67 / 3.06 ms** after. The world digest is
identical. Both native map frames were opened; no shared broad performance
claim is inferred from this small single scene. Evidence is in Tribes'
`docs/evidence/wb004-engine/`.

## Accepted battle timing

Candidate `ebd346c` passes the unchanged W10 threshold: **720 frames p50
9.0 ms / p95 15.58 ms**, with late p50 **8.4 ms / p95 15.1 ms**. The first
large pathfinding burst still reaches 109 ms; this percentile pass is not a
claim that startup spikes disappeared. Compare the corrected release baseline
(whole p95 17.8 ms) under the same 1280×800, Retina-2, unpaced timed loop and
25%-paced asset warmup. No profiler, simultaneous heavy local job, reduced
army, disabled AI/fog/HUD, larger atlas or model optimization was used.

The final 144-unit world digest remains
`51df29e630e6439a147f9115f2b7c47d7feaebddc7b48d02fe96889be6e3baf2`.
The crowd frame is byte-identical to the culling-only frame and was opened.
Evidence: Warband `docs/evidence/melee/mixed-unchanged-soups/metadata.json`
and its adjacent log. The release-version engine suite passes **403 tests in
25.02 s**, including all 14 native checks. Consumer and distribution checks
are required below before publishing.

Tribes' small screenshot difference is confined to its pulsing cursor glow: its
requested opacity now works instead of being reset to opaque by the old RGB
setter. The scene and model are unchanged; the native frames were inspected.

Final consumers: Warband **1048 passed, 12 skipped** with its unchanged
simulation fingerprint; Tribes **189 passed**. Its real keyboard/mouse
victory, leaderboard, restart and storage-error journey passes, with native
results and leaderboard frames inspected. Final human-sword and dwarf-hammer
Warband captures pass at normal/near/far zoom with all eight facings; native
matrices were inspected. Existing tutorial-alert overflow and Tribes' title
edge warning are retained observations, not renderer regressions addressed here.

Saga2D 0.3.3 is the compatible release prepared for these fixes. Distribution
and PyPI receipts are recorded after verifying the exact immutable artifacts.

## Published engine

Saga2D **0.3.3** is published from commit/tag `9a1a58c` / `v0.3.3`.
The source distribution builds the wheel; both pass strict metadata checks.
An isolated installed-wheel scene/socket check passes, and all **14 native
backend regressions pass against that installed wheel** (Python 3.12, current
pyglet 2.1.16). The locked engine suite also covers pyglet 2.1.13. A separate
fresh PyPI installation passes the same distribution check, and PyPI's file
hashes match the exact verified artifacts:

- Wheel: `4895608a488285f82a6fd060e3423cdd0ee38e8b30a84b434535bdf6217531da`
- Source: `7ba6d5b027b944acda38c48fd136bc238ab39e7356d06992714d8c0120789497`

[Engine CI 35240239742](https://github.com/ikamensh/saga2d-framework/actions/runs/35240239742)
passes on the tagged source. Receipts are under `docs/evidence/render-shapes/`
(`distribution.json`, `pypi-verification.json`, `wheel-native.log`).
Warband has deliberately upgraded its pin/lock to this release; its hosted
compatibility and downloaded-client acceptance belong to WB-004's rollout.
S2D-003's broader resource soak is still open, without a leak/RSS claim.
