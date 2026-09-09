"""AudioManager through the mock backend: pitch, channel volumes, mute, music lifecycle, silent policy."""

import wave
from pathlib import Path

import pytest

from saga2d import AssetManager, AssetNotFoundError, AudioManager, Game, Scene
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


def test_live_effects_follow_volume_and_mute_without_losing_relative_gain(audio: AudioManager, backend) -> None:
    """A sustained effect responds to settings immediately, preserving its own gain."""
    audio.play_sound("ping", volume=.8)
    audio.play_sound("ping", volume=.2)
    audio.set_volume("master", .5)
    audio.set_volume("sfx", .5)
    assert [sound["volume"] for sound in backend.sounds_playing.values()] == pytest.approx([.2, .05])
    audio.muted = True
    assert [sound["volume"] for sound in backend.sounds_playing.values()] == [0, 0]
    audio.set_volume("sfx", .4)
    audio.muted = False
    assert [sound["volume"] for sound in backend.sounds_playing.values()] == pytest.approx([.16, .04])
    assert [sound["volume"] for sound in backend.sounds_played] == [.8, .2]


def test_effect_settings_are_local_to_their_manager_and_channel(audio: AudioManager, backend, tmp_path: Path) -> None:
    other = AudioManager(backend, AssetManager(backend, base_path=tmp_path))
    audio.play_sound("ping", volume=.8)
    other.play_sound("ping", volume=.2)
    audio.play_music("theme")
    audio.set_volume("music", .3)
    assert [sound["volume"] for sound in backend.sounds_playing.values()] == [.8, .2]
    audio.set_volume("sfx", .5)
    assert backend.music_volume == .3
    audio.muted = True
    assert [sound["volume"] for sound in backend.sounds_playing.values()] == [0, .2]
    other.set_volume("master", .5)
    audio.muted = False
    assert [sound["volume"] for sound in backend.sounds_playing.values()] == pytest.approx([.4, .1])
    assert backend.music_volume == .3


def test_stopped_effects_stay_stopped_when_settings_change(audio: AudioManager, backend) -> None:
    audio.play_sound("ping")
    audio.play_music("theme")
    player = next(iter(backend.sounds_playing))
    backend.stop_sounds()
    assert backend.music_playing is not None
    backend.stop_player(player)
    audio.muted = True
    audio.set_volume("master", .5)
    audio.muted = False
    assert not backend.is_player_playing(player)
    assert backend.sounds_playing == {}
    audio.play_sound("ping")
    assert [sound["volume"] for sound in backend.sounds_playing.values()] == [.5]


@pytest.mark.parametrize("fail_on_exit", [False, True])
def test_game_run_releases_effects_and_music_on_exit(tmp_path: Path, monkeypatch, fail_on_exit: bool) -> None:
    monkeypatch.delenv("SAGA2D_HEADLESS", raising=False)
    write_wav(tmp_path / "sounds" / "ping.wav", seconds=10)
    write_wav(tmp_path / "music" / "theme.wav", seconds=10)
    game = Game("audio cleanup", backend="mock", asset_path=tmp_path)

    class Playing(Scene):
        def on_enter(self) -> None:
            game.audio.play_sound("ping")
            game.audio.play_music("theme")
            # A game's sound bank can own another manager on the same backend.
            other = AudioManager(game.backend, AssetManager(game.backend, base_path=tmp_path))
            other.play_sound("ping")
            other.play_music("theme")
            assert len(game.backend.sounds_playing) == 2
            game.quit()

        def on_exit(self) -> None:
            if fail_on_exit:
                raise RuntimeError("scene cleanup failed")

    if fail_on_exit:
        with pytest.raises(RuntimeError, match="scene cleanup failed"):
            game.run(Playing())
    else:
        game.run(Playing())
    assert game.backend.sounds_playing == {}
    assert game.backend.music_playing is None
    assert game.audio.music_name is None
    assert not game.backend.is_running


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


def test_crossfade_fades_the_old_track_out_while_the_new_fades_in(audio: AudioManager, backend, tmp_path: Path) -> None:
    write_wav(tmp_path / "music" / "battle.wav")
    audio.set_volume("music", 0.5)
    audio.play_music("theme")
    audio.play_music("battle", fade=1.0)
    assert audio.music_name == "battle"
    old, new = backend.music_players
    assert old["volume"] == pytest.approx(0.5) and new["volume"] == 0
    audio.update(0.5)
    old, new = backend.music_players
    assert old["volume"] == pytest.approx(0.25) and new["volume"] == pytest.approx(0.25)
    audio.set_volume("music", 1.0)  # a level change mid-fade keeps both tracks on their curves
    old, new = backend.music_players
    assert old["volume"] == pytest.approx(0.5) and new["volume"] == pytest.approx(0.5)
    audio.update(0.6)
    (new,) = backend.music_players
    assert new["volume"] == pytest.approx(1.0) and audio.music_name == "battle"
    with pytest.raises(ValueError):
        audio.play_music("theme", fade=-1)


def test_stop_music_with_a_fade_releases_the_player_once_silent(audio: AudioManager, backend) -> None:
    audio.play_music("theme")
    audio.stop_music(fade=2.0)
    assert audio.music_name is None and len(backend.music_players) == 1
    audio.update(1.0)
    assert backend.music_players[0]["volume"] == pytest.approx(0.5)
    audio.muted = True
    assert backend.music_players[0]["volume"] == 0
    audio.update(1.0)
    assert backend.music_players == [] and backend.music_playing is None
    audio.stop_music(fade=1.0)
    audio.update(1.0)


def test_a_track_that_plays_to_its_end_is_forgotten_on_update(audio: AudioManager, backend) -> None:
    audio.play_music("theme", loop=False)
    (player_id,) = list(backend._music_players)
    backend.stop_player(player_id)  # what the backend does when a non-looping source ends
    assert audio.music_name == "theme"
    audio.update(1 / 60)
    assert audio.music_name is None


def test_game_tick_advances_music_fades_and_plays_files_by_absolute_path(tmp_path: Path) -> None:
    elsewhere = tmp_path / "cache" / "music" / "vigil.wav"
    write_wav(elsewhere)
    write_wav(tmp_path / "assets" / "music" / "theme.wav")
    game = Game("fades", backend="mock", asset_path=tmp_path / "assets")
    try:
        game.audio.play_music("theme")
        game.audio.play_music(str(elsewhere), fade=1.0)
        game.tick(0.5)
        old, new = game.backend.music_players
        assert old["volume"] == pytest.approx(0.5) and new["volume"] == pytest.approx(0.5)
        assert new["handle"] == game.backend.load_music(str(elsewhere))
        game.tick(0.6)
        assert len(game.backend.music_players) == 1 and game.audio.music_name == str(elsewhere)
    finally:
        game._teardown()
