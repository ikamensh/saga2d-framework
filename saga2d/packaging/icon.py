"""The icon a built game carries: the game's picture, or the engine's mark, in each platform's shape and format.

A game names a square PNG painted to the edges (``GamePackage.icon``); the
build gives it the platform's outline and writes the ``.ico`` the Windows
executable and installer embed or the ``.icns`` the Mac bundle holds.
``carried`` is the check ``verify`` runs on the built artifact.
"""
from __future__ import annotations

from pathlib import Path
import plistlib
import struct

from PIL import Image, ImageChops, ImageDraw, ImageFilter

DEFAULT = Path(__file__).resolve().parents[1] / "assets" / "icon.png"  # shipped with the engine: a game also wears it while it runs
SIDE = 1024                                    # the smallest picture a game may supply, and the master's size
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_SIZES = (32, 64, 128, 256, 512, 1024)     # what Pillow's writer stores
FORMATS = {"Windows": "ico", "Darwin": "icns"}  # other systems have no icon inside the executable
# macOS draws app icons on a 1024 grid: an 824 rounded square with its shadow
# inside a clear margin.  Windows has no grid; a little rounding suits its shell.
MAC_TILE, MAC_RADIUS, WINDOWS_RADIUS = 824, 185, 150
OVERSAMPLE = 4


def load(path: Path) -> Image.Image:
    """The game's picture, refused unless it is square and at least ``SIDE`` pixels."""
    with Image.open(path) as image:
        picture = image.convert("RGBA")
    if picture.width != picture.height or picture.width < SIDE:
        raise ValueError(f"An icon is a square picture of at least {SIDE} px; {path} is {picture.width}x{picture.height}")
    return picture


def rounded(side: int, radius: int) -> Image.Image:
    mask = Image.new("L", (side * OVERSAMPLE, side * OVERSAMPLE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side * OVERSAMPLE - 1, side * OVERSAMPLE - 1), radius * OVERSAMPLE, fill=255)
    return mask.resize((side, side), Image.Resampling.LANCZOS)


def shaped(picture: Image.Image, system: str) -> Image.Image:
    """The ``SIDE`` px master in ``system``'s outline; the picture itself where a desktop shapes nothing."""
    if system not in FORMATS:
        return picture
    if system == "Windows":
        tile = picture.resize((SIDE, SIDE), Image.Resampling.LANCZOS)
        tile.putalpha(ImageChops.multiply(tile.getchannel("A"), rounded(SIDE, WINDOWS_RADIUS)))
        return tile
    tile = picture.resize((MAC_TILE, MAC_TILE), Image.Resampling.LANCZOS)
    tile.putalpha(ImageChops.multiply(tile.getchannel("A"), rounded(MAC_TILE, MAC_RADIUS)))
    edge = (SIDE - MAC_TILE) // 2
    master = Image.new("RGBA", (SIDE, SIDE), (0, 0, 0, 0))
    shadow = Image.new("L", (SIDE, SIDE), 0)
    shadow.paste(tile.getchannel("A").point(lambda value: value // 2), (edge, edge + 12))
    master.putalpha(shadow.filter(ImageFilter.GaussianBlur(14)))
    master.alpha_composite(tile, (edge, edge))
    return master


def write(picture: Path, directory: Path, system: str) -> Path | None:
    """Convert ``picture`` for ``system`` into ``directory``; None where executables hold no icon."""
    if system not in FORMATS:
        return None
    master = shaped(load(picture), system)
    target = directory / f"icon.{FORMATS[system]}"
    if system == "Windows":
        # Bitmap entries: every reader of .ico takes them, which is not true of PNG ones below 256 px.
        master.save(target, format="ICO", sizes=[(size, size) for size in ICO_SIZES], bitmap_format="bmp")
    else:
        master.save(target, format="ICNS", append_images=[master.resize((size, size), Image.Resampling.LANCZOS)
                                                          for size in ICNS_SIZES if size != SIDE])
    return target


def ico_images(data: bytes) -> list[bytes]:
    """The stored images of an ``.ico`` file, as the bytes an executable's icon resources repeat."""
    reserved, kind, count = struct.unpack_from("<HHH", data)
    if (reserved, kind) != (0, 1) or not count:
        raise ValueError("Not an .ico file")
    images = []
    for index in range(count):
        size, offset = struct.unpack_from("<II", data, 6 + 16 * index + 8)
        images.append(data[offset:offset + size])
    return images


def carried(artifact: Path, icon: Path) -> None:
    """Fail unless ``artifact`` (a Windows executable or a Mac bundle) holds exactly ``icon``."""
    if icon.suffix == ".ico":
        executable = artifact.read_bytes()
        missing = [index for index, image in enumerate(ico_images(icon.read_bytes())) if image not in executable]
        if missing:
            raise AssertionError(f"{artifact} does not carry images {missing} of {icon}")
    else:
        info = plistlib.loads((artifact / "Contents" / "Info.plist").read_bytes())
        shipped = artifact / "Contents" / "Resources" / info["CFBundleIconFile"]
        if shipped.read_bytes() != icon.read_bytes():
            raise AssertionError(f"{shipped} differs from {icon}")
