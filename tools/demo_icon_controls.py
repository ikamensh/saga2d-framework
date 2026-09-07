"""Independent icon buttons, resource images and owned hover explanations.

    uv run python tools/demo_icon_controls.py
    uv run python tools/demo_icon_controls.py --verify --output /tmp/saga2d-icon-controls

Hover the disabled Save icon, enable it with D, then use F5 or click. Hover
both parts of the sample count. Open the modal and notice that the underlying
explanations and shortcuts stop. Native verification uses paced explicit ticks.
"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['SAGA2D_SILENT'] = '1'

from PIL import Image as PILImage, ImageDraw
from saga2d import Anchor, Button, Column, Game, Image, Label, Row, Scene, Style, TextStyle, Theme
from tools.native_frames import tick

PANEL = Style(padding=24, radius=12, background_color=(27, 39, 58, 255))


def icons(game):
    """Small original pictograms; the example has no game asset dependency."""
    for name in ('disk', 'sample', 'help'):
        image = PILImage.new('RGBA', (64, 64))
        draw = ImageDraw.Draw(image)
        if name == 'disk':
            draw.rounded_rectangle((7, 6, 57, 58), radius=5, fill='#79c5e8')
            draw.rectangle((17, 6, 46, 25), fill='#253c52')
            draw.rectangle((21, 37, 44, 57), fill='#dceff7')
        elif name == 'sample':
            draw.polygon(((32, 5), (56, 20), (49, 49), (32, 59), (15, 49), (8, 20)), fill='#eac05b')
            draw.line(((8, 20), (32, 32), (56, 20)), fill='#fff0b0', width=3)
            draw.line(((32, 32), (32, 57)), fill='#a7772e', width=3)
        else:
            draw.ellipse((5, 5, 59, 59), fill='#99bea7')
            draw.rounded_rectangle((28, 26, 36, 48), radius=2, fill='#253c3b')
            draw.ellipse((28, 15, 36, 23), fill='#253c3b')
        game.assets.image_from_pil(name, image)


class Icons(Scene):
    background_color = (10, 17, 29, 255)

    def __init__(self):
        self.saved = 0

    def on_enter(self):
        icons(self.game)
        self.save = Button(lambda: f'Save snapshot {self.saved + 1}', icon='disk', icon_size=30,
                           show_text=False, shortcut='F5', width=88, height=54,
                           enabled=False, on_click=self.save_snapshot)
        self.value = Label(lambda: str(12 + self.saved), font_size=24)
        self.resources = Row(Image('sample', width=30, height=30), self.value,
                             tooltip='Available samples. Hovering the image or value gives the same explanation.')
        self.ui.add(Column(
            Label('Small controls, complete explanations', font_size=28),
            Label('The icon keeps its name and shortcut. Disabled actions still explain themselves.',
                  width=610, wrap=True, font_size=18),
            Row(self.save, Button('Enable / disable Save', icon='disk', shortcut='D', on_click=self.toggle), spacing=16),
            self.resources,
            Label(lambda: f'Snapshots saved: {self.saved}', font_size=20),
            Button('Open help overlay', icon='help', shortcut='H', on_click=lambda: self.game.push(Help()),
                   tooltip='Open a modal above this scene and its hover explanations.'),
            spacing=20, anchor=Anchor.CENTER, style=PANEL,
        ))

    def toggle(self):
        self.save.enabled = not self.save.enabled

    def save_snapshot(self):
        self.saved += 1


class Help(Scene):
    transparent = True

    def on_enter(self):
        self.ui.add(Column(
            Label('This scene owns input and hover', font_size=24),
            Label('F5 cannot save beneath this overlay.', font_size=18),
            Button('Close help', icon='help', shortcut='Esc', on_click=self.game.pop),
            spacing=22, anchor=Anchor.CENTER, style=PANEL,
        ))

    def draw(self):
        self.draw_rect(0, 0, self.game.width, self.game.height, (5, 10, 18, 235))


def verify(game, output):
    from pyglet.window import key, mouse

    output.mkdir(parents=True, exist_ok=True)
    scene = Icons()
    game.push(scene)
    tick(game)
    cached = game.assets.image('disk')

    def point(component):
        x, y, w, h = component.bounds
        window = game.backend.window
        scale = min(window.width / game.width, window.height / game.height)
        return (round((window.width - game.width * scale) / 2 + (x + w / 2) * scale),
                round((window.height - game.height * scale) / 2 + (game.height - y - h / 2) * scale))

    def hover(component):
        game.backend.window.dispatch_event('on_mouse_motion', *point(component), 0, 0)
        tick(game)

    def press(symbol):
        game.backend.window.dispatch_event('on_key_press', symbol, 0)
        game.backend.window.dispatch_event('on_key_release', symbol, 0)
        tick(game)

    def click(component):
        game.backend.window.dispatch_event('on_mouse_press', *point(component), mouse.LEFT, 0)
        game.backend.window.dispatch_event('on_mouse_release', *point(component), mouse.LEFT, 0)
        tick(game)

    def capture(name):
        game.backend.capture_frame().save(output / f'{name}.png')

    hover(scene.save)
    press(key.F5)
    assert scene.saved == 0
    capture('disabled-icon-tooltip')
    press(key.D)
    press(key.F5)
    click(scene.save)
    assert scene.saved == 2
    hover(scene.value)
    capture('resource-row-tooltip')
    press(key.H)
    press(key.F5)
    assert isinstance(game.scene, Help) and scene.saved == 2
    capture('modal-suppresses-tooltip')
    press(key.ESCAPE)
    assert game.scene is scene
    hover(scene.save)
    capture('restored-reactive-tooltip')
    assert game.assets.image('disk') == cached
    print(f'Native icon clicks, shortcuts, disabled input, modal ownership and cached images passed: {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('/tmp/saga2d-icon-controls'))
    args = parser.parse_args()
    theme = Theme(font_size=20, button_font_size=22, keycap_font_size=15,
                  text_styles={'body': TextStyle(20, (245, 247, 250, 255))})
    game = Game('Icon controls', resolution=(800, 520), theme=theme, visible=not args.verify)
    if args.verify:
        try:
            verify(game, args.output)
        finally:
            game.close()
        assert game.backend.window is None and game.scene is None
    else:
        game.run(Icons())


if __name__ == '__main__':
    main()
