"""A game-independent button shortcut example.

    uv run python tools/demo_button_shortcuts.py

Try Enter/Space at the limit, Tab to a shorter preset page, and Enter while
the help overlay is open. No key registration or unbinding is needed.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from saga2d import Anchor, Button, Column, Game, Label, Row, Scene, Style  # noqa: E402


PANEL = Style(padding=24, radius=12, background_color=(24, 32, 49, 255))


class Counter(Scene):
    background_color = (10, 14, 25, 255)

    def __init__(self):
        self.value = 0
        self.page = 0

    def on_enter(self):
        self.refresh()

    def refresh(self):
        self.ui.clear()
        panel = Column(spacing=16, anchor=Anchor.CENTER, style=PANEL)
        panel.add(Label("Button shortcuts", font_size=28))
        panel.add(Label(lambda: f"Counter: {self.value} / 3", font_size=22))
        panel.add(Row(
            Button("Add one", shortcut=("Enter", "Space"), on_click=self.add, enabled=self.value < 3),
            Button("Reset", shortcut="Ctrl+R", on_click=lambda: self.set_value(0)), spacing=12,
        ))
        panel.add(Label("Enter or Space adds one. At three, both the button and key stop.", font_size=13))
        panel.add(Label(f"Presets · page {self.page + 1} of 2", font_size=18))
        presets = (1, 2, 3) if self.page == 0 else (0,)
        panel.add(Row(*(Button(str(value), shortcut=str(index + 1), on_click=lambda value=value: self.set_value(value))
                        for index, value in enumerate(presets)), spacing=12))
        panel.add(Row(Button("Next page", shortcut="Tab", on_click=self.next_page),
                      Button("Help", shortcut="H", on_click=lambda: self.game.push(Help())),
                      Button("Quit", shortcut="Esc", on_click=self.game.quit), spacing=12))
        panel.add(Label("Page two removes keys 2 and 3. Help temporarily owns Enter.", font_size=13))
        self.ui.add(panel)

    def set_value(self, value):
        self.value = value
        self.refresh()

    def add(self):
        self.set_value(self.value + 1)

    def next_page(self):
        self.page = 1 - self.page
        self.refresh()


class Help(Scene):
    transparent = True

    def on_enter(self):
        self.ui.add(Column(
            Label("This dialog owns Enter", font_size=24),
            Label("Closing it leaves the counter unchanged.", font_size=15),
            Button("Close", shortcut=("Enter", "Esc"), on_click=self.game.pop),
            spacing=20, anchor=Anchor.CENTER, style=PANEL,
        ))

    def draw(self):
        self.draw_rect(0, 0, self.game.width, self.game.height, (0, 0, 0, 180))


if __name__ == "__main__":
    Game("Button shortcuts", resolution=(800, 600)).run(Counter())
