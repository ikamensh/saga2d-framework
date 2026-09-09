"""AudioManager — sound effects and looping music with channel volumes and crossfades.

::

    game.audio.play_sound("hit", pitch=1.05)
    game.audio.play_music("theme")
    game.audio.play_music("battle", fade=2.0)   # the old track fades out as the new fades in
    game.audio.stop_music(fade=1.0)
    game.audio.set_volume("music", 0.5)     # channels: master, music, sfx
    game.audio.muted = True                 # silence; channel volumes are kept

``Game.tick`` calls ``update(dt)`` on the game's manager so fades advance every frame.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from saga2d.assets import AssetManager
from saga2d.backends.base import Backend, PlayerId


@dataclass
class _Fade:
    """A music player on its way from one gain to another; at gain 0 it is released."""

    player: PlayerId
    start: float
    end: float
    duration: float
    elapsed: float = 0.0

    @property
    def gain(self) -> float:
        x = min(1.0, self.elapsed / self.duration)
        return self.start + (self.end - self.start) * (0.5 - 0.5 * math.cos(math.pi * x))

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration


class AudioManager:
    """Independent channel settings that also affect effects already playing.

    The backend owns playback resources. This manager retains only opaque IDs
    and each effect's local gain, so master/SFX changes preserve their balance.
    """

    CHANNELS = ("master", "music", "sfx")

    def __init__(self, backend: Backend, assets: AssetManager) -> None:
        self._backend = backend
        self._assets = assets
        self._volumes: dict[str, float] = {name: 1.0 for name in self.CHANNELS}
        self._muted = False
        self._player: PlayerId | None = None
        self._music_name: str | None = None
        self._music_gain = 1.0
        self._fade_in: _Fade | None = None
        self._fading_out: list[_Fade] = []
        self._sounds: dict[PlayerId, float] = {}

    def set_volume(self, channel: str, level: float) -> None:
        self._check_channel(channel)
        if not math.isfinite(level):
            raise ValueError(f"Volume must be finite, got {level!r}")
        self._volumes[channel] = max(0.0, min(1.0, level))
        if channel in ("master", "music"):
            self._apply_music_volume()
        if channel in ("master", "sfx"):
            self._apply_sound_volume()

    def get_volume(self, channel: str) -> float:
        self._check_channel(channel)
        return self._volumes[channel]

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, value: bool) -> None:
        self._muted = bool(value)
        self._apply_music_volume()
        self._apply_sound_volume()

    @property
    def music_name(self) -> str | None:
        return self._music_name

    def play_sound(self, name: str, *, volume: float = 1.0, pitch: float = 1.0) -> None:
        """Play effect *name* once.  *pitch* 1.0 is nominal; 2.0 is an octave up."""
        if not (math.isfinite(pitch) and pitch > 0):
            raise ValueError(f"pitch must be a positive finite number, got {pitch!r}")
        handle = self._assets.sound(name)
        if self._muted:
            return
        self._prune_sounds()
        player = self._backend.play_sound(handle, volume=self._volumes["master"] * self._volumes["sfx"] * volume, pitch=pitch)
        self._sounds[player] = volume

    def play_music(self, name: str, *, loop: bool = True, fade: float = 0.0) -> None:
        """Start *name*.  With *fade* seconds the current track fades out while the new one
        fades in; otherwise the current track stops at once.  ``music_name`` is the new track
        immediately."""
        if not (math.isfinite(fade) and fade >= 0):
            raise ValueError(f"fade must be a nonnegative finite number of seconds, got {fade!r}")
        handle = self._assets.music(name)
        self._release_music(fade)
        self._music_gain = 0.0 if fade > 0 else 1.0
        self._fade_in = _Fade(None, 0.0, 1.0, fade) if fade > 0 else None
        self._player = self._backend.play_music(handle, loop=loop, volume=self._music_volume() * self._music_gain)
        self._music_name = name

    def stop_music(self, fade: float = 0.0) -> None:
        """Stop the current track, over *fade* seconds if given; idempotent."""
        if not (math.isfinite(fade) and fade >= 0):
            raise ValueError(f"fade must be a nonnegative finite number of seconds, got {fade!r}")
        self._release_music(fade)

    def update(self, dt: float) -> None:
        """Advance fades by *dt* seconds and forget a track that has played to its end."""
        if self._fade_in is not None and self._player is not None:
            self._fade_in.elapsed += dt
            self._music_gain = self._fade_in.gain
            self._backend.set_player_volume(self._player, self._music_volume() * self._music_gain)
            if self._fade_in.done:
                self._fade_in = None
        for fade in list(self._fading_out):
            fade.elapsed += dt
            if fade.done:
                self._backend.stop_player(fade.player)
                self._fading_out.remove(fade)
            else:
                self._backend.set_player_volume(fade.player, self._music_volume() * fade.gain)
        if self._player is not None and not self._backend.is_player_playing(self._player):
            self._player = None
            self._music_name = None
            self._fade_in = None

    def _release_music(self, fade: float) -> None:
        if self._player is None:
            return
        if fade > 0:
            self._fading_out.append(_Fade(self._player, self._music_gain, 0.0, fade))
        else:
            self._backend.stop_player(self._player)
        self._player = None
        self._music_name = None
        self._fade_in = None

    def _music_volume(self) -> float:
        return 0.0 if self._muted else self._volumes["master"] * self._volumes["music"]

    def _apply_music_volume(self) -> None:
        if self._player is not None:
            self._backend.set_player_volume(self._player, self._music_volume() * self._music_gain)
        for fade in self._fading_out:
            self._backend.set_player_volume(fade.player, self._music_volume() * fade.gain)

    def _prune_sounds(self) -> None:
        self._sounds = {
            player: volume for player, volume in self._sounds.items()
            if self._backend.is_player_playing(player)
        }

    def _apply_sound_volume(self) -> None:
        self._prune_sounds()
        gain = 0.0 if self._muted else self._volumes["master"] * self._volumes["sfx"]
        for player, volume in self._sounds.items():
            self._backend.set_player_volume(player, gain * volume)

    def _check_channel(self, channel: str) -> None:
        if channel not in self._volumes:
            raise KeyError(f"Unknown audio channel {channel!r}. Valid channels: {list(self.CHANNELS)}")
