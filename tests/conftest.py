"""pytest fixtures for EasyGame tests."""

import pytest

from easygame import Game
from easygame.backends.mock_backend import MockBackend


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
    """Return a Game instance with backend='mock' for headless testing."""
    return Game("Test", backend="mock", resolution=(1920, 1080))


@pytest.fixture
def mock_backend(mock_game: Game) -> MockBackend:
    """Return the MockBackend instance from mock_game.

    Use for event injection and assertions::

        mock_backend.inject_key("space")
        mock_game.tick(dt=0.016)
        assert mock_backend.frame_count == 1
    """
    return mock_game.backend
