# Frame pacing

Ordinary games need no custom limiter:

```python
game.run(TitleScene())          # at most 60 FPS; at most 15 while inactive/hidden
game.run(TitleScene(), fps=30)  # an application can choose a lower foreground cap
```

The loop sleeps for the remaining interval after actual frame work, including
VSync. It does not spin or issue catch-up frames after an overrun. Native window
activation/deactivation and show/hide events change the cap; a shown window
without focus remains inactive. Polling continues, so input, window closure and
audio completion keep working. An inactive event may wait up to about 67 ms plus
the actual frame work before dispatch. Real elapsed time still drives updates.

`tick(dt)` deliberately does not wait or alter the supplied timestep. Embedders,
native verification tools and simulations that call it directly own their clock.
Mock/model tests should not acquire wall-clock waits from the framework.

`tools/verify_frame_pacing.py` is a runnable example independent of Shardbound:

```sh
uv run python tools/verify_frame_pacing.py --check --output /tmp/pacing-example
```

It draws a moving circle and sends native focus/visibility callbacks in a hidden
window, including a show/focus restoration and a keyboard command in every phase.
`--scene shard` puts the real Shardbound map beneath the observation scene. The
same script can run from an older checkout with `--check` omitted to measure the
uncapped baseline. Reports record source hashes, elapsed time, rendered frames,
CPU time and cleanup. Captures are actual native frames. Synthetic callbacks test
the event path; they are not a human focus walkthrough or a battery-life estimate.

The regression is concrete: before this change a minimal ordinary `Game.run`
produced 81,030 mock frames in 0.2 seconds. `pyglet.clock.tick()` supplies time but
does not itself impose a frame limit, and a hidden window's VSync did not prevent
the real Shardbound map from rendering 165–179 FPS at about 90% of one core. The
limiter belongs to Saga2D because all game launchers share this loop. No battle,
campaign, idle-turn or game-specific animation policy enters the framework.

Native test drivers have separate limits, and model fuzzers require CPU budgets:
neither VSync nor a `run()` cap can throttle code that deliberately bypasses it.
Run one expensive job at a time on an interactive machine.

Primary implementation context: [Pyglet's event-loop documentation](https://pyglet.readthedocs.io/en/latest/programming_guide/eventloop.html)
and [window events](https://pyglet.readthedocs.io/en/latest/modules/window.html).
