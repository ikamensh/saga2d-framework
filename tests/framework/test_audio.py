"""AudioManager through the mock backend: pitch, channel volumes, mute, music lifecycle, silent policy."""

import wave
from pathlib import Path

import pytest

from saga2d import AssetManager, AssetNotFoundError, AudioManager, Game
from saga2d.backends.base import silent_audio


def write_wav(path: Path, seconds: float = 0.1) -> None:
    """A minimal valid 16-bit PCM file (silence)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * int(8000 * seconds))


@pytest.fixture
def audio(game: Game, tmp_path: Path) -> AudioManager:
    write_wav(tmp_path / "sounds" / "ping.wav")
    write_wav(tmp_path / "music" / "theme.wav")
    return AudioManager(game.backend, AssetManager(game.backend, base_path=tmp_path))


def test_play_sound_passes_pitch_and_channel_volumes_to_the_backend(audio: AudioManager, backend, tmp_path: Path) -> None:
    audio.set_volume("master", 0.5)
    audio.set_volume("sfx", 0.5)
    audio.play_sound("ping", volume=0.8, pitch=1.2)
    played = backend.sounds_played[-1]
    assert played["handle"] == backend.load_sound(str(tmp_path / "sounds" / "ping.wav"))
    assert played["volume"] == pytest.approx(0.2)
    assert played["pitch"] == 1.2


def test_pitch_defaults_to_nominal_and_must_be_positive_and_finite(audio: AudioManager, backend) -> None:
    audio.play_sound("ping")
    assert backend.sounds_played[-1]["pitch"] == 1.0
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            audio.play_sound("ping", pitch=bad)
    assert len(backend.sounds_played) == 1


def test_muted_skips_playback_but_still_reports_a_missing_asset(audio: AudioManager, backend) -> None:
    audio.muted = True
    audio.play_sound("ping")
    assert backend.sounds_played == []
    with pytest.raises(AssetNotFoundError):
        audio.play_sound("missing")
    audio.muted = False
    audio.play_sound("ping")
    assert len(backend.sounds_played) == 1


def test_mute_silences_running_music_and_unmute_restores_its_volume(audio: AudioManager, backend) -> None:
    audio.set_volume("music", 0.6)
    audio.play_music("theme")
    assert backend.music_volume == pytest.approx(0.6)
    audio.muted = True
    assert backend.music_volume == 0.0 and audio.music_name == "theme"
    audio.set_volume("master", 0.5)
    assert backend.music_volume == 0.0
    audio.muted = False
    assert backend.music_volume == pytest.approx(0.3)


def test_music_starts_stops_and_stop_is_idempotent(audio: AudioManager, backend) -> None:
    audio.play_music("theme")
    assert backend.music_playing is not None and audio.music_name == "theme"
    audio.stop_music()
    assert backend.music_playing is None and audio.music_name is None
    audio.stop_music()


def test_channels_are_validated_and_volumes_clamped(audio: AudioManager) -> None:
    with pytest.raises(KeyError):
        audio.set_volume("voice", 1.0)
    with pytest.raises(ValueError):
        audio.set_volume("sfx", float("nan"))
    audio.set_volume("sfx", 3.0)
    assert audio.get_volume("sfx") == 1.0
    audio.set_volume("sfx", -1.0)
    assert audio.get_volume("sfx") == 0.0


def test_silent_audio_policy_reads_both_environment_variables() -> None:
    assert not silent_audio({})
    assert not silent_audio({"SAGA2D_SILENT": "0", "SAGA2D_HEADLESS": " "})
    assert silent_audio({"SAGA2D_SILENT": "1"})
    assert silent_audio({"SAGA2D_HEADLESS": "yes"})
