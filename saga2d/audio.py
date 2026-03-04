"""Audio system — channels, music playback, crossfade, sound pools.

:class:`AudioManager` sits between game code and the backend audio protocol.
Game code does ``game.audio.play_sound("sword_hit")``, never touches the
backend directly.

**Key design principle:** AudioManager is pure framework logic (volume math,
pool selection, crossfade orchestration).  All actual playback goes through
the backend protocol.  This mirrors how Camera is pure math and Sprite
delegates to the backend for rendering.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from saga2d.assets import AssetManager, AssetNotFoundError
from saga2d.backends.base import Backend, MusicPlayerId

if TYPE_CHECKING:
    from saga2d.util.tween import TweenManager


# ---------------------------------------------------------------------------
# Crossfade tween proxy
# ---------------------------------------------------------------------------


class _CrossfadeProxy:
    """Tween target that forwards volume changes to backend players.

    The tween system sets ``old_volume`` and ``new_volume`` each frame.
    The proxy multiplies by ``master * music`` channel volume before
    passing to the backend.
    """

    def __init__(
        self,
        audio_mgr: AudioManager,
        old_player_id: MusicPlayerId,
        new_player_id: MusicPlayerId,
        old_base: float,
    ) -> None:
        self._audio = audio_mgr
        self._old_player = old_player_id
        self._new_player = new_player_id
        self._old_base = old_base
        self._old_vol = old_base
        self._new_vol = 0.0

    @property
    def old_volume(self) -> float:
        return self._old_vol

    @old_volume.setter
    def old_volume(self, val: float) -> None:
        self._old_vol = val
        effective = self._audio._volumes["master"] * self._audio._volumes["music"] * val
        self._audio._backend.set_player_volume(self._old_player, effective)

    @property
    def new_volume(self) -> float:
        return self._new_vol

    @new_volume.setter
    def new_volume(self, val: float) -> None:
        self._new_vol = val
        effective = self._audio._volumes["master"] * self._audio._volumes["music"] * val
        self._audio._backend.set_player_volume(self._new_player, effective)
        # Keep AudioManager's tracked base volume in sync with the new player.
        self._audio._current_player_base_volume = val


# ---------------------------------------------------------------------------
# AudioManager
# ---------------------------------------------------------------------------


class AudioManager:
    """Framework-level audio system.  Owned by Game as ``game.audio``.

    Manages channels, volume hierarchy, music playback with crossfade,
    sound effects, and sound pools.

    Parameters:
        backend: The backend instance (must implement the audio protocol).
        assets:  The :class:`~saga2d.assets.AssetManager` for loading
                 sound/music assets by name.
    """

    def __init__(self, backend: Backend, assets: AssetManager) -> None:
        self._backend = backend
        self._assets = assets

        # Channel volumes (0.0–1.0)
        self._volumes: dict[str, float] = {
            "master": 1.0,
            "music": 1.0,
            "sfx": 1.0,
            "ui": 1.0,
        }

        # Current music state
        self._current_player_id: MusicPlayerId | None = None
        self._current_music_name: str | None = None
        self._current_player_base_volume: float = 1.0  # pre-channel volume

        # Crossfade state
        self._crossfade_old_player: MusicPlayerId | None = None
        self._crossfade_tween_ids: list[int] = []
        self._tween_manager: TweenManager | None = (
            None  # set when crossfade tweens are created
        )

        # Sound pools
        self._pools: dict[str, list[str]] = {}  # pool_name -> [sound_names]
        self._pool_last: dict[str, int] = {}  # pool_name -> last played index

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    def set_volume(self, channel: str, level: float) -> None:
        """Set the volume for *channel* (clamped to 0.0–1.0).

        Recognised channels: ``"master"``, ``"music"``, ``"sfx"``, ``"ui"``.

        Changing ``"master"`` or ``"music"`` immediately re-applies to the
        current music player (if any).  Sound effects are fire-and-forget —
        volume changes only affect future plays.

        Raises:
            KeyError: If *channel* is not a recognised channel name.
        """
        if channel not in self._volumes:
            raise KeyError(
                f"Unknown audio channel {channel!r}. "
                f"Valid channels: {sorted(self._volumes)}"
            )
        self._volumes[channel] = max(0.0, min(1.0, level))

        # Re-apply to current music player if relevant.
        if channel in ("master", "music") and self._current_player_id is not None:
            effective = (
                self._volumes["master"]
                * self._volumes["music"]
                * self._current_player_base_volume
            )
            self._backend.set_player_volume(self._current_player_id, effective)

    def get_volume(self, channel: str) -> float:
        """Return the current volume for *channel*.

        Raises:
            KeyError: If *channel* is not a recognised channel name.
        """
        if channel not in self._volumes:
            raise KeyError(
                f"Unknown audio channel {channel!r}. "
                f"Valid channels: {sorted(self._volumes)}"
            )
        return self._volumes[channel]

    # ------------------------------------------------------------------
    # Sound effects
    # ------------------------------------------------------------------

    def play_sound(
        self, name: str, *, channel: str = "sfx", optional: bool = False
    ) -> None:
        """Play a sound effect by name (fire-and-forget).

        The effective volume is ``master * channel``.

        Parameters:
            name:    Sound name resolved via
                     :meth:`AssetManager.sound` (no extension needed).
            channel: Volume channel — ``"sfx"`` (default) or ``"ui"``.
            optional: If True and the asset is missing, return None instead of
                      raising :exc:`AssetNotFoundError`.
        """
        try:
            handle = self._assets.sound(name)
        except AssetNotFoundError:
            if optional:
                return None
            raise
        if channel not in self._volumes:
            raise KeyError(
                f"Unknown audio channel {channel!r}. "
                f"Valid channels: {sorted(self._volumes)}"
            )
        effective = self._volumes["master"] * self._volumes[channel]
        self._backend.play_sound(handle, volume=effective)

    # ------------------------------------------------------------------
    # Music
    # ------------------------------------------------------------------

    def play_music(
        self, name: str, *, loop: bool = True, optional: bool = False
    ) -> None:
        """Stop any current music and start playing *name*.

        No crossfade — immediate switch.  Use :meth:`crossfade_music` for
        smooth transitions.

        Parameters:
            optional: If True and the asset is missing, return None instead of
                      raising :exc:`AssetNotFoundError`.
        """
        self.stop_music()

        try:
            handle = self._assets.music(name)
        except AssetNotFoundError:
            if optional:
                return None
            raise
        effective = self._volumes["master"] * self._volumes["music"]
        player_id = self._backend.play_music(handle, loop=loop, volume=effective)

        self._current_player_id = player_id
        self._current_music_name = name
        self._current_player_base_volume = 1.0

    def stop_music(self) -> None:
        """Stop the current music track."""
        self._cancel_crossfade()
        if self._current_player_id is not None:
            self._backend.stop_player(self._current_player_id)
            self._current_player_id = None
            self._current_music_name = None

    def crossfade_music(
        self,
        name: str,
        duration: float = 1.0,
        *,
        loop: bool = True,
    ) -> None:
        """Crossfade from current music to *name* over *duration* seconds.

        If no music is playing, equivalent to :meth:`play_music`.
        If the same track is already playing, no-op.
        """
        if self._current_music_name == name:
            return
        if self._current_player_id is None:
            self.play_music(name, loop=loop)
            return

        # Cancel any in-progress crossfade first.
        self._cancel_crossfade()

        # The current player becomes the "old" player (fading out).
        old_player = self._current_player_id
        old_base_volume = self._current_player_base_volume

        # Create the new player (fading in), start at volume 0.
        handle = self._assets.music(name)
        new_player = self._backend.play_music(handle, loop=loop, volume=0.0)

        # Update current state to the new player.
        self._current_player_id = new_player
        self._current_music_name = name
        self._current_player_base_volume = 0.0

        # Store old player for cleanup.
        self._crossfade_old_player = old_player

        # Use a proxy object for tweening (tween system sets attributes).
        fade = _CrossfadeProxy(self, old_player, new_player, old_base_volume)

        from saga2d.util import tween as tween_mod
        from saga2d.util.tween import Ease, tween

        # Capture the instance tween manager so _cancel_crossfade doesn't
        # rely on the module-level global.
        self._tween_manager = tween_mod._tween_manager

        # Tween old volume from current base → 0.0.
        tid_out = tween(
            fade,
            "old_volume",
            old_base_volume,
            0.0,
            duration,
            ease=Ease.LINEAR,
        )
        # Tween new volume from 0.0 → 1.0; on_complete cleans up old player.
        tid_in = tween(
            fade,
            "new_volume",
            0.0,
            1.0,
            duration,
            ease=Ease.LINEAR,
            on_complete=lambda: self._finish_crossfade(old_player),
        )
        self._crossfade_tween_ids = [tid_out, tid_in]

    # ------------------------------------------------------------------
    # Sound pools
    # ------------------------------------------------------------------

    def register_pool(self, name: str, sound_names: list[str]) -> None:
        """Register a named pool of sounds for randomised playback.

        Example::

            game.audio.register_pool("knight_ack",
                ["knight_ack_01", "knight_ack_02", "knight_ack_03"])
        """
        self._pools[name] = list(sound_names)
        self._pool_last[name] = -1  # no previous play

    def play_pool(self, name: str) -> None:
        """Play a random sound from the named pool.

        Avoids immediate repetition: if the pool has N > 1 sounds, the
        same sound won't play twice in a row.

        Raises:
            KeyError: If *name* is not a registered pool.
        """
        sounds = self._pools[name]
        if not sounds:
            return
        if len(sounds) == 1:
            idx = 0
        else:
            last = self._pool_last[name]
            # Pick from all indices except the last-played one.
            candidates = [i for i in range(len(sounds)) if i != last]
            idx = random.choice(candidates)

        self._pool_last[name] = idx
        self.play_sound(sounds[idx])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _finish_crossfade(self, old_player_id: MusicPlayerId) -> None:
        """Called when crossfade completes.  Stop the old player."""
        self._backend.stop_player(old_player_id)
        self._crossfade_old_player = None
        self._crossfade_tween_ids.clear()

    def _cancel_crossfade(self) -> None:
        """Cancel an in-progress crossfade.  Stop the old player immediately."""
        mgr = self._tween_manager
        if mgr is not None:
            for tid in self._crossfade_tween_ids:
                mgr.cancel(tid)
        self._crossfade_tween_ids.clear()

        if self._crossfade_old_player is not None:
            self._backend.stop_player(self._crossfade_old_player)
            self._crossfade_old_player = None

    def _teardown(self) -> None:
        """Stop all music and crossfades.  Called by Game._teardown on shutdown."""
        self.stop_music()
