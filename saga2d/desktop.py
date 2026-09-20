"""What the desktop makes of a running game: the icon it draws for it, and the name beside it.

A built game carries both in its bundle, but a game started from a checkout is
a bare Python process: macOS draws a blank page called ``python3.13`` in the
Dock, and Windows the interpreter's own icon in the taskbar. :func:`pictures`
shapes a game's icon exactly as its built app wears it
(:mod:`saga2d.packaging.icon`), for the backend to hand the window;
:func:`call_it` tells macOS the game's name.

:class:`~saga2d.game.Game` does both when it opens its window, under the game's
own picture (``icon=``) or the engine's mark.
"""

from __future__ import annotations

import ctypes
import logging
import platform
from pathlib import Path

from PIL import Image

_logger = logging.getLogger(__name__)

#: The sizes a desktop asks a window for: macOS draws the largest, a taskbar and a title bar the small ones.
SIZES = (512, 256, 128, 64, 32, 16)

_SERVICES = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
_CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_CURRENT_SESSION = -2   # kLSDefaultSessionID
_UTF8 = 0x08000100      # kCFStringEncodingUTF8


def pictures(path: Path | str) -> list[Image.Image]:
    """The picture at ``path`` in this desktop's outline, at every size a window is asked for."""
    from saga2d.packaging import icon  # the shaping a built app's icon goes through, not the build tools

    master = icon.shaped(icon.load(Path(path)), platform.system())
    return [master.resize((side, side), Image.Resampling.LANCZOS) for side in SIZES]


def call_it(name: str) -> None:
    """Have macOS call this process ``name``, in the Dock and wherever else it names applications.

    Only Launch Services knows that name, and a process without an application
    bundle keeps the interpreter's until it is told otherwise — through calls
    Apple leaves private, so a macOS that drops them costs the name and nothing
    else. Call it once a window exists: an unregistered process has none.
    Elsewhere the desktop reads the window's title, and this does nothing.
    """
    if platform.system() != "Darwin":
        return
    services = ctypes.cdll.LoadLibrary(_SERVICES)
    try:
        rename = services._LSSetApplicationInformationItem
        display_name = ctypes.c_void_p.in_dll(services, "_kLSDisplayNameKey")
    except (AttributeError, ValueError):
        _logger.debug("This macOS takes no process name from Launch Services; the Dock keeps the interpreter's")
        return
    core = ctypes.cdll.LoadLibrary(_CORE_FOUNDATION)
    core.CFStringCreateWithCString.restype = ctypes.c_void_p
    core.CFStringCreateWithCString.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32)
    core.CFRelease.argtypes = (ctypes.c_void_p,)
    services._LSGetCurrentApplicationASN.restype = ctypes.c_void_p
    rename.restype = ctypes.c_int
    rename.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

    value = core.CFStringCreateWithCString(None, name.encode(), _UTF8)
    status = rename(_CURRENT_SESSION, services._LSGetCurrentApplicationASN(), display_name, value, None)
    core.CFRelease(value)
    if status:
        _logger.debug("Launch Services refused the name %r: OSStatus %d", name, status)
