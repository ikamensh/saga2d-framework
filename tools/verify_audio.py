"""Verify real pyglet gain updates, natural completion and shutdown release.

    uv run python tools/verify_audio.py            # real playback, silent driver
    uv run python tools/verify_audio.py --audible  # optional brief, quiet tone

The hidden window never takes focus. Native player inspection here checks the
adapter's resource boundary; framework tests exercise public mock observations.
"""

import argparse
import math
import os
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def write_tone(path: Path, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"".join(
            struct.pack("<h", int(2000 * math.sin(2 * math.pi * 440 * i / 8000)))
            for i in range(int(8000 * seconds))
        ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audible", action="store_true")
    args = parser.parse_args()
    if os.environ.get("SAGA2D_HEADLESS", "").strip() not in ("", "0"):
        parser.error("unset SAGA2D_HEADLESS for this bounded Game.run check; its window remains hidden")
    os.environ["SAGA2D_SILENT"] = "0" if args.audible else "1"

    from saga2d import AssetManager, AudioManager, Game, Scene

    with TemporaryDirectory(prefix="saga2d-audio-") as directory:
        root = Path(directory)
        write_tone(root / "sounds" / "sustained.wav", 2)
        write_tone(root / "sounds" / "short.wav", .04)
        write_tone(root / "music" / "theme.wav", 2)
        game = Game("Audio verification", backend="pyglet", resolution=(64, 64),
                    visible=False, asset_path=root)
        backend = game.backend
        native_players = []

        class Check(Scene):
            def on_enter(self):
                self.started = time.monotonic()
                game.audio.set_volume("master", .25)
                game.audio.play_sound("sustained", volume=.8)
                self.effect = next(iter(backend._players.values()))
                game.audio.set_volume("music", .1)
                game.audio.play_music("theme")
                other = AudioManager(backend, AssetManager(backend, base_path=root))
                other.play_sound("sustained", volume=.15)
                self.independent = list(backend._players.values())[-1]
                other.set_volume("music", .05)
                other.play_music("theme")
                self.short = backend.play_sound(
                    backend.load_sound(str(root / "sounds" / "short.wav")), volume=.1)
                self.short_music = backend.play_music(
                    backend.load_music(str(root / "sounds" / "short.wav")), loop=False, volume=.05)
                native_players.extend(backend._players.values())
                self.checked = False

            def update(self, dt):
                elapsed = time.monotonic() - self.started
                if elapsed > 3:
                    raise TimeoutError("the short effect did not finish and release within 3 seconds")
                if not self.checked:
                    assert math.isclose(self.effect.volume, .2)
                    game.audio.set_volume("master", .5)
                    assert math.isclose(self.effect.volume, .4)
                    game.audio.set_volume("sfx", .5)
                    assert math.isclose(self.effect.volume, .2)
                    game.audio.muted = True
                    assert self.effect.volume == 0
                    game.audio.set_volume("sfx", .2)
                    assert self.effect.volume == 0
                    game.audio.muted = False
                    assert math.isclose(self.effect.volume, .08)
                    assert math.isclose(self.independent.volume, .15)
                    self.checked = True
                ended = not any(backend.is_player_playing(player) for player in (self.short, self.short_music))
                if elapsed >= .2 and ended:
                    assert self.short not in backend._players and self.short_music not in backend._players, "completed player retained by backend"
                    assert self.effect.playing, "sustained effect ended before the cleanup check"
                    game.quit()

        game.run(Check())
        assert not backend._players and not backend._sound_players
        assert all(not player.playing and player._audio_player is None for player in native_players)
        assert game.audio.music_name is None
        assert backend.window is None
    mode = "default audio driver" if args.audible else "silent driver"
    print(f"Audio verification passed ({mode}): live gain/mute, independent managers, EOS release, Game.run cleanup.")


if __name__ == "__main__":
    main()
