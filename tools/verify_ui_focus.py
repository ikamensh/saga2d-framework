"""Real keyboard/pointer focus, custom controls, blocked HUD clicks and modal ownership.

    uv run python tools/verify_ui_focus.py --output /tmp/saga2d-ui-focus

The hidden native window is silent. Screenshots show a game-independent custom
card and an ordinary button sharing the same interaction and focus interface.
"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SAGA2D_SILENT"] = "1"

from saga2d import Anchor, Button, Column, Component, Game, Label, Panel, Scene, Style
from saga2d.rendering.shapes import draw_box
from saga2d.testing.native_frames import tick


class Card(Button):
    def on_draw(self):
        backend = self._game.backend
        x, y, w, h = self.bounds
        color = (241, 189, 88, 255) if self.focused or self.hovered else (139, 157, 174, 255)
        draw_box(backend, x, y, w, h, (31, 49, 65, 255), border_color=color,
                 border_width=3, radius=12, order=self._order)
        backend.draw_text("CUSTOM CARD", x + w / 2, y + 32, 14, color,
                          anchor_x="center", anchor_y="top", order=self._order)
        backend.draw_text(self.text, x + w / 2, y + 68, 19, (237, 241, 245, 255),
                          anchor_x="center", anchor_y="top", order=self._order)


class DragPad(Component):
    def __init__(self):
        super().__init__(width=210, height=70, blocks_pointer=True, anchor=Anchor.TOP_LEFT, margin=(50, 330))
        self.drags = 0
        self.cancelled = 0

    def on_event(self, event):
        if event.type == "click" and self.hit_test(event.x, event.y):
            self.capture_pointer()
            return True
        if event.type == "drag" and self.has_pointer_capture:
            self.drags += 1
            return True
        return False

    def on_pointer_cancel(self):
        self.cancelled += 1

    def on_draw(self):
        x, y, w, h = self.bounds
        draw_box(self._game.backend, x, y, w, h, (48, 62, 74, 255),
                 border_color=(139, 157, 174, 255), border_width=1, order=self._order)
        self._game.backend.draw_text("Drag beyond this box", x + 15, y + 22, 15,
                                     (235, 238, 244, 255), anchor_y="top", order=self._order)


class Demo(Scene):
    background_color = (13, 23, 34, 255)

    def on_enter(self):
        self.activations = 0
        self.world_clicks = 0
        self.ui.enable_focus(navigation="vertical")
        self.ui.add(Label("Shared focus, custom appearance", font_size=25,
                          anchor=Anchor.TOP_LEFT, margin=(50, 28)))
        self.card = self.ui.add(Card("The watchtower", width=210, height=145,
                                     anchor=Anchor.TOP_LEFT, margin=(50, 90), on_click=self.activate))
        self.button = self.ui.add(Button("Ordinary button", width=220, height=54,
                                        anchor=Anchor.TOP_LEFT, margin=(315, 120), on_click=self.activate))
        self.ui.add(Label("Tab / arrows move focus; Enter activates", font_size=16,
                          anchor=Anchor.TOP_LEFT, margin=(50, 265)))
        self.ui.add(Label(lambda: f"Activations: {self.activations}   World clicks: {self.world_clicks}",
                          font_size=16, anchor=Anchor.TOP_LEFT, margin=(50, 295)))
        self.drag = self.ui.add(DragPad())

    def activate(self):
        self.activations += 1

    def handle_input(self, event):
        if event.type == "click":
            self.world_clicks += 1
        return False


class Modal(Scene):
    transparent = True

    def on_enter(self):
        self.ui.enable_focus()
        close = Button("Close with Enter", on_click=self.game.pop)
        self.ui.add(Column(Label("Modal owns input", font_size=24), close,
                           spacing=20, anchor=Anchor.CENTER, style=Style(padding=28)))
        self.ui.focus(close)

    def draw(self):
        self.draw_rect(0, 0, self.game.width, self.game.height, (0, 0, 0, 175))


def verify(output):
    from pyglet.window import key, mouse

    output.mkdir(parents=True, exist_ok=True)
    game = Game("Focus verification", resolution=(640, 450), visible=False)
    try:
        scene = Demo()
        game.push(scene)
        tick(game)
        window = game.backend.window

        def point(x, y):
            scale = min(window.width / game.width, window.height / game.height)
            return (round((window.width - game.width * scale) / 2 + x * scale),
                    round((window.height - game.height * scale) / 2 + (game.height - y) * scale))

        def press(symbol):
            window.dispatch_event("on_key_press", symbol, 0)
            window.dispatch_event("on_key_release", symbol, 0)
            tick(game)

        press(key.TAB)
        assert scene.ui.focused is scene.card
        game.backend.capture_frame().save(output / "card-focus.png")
        press(key.ENTER)
        assert scene.activations == 1
        press(key.DOWN)
        assert scene.ui.focused is scene.button
        game.backend.capture_frame().save(output / "button-focus.png")
        # An unavailable HUD panel must not activate its covered button or world.
        cover = scene.ui.add(Panel(width=220, height=54, anchor=Anchor.TOP_LEFT,
                                   margin=(315, 120), enabled=False, blocks_pointer=True))
        tick(game)
        window.dispatch_event("on_mouse_press", *point(350, 140), mouse.LEFT, 0)
        tick(game)
        assert (scene.activations, scene.world_clicks) == (1, 0)
        scene.ui.remove(cover)
        window.dispatch_event("on_mouse_press", *point(100, 355), mouse.LEFT, 0)
        window.dispatch_event("on_mouse_drag", *point(570, 355), 470, 0, mouse.LEFT, 0)
        tick(game)
        assert scene.drag.drags == 1 and scene.drag.has_pointer_capture
        game.push(Modal())
        tick(game)
        assert not scene.drag.has_pointer_capture and scene.drag.cancelled == 1
        game.backend.capture_frame().save(output / "modal.png")
        window.dispatch_event("on_key_press", key.ENTER, 0)
        window.dispatch_event("on_key_press", key.ENTER, 0)
        tick(game)
        assert game.scene is scene and scene.activations == 1
        press(key.ENTER)
        assert scene.activations == 2
        print("Native focus, pointer blocking, capture and modal checks passed.")
    finally:
        game.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/ui-focus"))
    verify(parser.parse_args().output)
