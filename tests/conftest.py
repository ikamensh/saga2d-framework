"""pytest fixtures for EasyGame tests."""

import pytest

from easygame import Game


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


from easygame.backends.mock_backend import MockBackend


@pytest.fixture
def mock_game() -> Game:
    """Return a Game instance with backend='mock' for headless testing."""
    return Game("Test", backend="mock", resolution=(1920, 1080))


@pytest.fixture(autouse=True)
def cleanup_globals() -> None:
    """After each test, clear module-level _current_game and _tween_manager for isolation."""
    yield
    import easygame.rendering.sprite as sprite_mod
    import easygame.util.tween as tween_mod

    game = sprite_mod._current_game
    if game is not None:
        if hasattr(game, "_teardown"):
            game._teardown()
        sprite_mod._current_game = None
    tween_mod._tween_manager = None


@pytest.fixture
def mock_backend(mock_game: Game) -> MockBackend:
    """Return the MockBackend instance from mock_game.

    Use for event injection and assertions::

        mock_backend.inject_key("space")
        mock_game.tick(dt=0.016)
        assert mock_backend.frame_count == 1
    """
    return mock_game.backend
