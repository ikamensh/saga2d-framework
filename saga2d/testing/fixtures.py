"""Pytest fixtures shared by every saga2d project: ``pytest_plugins = ["saga2d.testing.fixtures"]`` in conftest.py."""
import pytest

from saga2d.backends.mock_backend import MockBackend
from saga2d.game import Game


@pytest.fixture
def game() -> Game:
    """A mock-backend Game torn down after every test."""
    g = Game("Test", backend="mock", resolution=(800, 600))
    yield g
    g._teardown()


@pytest.fixture
def backend(game: Game) -> MockBackend:
    return game.backend
