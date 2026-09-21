"""What the desktop makes of a running game: the icon it draws for it, and the name beside it.

A built game carries both in its bundle, but a game started from a checkout is
a bare Python process: macOS draws a blank page called ``python3.13`` in the
Dock, and Windows the interpreter's own icon in the taskbar. :func:`pictures`
shapes a game's icon exactly as its built app wears it
(:mod:`saga2d.packaging.icon`), for the backend to hand the window, which fixes
the picture everywhere.

The *name* beside it cannot be fixed from inside the process. macOS labels a
Dock tile from the running application's bundle, and a process started from a
checkout has none, so the tile keeps the interpreter's file name however the
window is captioned. Measured on macOS 26: setting the Launch Services display
name before the tile is created does not move it, and neither does
``CFBundleName`` in the main bundle's info dictionary, which does not survive
check-in. Only a real ``.app`` changes it — which is what
:mod:`saga2d.packaging` builds. :func:`call_it` is still worth the call: it is
the name Activity Monitor, the Force Quit window and ``lsappinfo`` show, so a
hung game is named for the game there rather than ``python3``.

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
    """Have macOS call this process ``name`` wherever it reads Launch Services.

    That is Activity Monitor, the Force Quit window and ``lsappinfo``, and not
    the Dock tile, which is labelled from the application bundle a game run from
    a checkout does not have (see this module's docstring). Only Launch Services
    knows this name, and only through calls Apple leaves private, so a macOS
    that drops them costs the name and nothing else. Call it once a window
    exists: an unregistered process has none. Elsewhere this does nothing.
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
