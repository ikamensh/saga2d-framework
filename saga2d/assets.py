"""Convention-based asset loading with caching.

::

    game.assets.image("sprites/knight")      # assets/images/sprites/knight.png
    game.assets.image_from_pil("glow", pil)  # procedural texture, cached by key
    game.assets.sound("hit")                 # assets/sounds/hit.wav
    game.assets.music("theme")               # assets/music/theme.ogg (streams)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from saga2d.backends.base import Backend, ImageHandle, SoundHandle

if TYPE_CHECKING:
    from PIL import Image


class AssetNotFoundError(FileNotFoundError):
    """The asset file does not exist; the message lists the paths tried."""


class AssetManager:
    _SOUND_EXTENSIONS = (".wav", ".ogg", ".mp3")
    _MUSIC_EXTENSIONS = (".ogg", ".wav", ".mp3")

    def __init__(self, backend: Backend, base_path: Path | str = Path("assets")) -> None:
        self._backend = backend
        self._base_path = Path(base_path)
        self._images: dict[str, ImageHandle] = {}
        self._frames: dict[str, list[str]] = {}
        self._sounds: dict[str, SoundHandle] = {}
        self._music_paths: dict[str, str] = {}

    @property
    def base_path(self) -> Path:
        return self._base_path

    def image(self, name: str) -> ImageHandle:
        """Load ``<base>/images/<name>.png`` (extension optional). Cached."""
        handle = self._images.get(name)
        if handle is None:
            handle = self._backend.load_image(str(self._resolve_image_path(name)))
            self._images[name] = handle
        return handle

    def image_from_pil(self, key: str, pil_image: "Image.Image") -> ImageHandle:
        """Register a procedurally generated RGBA image under *key*.

        Subsequent :meth:`image` calls with *key* return the same handle,
        so sprites can be created with the key like any file asset.
        """
        if key in self._images:
            return self._images[key]
        handle = self._backend.load_image_from_pil(pil_image.convert("RGBA"))
        self._images[key] = handle
        return handle

    def has_image(self, key: str) -> bool:
        return key in self._images

    def frames(self, prefix: str) -> list[str]:
        """Asset names for ``<prefix>_01.png``, ``<prefix>_02.png``, … sorted by number."""
        if prefix in self._frames:
            return self._frames[prefix]
        images_dir = self._base_path / "images"
        full = images_dir / prefix
        matches = sorted(full.parent.glob(full.name + "_*.png"), key=lambda p: int(p.stem.rsplit("_", 1)[-1]))
        if not matches:
            raise AssetNotFoundError(f"No animation frames for '{prefix}'. Looked for: {full.parent / (full.name + '_*.png')}")
        names = [str(m.relative_to(images_dir).with_suffix("")) for m in matches]
        self._frames[prefix] = names
        return names

    def sound(self, name: str) -> SoundHandle:
        if name not in self._sounds:
            path = self._resolve_audio_path(name, self._base_path / "sounds", self._SOUND_EXTENSIONS, "Sound")
            self._sounds[name] = self._backend.load_sound(str(path))
        return self._sounds[name]

    def music(self, name: str) -> SoundHandle:
        """A fresh streaming source (streams cannot be shared between players)."""
        if name not in self._music_paths:
            path = self._resolve_audio_path(name, self._base_path / "music", self._MUSIC_EXTENSIONS, "Music")
            self._music_paths[name] = str(path)
        return self._backend.load_music(self._music_paths[name])

    def _resolve_image_path(self, name: str) -> Path:
        filename = name if "." in Path(name).name else name + ".png"
        path = self._base_path / "images" / filename
        if not path.exists():
            raise AssetNotFoundError(f"Image asset '{name}' not found. Looked in: {path}")
        return path

    def _resolve_audio_path(self, name: str, base_dir: Path, extensions: tuple[str, ...], kind: str) -> Path:
        if "." in Path(name).name:
            candidates = [base_dir / name]
        else:
            candidates = [base_dir / (name + ext) for ext in extensions]
        for path in candidates:
            if path.exists():
                return path
        raise AssetNotFoundError(f"{kind} asset '{name}' not found. Looked in: {', '.join(map(str, candidates))}")
