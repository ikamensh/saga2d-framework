"""Backend implementations.  Game code never imports from here; ``Game``
selects a backend by name and the framework talks to it through the
:class:`~saga2d.backends.base.Backend` protocol."""
