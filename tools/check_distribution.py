"""Exercise a wheel installation from outside the source checkout.

Run with the isolated environment's Python, for example:
``/tmp/wheel-env/bin/python -I /path/to/saga2d/tools/check_distribution.py``.
The caller's working directory must not be the source checkout so the room
server subprocess also imports the installed distribution.
"""

from importlib import metadata
from pathlib import Path

from PIL import ImageFont
from websockets.sync.client import connect

import saga2d
from saga2d import Button, Column, Game, Label, Scene, fonts
from saga2d.packaging import RECIPE
from saga2d.testing.online import COUNTER_GAMES, command, handshake, receive, running_server


def check_installation() -> None:
    """The imported package and its assets must belong to the installed wheel."""
    distribution = metadata.distribution("saga2d")
    installed_module = Path(distribution.locate_file("saga2d/__init__.py")).resolve()
    assert Path(saga2d.__file__).resolve() == installed_module, "Imported a checkout instead of the wheel"
    assert saga2d.__version__ == distribution.version
    for filename in fonts.FILES.values():
        font = ImageFont.truetype(str(fonts.FONT_DIR / filename), size=18)
        assert font.getlength("Saga2D") > 0
    assert "SIL OPEN FONT LICENSE" in (fonts.FONT_DIR / "OFL.txt").read_text(encoding="utf-8")
    for filename in ("game.spec", "game.iss", "entry.py"):
        assert (RECIPE / filename).read_text(encoding="utf-8"), filename


def check_scene() -> None:
    """A packaged scene renders controls and reacts to ordinary keyboard input."""
    class CounterScene(Scene):
        def on_enter(self):
            self.count = 0
            self.ui.add(Column(
                Label(lambda: f"Count: {self.count}"),
                Button("Add", shortcut="Space", on_click=self.add),
            ))

        def add(self):
            self.count += 1

    game = Game("Distribution check", backend="mock")
    try:
        fonts.load(game)
        scene = CounterScene()
        game.push(scene)
        game.tick(0)
        assert "Count: 0" in [item["text"] for item in game.backend.texts]
        game.backend.inject_key("space")
        game.tick(0)
        assert scene.count == 1
        assert "Count: 1" in [item["text"] for item in game.backend.texts]
    finally:
        game.close()


def check_online_room() -> None:
    """The installed server hosts a real two-client room and publishes orders."""
    with running_server(COUNTER_GAMES) as (url, _process):
        with connect(url, proxy=None) as host, connect(url, proxy=None) as guest:
            welcome = handshake(host, game="counter-v1")
            receive(host)
            handshake(guest, "join", game="counter-v1", room=welcome["room"])
            ready = receive(host, predicate=lambda message: message["ready"])
            assert receive(guest)["state"] == ready["state"]
            command(guest, {"action": "add"}, ready["revision"])
            changed = receive(host)
            assert changed["state"]["counts"] == [0, 1]
            assert receive(guest)["state"] == changed["state"]


if __name__ == "__main__":
    check_installation()
    check_scene()
    check_online_room()
    print(f"Installed saga2d {saga2d.__version__}: assets, UI and online room passed.")
