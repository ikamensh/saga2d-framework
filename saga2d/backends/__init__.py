"""Backend implementations for the Saga2D framework.

This package is *internal* — game code never imports from here directly.
The ``Game`` class selects and owns the backend; the rest of the framework
interacts with it through the :class:`~saga2d.backends.base.Backend`
protocol.

Re-exported for convenience within the framework:

* Event dataclasses: :class:`KeyEvent`, :class:`MouseEvent`, :class:`WindowEvent`
* Union type: :data:`Event`
* Opaque handles: :data:`ImageHandle`, :data:`SoundHandle`, :data:`FontHandle`
* Protocol: :class:`Backend`
"""

from saga2d.backends.base import (
    Backend,
    Event,
    FontHandle,
    ImageHandle,
    KeyEvent,
    MouseEvent,
    SoundHandle,
    WindowEvent,
)
from saga2d.backends.mock_backend import MockBackend

__all__ = [
    "Backend",
    "Event",
    "FontHandle",
    "ImageHandle",
    "KeyEvent",
    "MockBackend",
    "MouseEvent",
    "SoundHandle",
    "WindowEvent",
]
