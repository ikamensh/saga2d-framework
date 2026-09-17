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
