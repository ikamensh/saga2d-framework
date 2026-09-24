"""Frame telemetry: how a game actually ran on the player's machine, kept beside its saves.

``Game.run()`` times every frame and folds the frames into windows of a few
seconds. Each window becomes one JSON line in
``<data_dir>/telemetry/<started>-<pid>-<part>.jsonl``: frame-interval and
work percentiles, the split between update, draw and present, hitches, CPU,
full garbage collections, the window's size, and whatever the scenes say
about themselves (:meth:`Scene.telemetry_context`, :meth:`Telemetry.phase`).
A file that reaches ``file_limit`` continues in the next part, and the oldest
files are deleted while the directory holds more than ``total_limit``.

Only ``run()`` records: a test or tool that drives ``tick(dt)`` itself owns
its clock and writes nothing, and the mock backend has no frames worth
keeping. ``SAGA2D_TELEMETRY=0`` turns it off. Nothing leaves the machine.

``python -m saga2d.telemetry DIR`` summarises what a data directory holds.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, ContextManager, TextIO

#: Seconds of frames folded into one line.
WINDOW_SECONDS = 5.0
#: A file this large continues in the next part.
FILE_LIMIT = 4 * 1024 * 1024
#: The directory is pruned, oldest file first, down to this.
TOTAL_LIMIT = 16 * 1024 * 1024
#: A frame interval at least this long is a hitch the player sees.
HITCH_MS = 50.0

_NULL_PHASE = nullcontext()


def enabled_by_default() -> bool:
    """``SAGA2D_TELEMETRY=0`` (or ``false``/``no``) turns recording off; anything else leaves it on."""
    return os.environ.get("SAGA2D_TELEMETRY", "").strip().lower() not in ("0", "false", "no")


def _percentiles(values: list[float]) -> list[float]:
    """p50, p95, p99 and max of *values*, in ms rounded to 0.1."""
    ordered = sorted(values)
    last = len(ordered) - 1
    return [round(ordered[min(last, int(p * len(ordered)))], 1) for p in (0.5, 0.95, 0.99)] + [round(ordered[last], 1)]


class Telemetry:
    """A game's frame recorder. ``Game`` owns one as ``game.telemetry``; ``run()`` starts and stops it.

    Set :attr:`enabled`, :attr:`directory`, :attr:`window` or the limits before ``run()`` to
    change whether, where and how much it keeps.
    """

    def __init__(self, directory: Path, *, enabled: bool) -> None:
        self.directory = directory
        self.enabled = enabled
        self.window = WINDOW_SECONDS
        self.file_limit = FILE_LIMIT
        self.total_limit = TOTAL_LIMIT
        #: The file being written, while recording.
        self.path: Path | None = None
        self._stream: TextIO | None = None
        self._header: dict[str, Any] = {}
        self._describe: Callable[[], Mapping[str, Any]] = dict
        self._session = ""
        self._part = 0
        self._began = 0.0
        self._frames_total = 0
        #: The previous frame's start and its (update, draw, present) ms: its interval ends when the next frame starts.
        self._last: tuple[float, tuple[float, float, float]] | None = None
        self._frame_phases: dict[str, float] = {}
        self._reset_window(0.0)

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self, header: Mapping[str, Any], describe: Callable[[], Mapping[str, Any]]) -> None:
        """Open a session: *header* heads every part; *describe* is asked for the extra fields of
        each window (window size, the scenes' context) as it closes."""
        if self._stream is not None:
            raise RuntimeError("telemetry is already recording")
        self._header = {**header, "window_s": self.window}
        self._describe = describe
        self._session = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-{os.getpid()}"
        self._part = 0
        self._began = time.perf_counter()
        self._frames_total = 0
        self._last = None
        self._frame_phases.clear()
        self._reset_window(self._began)
        self._open_part()

    def phase(self, name: str) -> ContextManager[None]:
        """Time a block as part of *name*; each window reports the mean ms per frame spent in each phase.

        ``with game.telemetry.phase("ai"): ...`` Returns a shared no-op while not recording.
        """
        if self._stream is None:
            return _NULL_PHASE
        return self._timed(name)

    @contextmanager
    def _timed(self, name: str) -> Iterator[None]:
        began = time.perf_counter()
        try:
            yield
        finally:
            self._frame_phases[name] = self._frame_phases.get(name, 0.0) + (time.perf_counter() - began) * 1000

    def frame_begins(self, now: float) -> None:
        """A frame starts at *now* (``perf_counter``): the previous one lasted until now, and a window
        that has run :attr:`window` seconds closes here, before this frame does any work."""
        if self._stream is None:
            return
        if self._last is not None:
            self._end_last(now)
            if now - self._window_start >= self.window:
                self._close_window(now)

    def frame_ends(self, started: float, drawing: float, finished: float, present: float, *,
                   scene: str | None, foreground: bool) -> None:
        """The frame that began at *started* began drawing at *drawing* and finished at *finished*,
        *present* seconds of that in presenting it (VSync, the GPU); the top scene is *scene*.

        A frame whose scene or focus differs from its window's starts a new window, so each window
        holds one scene in one state.
        """
        if self._stream is None:
            return
        if self._frames and (scene != self._scene or foreground != self._foreground):
            self._close_window(started)
        if not self._frames:
            self._scene, self._foreground = scene, foreground
        update = (drawing - started) * 1000
        draw = (finished - drawing - present) * 1000
        self._frames += 1
        self._work.append(update + draw)
        self._update += update
        self._draw += draw
        self._present += present * 1000
        for name, ms in self._frame_phases.items():
            self._phases[name] = self._phases.get(name, 0.0) + ms
        self._frame_phases.clear()
        self._last = (started, (update, draw, present * 1000))

    def stop(self) -> None:
        """Write the open window and a closing line; safe to call when not recording."""
        if self._stream is None:
            return
        now = time.perf_counter()
        if self._last is not None:
            self._end_last(now)
            self._close_window(now)
        self._write({"kind": "end", "t": round(now - self._began, 3), "frames": self._frames_total})
        self._stream.close()
        self._stream = None
        self.path = None

    # -- windows -----------------------------------------------------------------

    def _end_last(self, now: float) -> None:
        """The previous frame lasted until *now*: record its interval, and keep it if it is the worst."""
        assert self._last is not None
        started, split = self._last
        interval = (now - started) * 1000
        self._intervals.append(interval)
        if interval > self._worst[0]:
            self._worst = (interval, *split)
        self._last = None

    def _reset_window(self, now: float) -> None:
        self._scene: str | None = None
        self._foreground = True
        self._window_start = now
        self._cpu_start = time.process_time()
        self._gc_start = gc.get_stats()[2]["collections"]
        self._frames = 0
        self._intervals: list[float] = []
        self._work: list[float] = []
        self._update = self._draw = self._present = 0.0
        self._worst: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._phases: dict[str, float] = {}

    def _close_window(self, now: float) -> None:
        seconds = now - self._window_start
        frames = self._frames
        row: dict[str, Any] = {
            "kind": "window",
            "t": round(self._window_start - self._began, 3),
            "s": round(seconds, 3),
            "scene": self._scene,
            "fg": self._foreground,
            "frames": frames,
            "fps": round(frames / seconds, 1),
            "frame_ms": _percentiles(self._intervals),
            "work_ms": _percentiles(self._work),
            "update_ms": round(self._update / frames, 2),
            "draw_ms": round(self._draw / frames, 2),
            "present_ms": round(self._present / frames, 2),
            "hitches": sum(1 for ms in self._intervals if ms >= HITCH_MS),
            "worst": dict(zip(("frame", "update", "draw", "present"), (round(v, 1) for v in self._worst))),
            "cpu": round((time.process_time() - self._cpu_start) / seconds, 2),
            "gc_full": gc.get_stats()[2]["collections"] - self._gc_start,
        }
        if self._phases:
            row["phases"] = {name: round(ms / frames, 2) for name, ms in sorted(self._phases.items())}
        row.update(self._describe())
        self._frames_total += frames
        self._write(row)
        self._reset_window(now)

    # -- files -------------------------------------------------------------------

    def _open_part(self) -> None:
        self._part += 1
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / f"{self._session}-{self._part:03d}.jsonl"
        self._stream = open(self.path, "a", encoding="utf-8")
        self._write({"kind": "session", "part": self._part, **self._header})
        self._prune()

    def _write(self, row: Mapping[str, Any]) -> None:
        assert self._stream is not None
        self._stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        self._stream.flush()
        if row["kind"] == "window" and self._stream.tell() >= self.file_limit:
            self._stream.close()
            self._open_part()

    def _prune(self) -> None:
        """Delete the oldest files until the directory holds at most ``total_limit`` bytes; never the open one."""
        files = sorted(self.directory.glob("*.jsonl"))
        total = sum(path.stat().st_size for path in files)
        for path in files:
            if total <= self.total_limit:
                break
            if path != self.path:
                total -= path.stat().st_size
                path.unlink(missing_ok=True)


# -- reading -----------------------------------------------------------------------


def read(directory: Path) -> list[dict[str, Any]]:
    """Every session in *directory*, oldest first: ``{"header", "windows", "end", "files"}``.

    Parts of one session are joined; a session cut short (a crash, a pruned first part) has
    ``end`` None or starts at a later part.
    """
    sessions: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.jsonl")):
        key = path.stem.rsplit("-", 1)[0]
        session = sessions.setdefault(key, {"header": None, "windows": [], "end": None, "files": []})
        session["files"].append(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["kind"] == "session":
                session["header"] = session["header"] or row
            elif row["kind"] == "window":
                session["windows"].append(row)
            elif row["kind"] == "end":
                session["end"] = row
    return list(sessions.values())


def _weighted_percentile(pairs: list[tuple[float, float]], p: float) -> float:
    """The value below which a share *p* of the total weight lies."""
    ordered = sorted(pairs)
    total = sum(weight for _, weight in ordered)
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= p * total:
            return value
    return ordered[-1][0]


def summary(session: Mapping[str, Any], *, worst: int = 3) -> str:
    """A few lines on one session: its foreground frame rate over time, hitches, and the worst windows."""
    header = session["header"]  # every part opens with it, so a pruned first part loses nothing
    build = header["build"]
    windows = [w for w in session["windows"] if w["fg"]]
    lines = [f"{header['started']}  {header['game']}  {'v' + build['version'] if build else 'checkout'}  "
             f"saga2d {header['saga2d']}  {len(session['files'])} file(s)"]
    if not windows:
        return "\n".join(lines + ["  no foreground frames"])
    seconds = sum(w["s"] for w in windows)
    by_scene: dict[str, float] = {}
    for w in windows:
        by_scene[w["scene"]] = by_scene.get(w["scene"], 0.0) + w["s"]
    lines.append(f"  {seconds / 60:.1f} min in the foreground: " +
                 ", ".join(f"{name} {s / 60:.1f} min" for name, s in sorted(by_scene.items(), key=lambda kv: -kv[1])))
    fps = [(w["fps"], w["s"]) for w in windows]
    slow = sum(w["s"] for w in windows if w["fps"] < 30)
    lines.append(f"  fps: median {_weighted_percentile(fps, 0.5):.1f}, 5th percentile {_weighted_percentile(fps, 0.05):.1f}; "
                 f"under 30 fps {100 * slow / seconds:.0f}% of the time; "
                 f"hitches (>= {HITCH_MS:.0f} ms) {sum(w['hitches'] for w in windows)}")
    for w in sorted(windows, key=lambda w: w["fps"])[:worst]:
        extra = {k: w[k] for k in ("phases", "context", "window", "fullscreen") if k in w}
        lines.append(f"  at {w['t'] / 60:.1f} min {w['scene']}: {w['fps']} fps, frame p95 {w['frame_ms'][1]} ms, "
                     f"update {w['update_ms']} draw {w['draw_ms']} present {w['present_ms']} ms/frame, "
                     f"worst {w['worst']['frame']} ms  {json.dumps(extra, separators=(',', ':'))}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m saga2d.telemetry", description=__doc__.split("\n\n")[0])
    parser.add_argument("directory", type=Path, help="a game's data directory (e.g. ~/.warband) or its telemetry folder")
    parser.add_argument("--last", type=int, default=5, help="how many recent sessions to show (default 5)")
    parser.add_argument("--worst", type=int, default=3, help="worst windows listed per session (default 3)")
    args = parser.parse_args(argv)
    directory = args.directory.expanduser()
    if (directory / "telemetry").is_dir():
        directory = directory / "telemetry"
    sessions = read(directory)
    size = sum(path.stat().st_size for path in directory.glob("*.jsonl"))
    print(f"{directory}: {len(sessions)} session(s), {size / 1024:.0f} KB")
    for session in sessions[-args.last:]:
        print(summary(session, worst=args.worst))


def session_header(game_title: str, resolution: tuple[int, int], fps: float, build: Mapping[str, Any] | None) -> dict[str, Any]:
    """The facts that do not change during a session: what ran, on what, and with what cap."""
    from saga2d import __version__

    return {
        "game": game_title,
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "saga2d": __version__,
        "build": {"version": build.get("version"), "commit": build.get("source_commit")} if build else None,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpus": os.cpu_count(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "resolution": list(resolution),
        "fps_cap": fps,
    }


if __name__ == "__main__":
    main()
