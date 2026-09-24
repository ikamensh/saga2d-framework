"""Frame telemetry: ``run()`` keeps how the game ran under ``<data_dir>/telemetry``, bounded in size.

Every test drives the real loop (``Game.run``) on the mock backend with recording switched on,
and reads the result back through :func:`saga2d.telemetry.read`, the reader the CLI uses.
"""

import json
import time

import pytest

from saga2d import Game, Scene
from saga2d import telemetry as telemetry_module
from saga2d.telemetry import read


class Timed(Scene):
    """Quit after *seconds* of wall time; say what the telemetry should know; spend time in a phase."""

    def __init__(self, seconds=0.3, then=None):
        self.seconds = seconds
        self.then = then
        self.frames = 0
        self.sizes = []

    def on_enter(self):
        self.started = time.monotonic()

    def update(self, dt):
        self.frames += 1
        with self.game.telemetry.phase("thinking"):
            time.sleep(0.001)
        directory = self.game.telemetry.directory
        self.sizes.append(sum(p.stat().st_size for p in directory.glob("*.jsonl")))
        if time.monotonic() - self.started >= self.seconds:
            if self.then is not None:
                self.game.replace(self.then)
                self.then = None
                self.started = time.monotonic()
            else:
                self.game.quit()

    def telemetry_context(self):
        return {"frames_seen": self.frames}


class Other(Timed):
    pass


def recording_game(tmp_path, window=0.05):
    game = Game("telemetry", backend="mock", save_dir=tmp_path / "saves")
    game.telemetry.enabled = True
    game.telemetry.window = window
    game.backend.inject_focus(True)  # a window starts unfocused until the OS says otherwise
    return game


def test_a_run_leaves_one_session_whose_windows_account_for_every_frame(tmp_path):
    """The header says what ran; the windows add up to the frames drawn; the scene's context and phases ride along."""
    scene = Timed(0.3)
    game = recording_game(tmp_path)
    game.run(scene)

    [session] = read(tmp_path / "telemetry")
    assert session["header"]["game"] == "telemetry"
    assert session["header"]["resolution"] == [1280, 800]
    assert session["end"]["frames"] == scene.frames == sum(w["frames"] for w in session["windows"])
    assert len(session["windows"]) >= 3
    for window in session["windows"]:
        assert window["scene"] == "Timed" and window["fg"] is True
        p50, p95, p99, worst = window["frame_ms"]
        assert 0 < p50 <= p95 <= p99 <= worst == window["worst"]["frame"]
        assert window["phases"]["thinking"] >= 1.0  # the scene slept 1 ms a frame inside it
        assert window["update_ms"] >= window["phases"]["thinking"]
        assert window["window"] == list(game.window_size)
        assert 0 < window["context"]["frames_seen"] <= scene.frames
    assert session["windows"][-1]["context"]["frames_seen"] == scene.frames


def test_windows_split_where_the_top_scene_changes(tmp_path):
    """A window never mixes two scenes' frames, so one scene's frame rate is not blurred into another's."""
    game = recording_game(tmp_path, window=10.0)
    game.run(Timed(0.15, then=Other(0.15)))

    [session] = read(tmp_path / "telemetry")
    assert [w["scene"] for w in session["windows"]] == ["Timed", "Other"]


def test_a_backgrounded_window_is_its_own_window(tmp_path):
    """Frames capped at 15 FPS behind another app are marked, not averaged into the foreground's rate."""

    class Hides(Timed):
        def update(self, dt):
            super().update(dt)
            if self.frames == 5:
                self.game.backend.inject_focus(False)

    game = recording_game(tmp_path, window=10.0)
    game.run(Hides(0.4))

    [session] = read(tmp_path / "telemetry")
    assert [w["fg"] for w in session["windows"]] == [True, False]
    assert session["windows"][1]["fps"] < 30  # the 15 FPS cap, not the foreground's 60


