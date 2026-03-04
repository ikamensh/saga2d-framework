"""Convention-based asset loading with caching and @2x variant support.

The :class:`AssetManager` resolves asset names to file paths under a
configurable base directory, loads them through the backend, and caches
the returned handles so repeated requests for the same asset are free.

Usage (from game code)::

    img = game.assets.image("sprites/knight")   # loads assets/images/sprites/knight.png
    img2 = game.assets.image("sprites/knight")  # returns cached handle

Resolution variant support::

    # If scale_factor >= 1.5 and "knight@2x.png" exists alongside "knight.png",
    # the @2x variant is loaded automatically.

The asset manager is owned by :class:`~saga2d.game.Game` and exposed as
``game.assets``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from saga2d.backends.base import Backend, ImageHandle, SoundHandle

if TYPE_CHECKING:
    from saga2d.rendering.color_swap import ColorSwap


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class AssetNotFoundError(FileNotFoundError):
    """Raised when an asset file cannot be found.

    The message includes the attempted path(s) so the developer can see
    exactly what was looked up.
    """


# ---------------------------------------------------------------------------
# AssetManager
# ---------------------------------------------------------------------------


class AssetManager:
    """Convention-based asset loader with caching.

    Parameters:
        backend:      The backend instance (must implement ``load_image``).
        base_path:    Root directory for assets (e.g. ``Path("assets")``).
                      Resolved relative to CWD if not absolute.
        scale_factor: Display scale factor.  When ``>= 1.5``, the manager
                      prefers ``@2x`` image variants if they exist on disk.
    """

    def __init__(
        self,
        backend: Backend,
        base_path: Path | str = Path("assets"),
        *,
        scale_factor: float = 1.0,
    ) -> None:
        self._backend = backend
        self._base_path = Path(base_path)
        self._scale_factor = scale_factor
        self._image_cache: dict[str, ImageHandle] = {}
        self._swapped_cache: dict[
            tuple[str, tuple[object, ...]], ImageHandle
        ] = {}  # (name, color_swap.cache_key()) -> handle
        self._frames_cache: dict[str, list[str]] = {}
        self._sound_cache: dict[str, SoundHandle] = {}
        # Music paths are cached (not handles) because streaming sources
        # cannot be reused across players in pyglet.
        self._music_path_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Image loading
    # ------------------------------------------------------------------

    def image(self, name: str) -> ImageHandle:
        """Load an image by convention name and return an opaque handle.

        *name* is resolved under ``<base_path>/images/``.  If *name* has
        no file extension, ``.png`` is appended automatically.

        Examples::

            game.assets.image("sprites/knight")
            # → <base_path>/images/sprites/knight.png

            game.assets.image("backgrounds/forest.jpg")
            # → <base_path>/images/backgrounds/forest.jpg

        On high-DPI displays (``scale_factor >= 1.5``), the manager first
        checks for a ``@2x`` variant (e.g. ``knight@2x.png``).  If found
        it is loaded instead; otherwise the base file is used.

        Returns:
            An opaque ``ImageHandle``.

        Raises:
            AssetNotFoundError: If the file does not exist.
        """
        if name in self._image_cache:
            return self._image_cache[name]

        path = self._resolve_image_path(name)
        handle = self._backend.load_image(str(path))
        self._image_cache[name] = handle
        return handle

    def image_swapped(self, name: str, color_swap: "ColorSwap") -> ImageHandle:
        """Load an image with color replacement applied. Cached per (name, swap).

        Returns:
            An opaque ImageHandle.

        Raises:
            AssetNotFoundError: If the image file does not exist.
        """
        key = (name, color_swap.cache_key())
        if key in self._swapped_cache:
            return self._swapped_cache[key]
        path = self._resolve_image_path(name)
        pil_img = color_swap.apply(str(path))
        handle = self._backend.load_image_from_pil(pil_img)
        self._swapped_cache[key] = handle
        return handle

    def _resolve_image_path(self, name: str) -> Path:
        """Resolve asset name to a file path. Handles @2x variants.

        Raises:
            AssetNotFoundError: If the file does not exist.
        """
        if "." not in Path(name).name:
            name_with_ext = name + ".png"
        else:
            name_with_ext = name

        images_dir = self._base_path / "images"
        base_path = images_dir / name_with_ext

        if self._scale_factor >= 1.5:
            hi_res_path = _make_2x_path(base_path)
            if hi_res_path.exists():
                return hi_res_path

        if base_path.exists():
            return base_path

        tried = [str(base_path)]
        if self._scale_factor >= 1.5:
            tried.insert(0, str(_make_2x_path(base_path)))
        raise AssetNotFoundError(
            f"Image asset '{name}' not found.  Looked in: {', '.join(tried)}"
        )

    # ------------------------------------------------------------------
    # Animation frames
    # ------------------------------------------------------------------

    def frames(self, prefix: str) -> list[str]:
        """Discover numbered animation frames by prefix.

        Finds files matching ``{prefix}_01.png``, ``{prefix}_02.png``, etc.
        under ``<base_path>/images/``.  Returns a list of asset names
        (suitable for :meth:`image`) sorted by frame number.  Result is
        cached.

        Example::

            game.assets.frames("sprites/knight_walk")
            # → ["sprites/knight_walk_01", "sprites/knight_walk_02", ...]

        Raises:
            AssetNotFoundError: If no matching files exist.
        """
        if prefix in self._frames_cache:
            return self._frames_cache[prefix]

        images_dir = self._base_path / "images"
        full_prefix = images_dir / prefix
        pattern = full_prefix.name + "_*.png"
        matches = sorted(
            full_prefix.parent.glob(pattern),
            key=lambda p: int(p.stem.rsplit("_", 1)[-1]),
        )

        if not matches:
            raise AssetNotFoundError(
                f"No animation frames for '{prefix}'.  "
                f"Looked for: {full_prefix.parent / pattern}"
            )

        names = [str(m.relative_to(images_dir).with_suffix("")) for m in matches]
        self._frames_cache[prefix] = names
        return names

    # ------------------------------------------------------------------
    # Sound loading
    # ------------------------------------------------------------------

    #: Extension search order for sound effects (WAV preferred — short,
    #: uncompressed, low latency).
    _SOUND_EXTENSIONS: tuple[str, ...] = (".wav", ".ogg", ".mp3")

    #: Extension search order for music tracks (OGG preferred — compressed,
    #: streaming-friendly, patent-free).
    _MUSIC_EXTENSIONS: tuple[str, ...] = (".ogg", ".wav", ".mp3")

    def sound(self, name: str) -> SoundHandle:
        """Load a sound effect by name (cached).

        Resolution: ``assets/sounds/{name}.wav``, then ``.ogg``, then
        ``.mp3``.  If *name* contains a ``.`` it is used as-is.

        Returns:
            An opaque ``SoundHandle``.

        Raises:
            AssetNotFoundError: If the file does not exist.
        """
        if name in self._sound_cache:
            return self._sound_cache[name]

        path = self._resolve_audio_path(
            name,
            self._base_path / "sounds",
            self._SOUND_EXTENSIONS,
            "Sound",
        )
        handle = self._backend.load_sound(str(path))
        self._sound_cache[name] = handle
        return handle

    def music(self, name: str) -> SoundHandle:
        """Load a music track by name (streaming).

        Returns a **fresh** streaming source each time because pyglet
        streaming sources cannot be reused across players.  The resolved
        file *path* is cached so repeated calls skip the filesystem probe.

        Resolution: ``assets/music/{name}.ogg``, then ``.wav``, then
        ``.mp3``.  If *name* contains a ``.`` it is used as-is.

        Returns:
            An opaque ``SoundHandle`` (streaming).

        Raises:
            AssetNotFoundError: If the file does not exist.
        """
        if name not in self._music_path_cache:
            path = self._resolve_audio_path(
                name,
                self._base_path / "music",
                self._MUSIC_EXTENSIONS,
                "Music",
            )
            self._music_path_cache[name] = str(path)

        return self._backend.load_music(self._music_path_cache[name])

    def _resolve_audio_path(
        self,
        name: str,
        base_dir: Path,
        extensions: tuple[str, ...],
        kind: str,
    ) -> Path:
        """Try *extensions* in order under *base_dir* and return the first hit.

        If *name* already contains a file extension (a ``.`` in the final
        component), use it directly without trying alternatives.

        Raises:
            AssetNotFoundError: If no matching file is found.
        """
        # If the name already has an extension, use it directly.
        if "." in Path(name).name:
            path = base_dir / name
            if path.exists():
                return path
            raise AssetNotFoundError(
                f"{kind} asset '{name}' not found.  Looked in: {path}"
            )

        tried: list[str] = []
        for ext in extensions:
            path = base_dir / (name + ext)
            tried.append(str(path))
            if path.exists():
                return path

        raise AssetNotFoundError(
            f"{kind} asset '{name}' not found.  Looked in: {', '.join(tried)}"
        )


def _make_2x_path(path: Path) -> Path:
    """Insert ``@2x`` before the file extension.

    ``sprites/knight.png`` → ``sprites/knight@2x.png``
    """
    return path.with_stem(path.stem + "@2x")
