"""Shared fixtures: a mock-backend Game torn down after every test."""

import pytest

from saga2d import Game
from saga2d.backends.mock_backend import MockBackend


@pytest.fixture
def game() -> Game:
    g = Game("Test", backend="mock", resolution=(800, 600))
    yield g
    g._teardown()


@pytest.fixture
def backend(game: Game) -> MockBackend:
    return game.backend
