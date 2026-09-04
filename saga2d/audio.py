"""AudioManager — sound effects and looping music with channel volumes.

::

    game.audio.play_sound("hit", pitch=1.05)
    game.audio.play_music("theme")
    game.audio.set_volume("music", 0.5)     # channels: master, music, sfx
    game.audio.muted = True                 # silence; channel volumes are kept
"""

from __future__ import annotations

import math

from saga2d.assets import AssetManager
from saga2d.backends.base import Backend, MusicPlayerId


class AudioManager:
    CHANNELS = ("master", "music", "sfx")

    def __init__(self, backend: Backend, assets: AssetManager) -> None:
        self._backend = backend
        self._assets = assets
        self._volumes: dict[str, float] = {name: 1.0 for name in self.CHANNELS}
        self._muted = False
        self._player: MusicPlayerId | None = None
        self._music_name: str | None = None

    def set_volume(self, channel: str, level: float) -> None:
        self._check_channel(channel)
        if not math.isfinite(level):
            raise ValueError(f"Volume must be finite, got {level!r}")
        self._volumes[channel] = max(0.0, min(1.0, level))
        if channel in ("master", "music"):
            self._apply_music_volume()

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
        self._backend.play_sound(handle, volume=self._volumes["master"] * self._volumes["sfx"] * volume, pitch=pitch)

    def play_music(self, name: str, *, loop: bool = True) -> None:
        """Stop any current track and start *name*."""
        self.stop_music()
        handle = self._assets.music(name)
        self._player = self._backend.play_music(handle, loop=loop, volume=self._music_volume())
        self._music_name = name

    def stop_music(self) -> None:
        if self._player is not None:
            self._backend.stop_player(self._player)
            self._player = None
            self._music_name = None

    def _music_volume(self) -> float:
        return 0.0 if self._muted else self._volumes["master"] * self._volumes["music"]

    def _apply_music_volume(self) -> None:
        if self._player is not None:
            self._backend.set_player_volume(self._player, self._music_volume())

    def _check_channel(self, channel: str) -> None:
        if channel not in self._volumes:
            raise KeyError(f"Unknown audio channel {channel!r}. Valid channels: {list(self.CHANNELS)}")