def test_the_directory_stays_bounded_and_keeps_the_newest(tmp_path):
    """However long a game runs, telemetry holds at most its budget plus the part being written.

    The oldest parts go first; the file being written is never deleted, and parts continue one
    session, each headed by the session's facts.
    """
    game = recording_game(tmp_path, window=0.0)  # a line per frame
    game.telemetry.file_limit = 3000
    game.telemetry.total_limit = 9000
    scene = Timed(0.6)
    game.run(scene, fps=500)

    files = sorted((tmp_path / "telemetry").glob("*.jsonl"))
    total = sum(p.stat().st_size for p in files)
    longest_line = max(len(line) + 1 for p in files for line in p.read_text().splitlines())
    assert max(scene.sizes) <= 9000 + 3000 + longest_line
    assert total <= 9000 + 3000 + longest_line
    parts = [int(p.stem.rsplit("-", 1)[1]) for p in files]
    assert parts[0] > 1, "the first parts were pruned"
    assert parts == list(range(parts[0], parts[0] + len(parts)))
    [session] = read(tmp_path / "telemetry")
    assert session["end"]["frames"] == scene.frames  # the newest part carries the session's end
    assert all(json.loads(p.read_text().splitlines()[0])["kind"] == "session" for p in files)


def test_only_the_loop_records(tmp_path, monkeypatch):
    """Ticking by hand writes nothing; the mock backend and SAGA2D_TELEMETRY=0 leave recording off."""
    game = Game("telemetry", backend="mock", save_dir=tmp_path / "saves")
    assert game.telemetry.enabled is False  # the mock backend's frames are not a player's
    game.telemetry.enabled = True
    game.push(Timed(10.0))
    for _ in range(20):
        game.tick(1 / 60)
    game.close()
    assert not (tmp_path / "telemetry").exists()

    monkeypatch.setenv("SAGA2D_TELEMETRY", "0")
    assert telemetry_module.enabled_by_default() is False
    monkeypatch.setenv("SAGA2D_TELEMETRY", "1")
    assert telemetry_module.enabled_by_default() is True


def test_the_summary_reads_a_data_directory(tmp_path, capsys):
    """``python -m saga2d.telemetry ~/.game`` finds the telemetry folder and describes each session."""
    game = recording_game(tmp_path)
    game.run(Timed(0.2))

    telemetry_module.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert "1 session(s)" in out
    assert "telemetry" in out and "fps: median" in out and '"frames_seen"' in out


def test_a_phase_outside_a_recording_costs_nothing_and_records_nothing(tmp_path):
    game = Game("telemetry", backend="mock", save_dir=tmp_path / "saves")
    with game.telemetry.phase("anything"):
        pass
    assert game.telemetry.phase("a") is game.telemetry.phase("b")
    game.close()


@pytest.mark.parametrize("fps", [0, float("nan")])
def test_a_bad_launch_opens_no_telemetry(tmp_path, fps):
    game = recording_game(tmp_path)
    with pytest.raises(ValueError, match="fps"):
        game.run(Timed(), fps=fps)
    assert not (tmp_path / "telemetry").exists()


def test_a_game_that_is_not_recording_reads_no_clock(monkeypatch):
    """Regression: Shardbound's CPU-budget tests replace ``time.process_time`` with a fake clock, and a
    ``Game`` read it once while setting up telemetry it would never record, which moved their clock.
    Off, telemetry costs nothing: no clock and no collector statistics, in the constructor or a tick."""
    import gc
    import time as time_module

    reads = []
    for name in ("perf_counter", "process_time"):
        real = getattr(time_module, name)
        monkeypatch.setattr(time_module, name, lambda real=real, name=name: reads.append(name) or real())
    monkeypatch.setattr(gc, "get_stats", lambda: reads.append("gc.get_stats") or [])
    game = Game("quiet", backend="mock")
    game.push(Timed(10.0))
    for _ in range(3):
        game.tick(1 / 60)
    game.close()
    monkeypatch.undo()
    assert reads == []
