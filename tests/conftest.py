"""pytest fixtures for EasyGame tests."""

import pytest

from easygame import Game

# Exclude visual tests (require display, pyglet) from collection.
collect_ignore = ["tests/visual"]


from easygame.backends.mock_backend import MockBackend


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
