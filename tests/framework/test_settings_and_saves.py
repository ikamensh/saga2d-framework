"""saga2d.settings and the save slots: defaults, corrupt files, named slots, summaries."""

import json
from pathlib import Path

import pytest

from saga2d import Game, SaveError, Scene
from saga2d.settings import Settings


def test_settings_fill_defaults_persist_and_survive_a_bad_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    s = Settings(path, {"music": 0.6, "edge_scroll": True, "name": "x"})
    assert s["music"] == 0.6 and dict(s) == {"music": 0.6, "edge_scroll": True, "name": "x"} and s.error is None
    s["music"] = 0.2
    s["extra"] = [1, 2]
    s.save()
    again = Settings(path, {"music": 0.6, "edge_scroll": True, "name": "x", "new": 5})
    assert again["music"] == 0.2 and again["extra"] == [1, 2] and again["new"] == 5
    path.write_text('{"music": "loud", "edge_scroll": false}')
    typed = Settings(path, {"music": 0.6, "edge_scroll": True})
    assert typed["music"] == 0.6 and typed["edge_scroll"] is False  # a wrong kind of value keeps the default
    path.write_text("{not json")
    broken = Settings(path, {"music": 0.6})
    assert broken["music"] == 0.6 and broken.error is not None
    broken.save()
    assert json.loads(path.read_text()) == {"music": 0.6}


def test_game_owns_a_data_dir_with_saves_and_settings(tmp_path: Path) -> None:
    game = Game("My Game", backend="mock", save_dir=tmp_path / "saves")
    try:
        assert game.data_dir == tmp_path
        settings = game.settings({"volume": 1.0})
        settings["volume"] = 0.3
        settings.save()
        assert (tmp_path / "settings.json").exists() and game.settings({}) is settings
    finally:
        game._teardown()
    plain = Game("My Game", backend="mock")
    try:
        assert plain.data_dir == Path.home() / ".my_game"
    finally:
        plain._teardown()


class Saver(Scene):
    def __init__(self) -> None:
        self.gold = 5

    def get_save_state(self):
        return {"gold": self.gold}

    def get_save_summary(self):
        return {"map": "Medium", "clock": "04:20"}

    def load_save_state(self, state):
        self.gold = state["gold"]


def test_named_slots_summaries_and_corrupt_files_in_the_browser(tmp_path: Path) -> None:
    game = Game("Slots", backend="mock", save_dir=tmp_path)
    try:
        scene = Saver()
        game.push(scene)
        game.save(1)
        scene.gold = 9
        game.save("autosave")
        listing = game.save_manager.list_slots(3, names=("autosave", "quick"))
        assert listing[0]["summary"] == {"map": "Medium", "clock": "04:20"} and "state" not in listing[0]
        assert listing[1] is None and listing[2] is None
        assert listing[3]["slot"] == "autosave" and listing[4] is None
        scene.gold = 0
        game.load("autosave")
        assert scene.gold == 9
        (tmp_path / "save_2.json").write_text("{}")
        (tmp_path / "save_3.json").write_text("[1, 2]")
        listing = game.save_manager.list_slots(3)
        assert "error" in listing[1] and "error" in listing[2] and listing[0]["slot"] == 1
        with pytest.raises(SaveError):
            game.load(2)
        assert scene.gold == 9  # a refused load leaves the scene alone
        with pytest.raises(ValueError):
            game.save("not a name")
        with pytest.raises(TypeError):
            game.save(1.5)
        game.save_manager.delete("autosave")
        assert game.save_manager.load("autosave") is None
    finally:
        game._teardown()
