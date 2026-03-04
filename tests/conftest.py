"""pytest fixtures for Saga2D tests."""

import pytest

from saga2d import Game
from saga2d.backends.mock_backend import MockBackend


@pytest.fixture(autouse=True)
def _teardown_game_globals() -> None:
    """Clear module-level globals after each test for isolation.

    When tests use tick() instead of run(), Game._teardown() is never called,
    leaving _current_game and _tween_manager set. This causes cross-test
    pollution. Clearing them after each test ensures isolation.
    """
    yield
    import saga2d.rendering.sprite as _sprite_mod
    import saga2d.util.tween as _tween_mod

    _sprite_mod._current_game = None
    _tween_mod._tween_manager = None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "visual: visual demo test (requires display, pyglet)",
    )


# Exclude visual and screenshot tests (require display, pyglet) from collection.
# "tests/visual" is project-relative (legacy); "screenshot" is conftest-relative.
# Both are defensive — visual tests have no test_ functions, screenshot has its own
# conftest with a pyglet-availability skip guard.
collect_ignore = ["visual", "screenshot"]


@pytest.fixture
def mock_game() -> Game:
    """Return a Game instance with backend='mock' for headless testing.

    Calls _teardown() after the test so module-level globals and scene stack
    are cleaned up even when run() is never called.
    """
    g = Game("Test", backend="mock", resolution=(1920, 1080))
    yield g
    g._teardown()


@pytest.fixture
def mock_backend(mock_game: Game) -> MockBackend:
    """Return the MockBackend instance from mock_game.

    Use for event injection and assertions::

        mock_backend.inject_key("space")
        mock_game.tick(dt=0.016)
        assert mock_backend.frame_count == 1
    """
    return mock_game.backend
