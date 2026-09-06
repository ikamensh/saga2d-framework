"""Independent local-layer, overlapping-control and modal example.

Run normally to interact, or use --verify for native input and pixel checks.
"""
import argparse
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['SAGA2D_SILENT'] = '1'

from PIL import Image
from saga2d import Anchor, Button, Column, Game, Label, Scene, Style

INK = (15, 24, 38, 255)
PANEL = (30, 51, 72, 255)
GOLD = (240, 194, 86, 255)
MAGENTA = (255, 0, 255, 255)


class Layers(Scene):
    background_color = INK

    def __init__(self):
        self.activated = []

    def on_enter(self):
        self.game.assets.image_from_pil('sample', Image.new('RGBA', (8, 8), MAGENTA))
        self.back = self.ui.add(Button('HIDDEN BACK', on_click=lambda: self.activated.append('back'),
                                       width=350, height=130, anchor=Anchor.TOP_LEFT, margin=(470, 170),
                                       style=Style(text_color=MAGENTA, background_color=INK, radius=0)))
        self.front = self.ui.add(Column(
            Label('Later sibling covers earlier text', font_size=17),
            Button('Activate front', shortcut='F', on_click=lambda: self.activated.append('front'), width=306, height=44),
            width=350, height=130, anchor=Anchor.TOP_LEFT, margin=(470, 170), spacing=14,
            style=Style(background_color=PANEL, padding=22, radius=0),
        ))
        self.ui.add(Button('Hide / show front', shortcut='H', on_click=self.toggle,
                           width=350, anchor=Anchor.TOP_LEFT, margin=(470, 328)))
        self.ui.add(Button('Open modal overlay', shortcut='O', on_click=lambda: self.game.push(Overlay()),
                           width=350, anchor=Anchor.TOP_LEFT, margin=(470, 385)))

    def toggle(self):
        self.front.visible = not self.front.visible

    def draw(self):
        self.draw_text('Layers inside one scene', 50, 65, font_size=30, color=GOLD)
        self.draw_text('A drawing scope orders a whole composition; controls keep their own tree order.',
                       50, 104, font_size=16)
        self.draw_text('Earlier health label', 220, 225, font_size=30, color=MAGENTA,
                       anchor_x='center', anchor_y='center')
        with self.screen_layer(1):
            self.draw_rect(50, 170, 350, 115, PANEL)
            self.draw_text('Recovered +8', 225, 226, font_size=28, color=GOLD,
                           anchor_x='center', anchor_y='center')
        self.draw_image('sample', 50, 320, 350, 105)
        with self.screen_layer(1):
            self.draw_rect(50, 320, 350, 105, PANEL)
            self.draw_paragraph('This panel also covers an earlier image.', 75, 350, 300,
                                font_size=18, color=GOLD)
        # Even the highest Scene.draw layer remains behind the UI controls.
        with self.screen_layer(999):
            self.draw_rect(470, 170, 350, 130, MAGENTA)
        self.draw_text('No magenta should leak through either panel or the front control.', 50, 465, font_size=16)
        self.draw_text(f'Activated: {", ".join(self.activated) or "none"}', 50, 505, font_size=16)


class Overlay(Scene):
    transparent = True

    def on_enter(self):
        self.ui.add(Button('Close overlay', shortcut='Esc', on_click=self.game.pop,
                           anchor=Anchor.CENTER, margin=0))

    def draw(self):
        self.draw_rect(0, 0, self.game.width, self.game.height, INK)
        self.draw_text('The next scene covers every local layer and control.',
                       self.game.width / 2, 120, font_size=23, color=GOLD, anchor_x='center')


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='saga2d-screen-layers-') as directory:
        game = Game('Screen layers', resolution=(900, 560), visible=False, save_dir=Path(directory) / 'saves')
        from pyglet.window import key, mouse

        def press(symbol):
            game.backend.window.dispatch_event('on_key_press', symbol, 0)
            game.backend.window.dispatch_event('on_key_release', symbol, 0)
            game.tick(1 / 60)

        def click(label):
            button = game.scene.ui.find(lambda item: isinstance(item, Button) and item.text == label)
            assert button is not None and button.enabled
            x, y, width, height = button.bounds
            window = game.backend.window
            scale = min(window.width / game.width, window.height / game.height)
            px = (window.width - game.width * scale) / 2 + (x + width / 2) * scale
            py = (window.height - game.height * scale) / 2 + (game.height - y - height / 2) * scale
            window.dispatch_event('on_mouse_press', round(px), round(py), mouse.LEFT, 0)
            window.dispatch_event('on_mouse_release', round(px), round(py), mouse.LEFT, 0)
            game.tick(1 / 60)

        def capture(name):
            frame = game.backend.capture_frame()
            frame.save(output / f'{name}.png')
            return frame

        def region(frame, bounds):
            sx, sy = frame.width / game.width, frame.height / game.height
            return frame.crop(tuple(round(value * (sx if i % 2 == 0 else sy)) for i, value in enumerate(bounds)))

        def no_magenta(frame, bounds):
            assert not any(r > 180 and b > 180 and g < 80 for r, g, b, *_ in colors(frame, bounds))

        def colors(frame, bounds):
            part = region(frame, bounds)
            return {color for _, color in part.getcolors(part.width * part.height)}

        try:
            scene = Layers()
            game.push(scene)
            game.tick(1 / 60)
            frame = capture('local-layers-and-controls')
            no_magenta(frame, (50, 170, 400, 285))
            no_magenta(frame, (50, 320, 400, 425))
            no_magenta(frame, (470, 170, 820, 300))
            assert any(r > 180 and g > 130 and b < 120 for r, g, b, *_ in colors(frame, (50, 170, 400, 285)))
            click('Activate front')
            assert scene.activated == ['front']
            press(key.H)
            click('HIDDEN BACK')
            assert scene.activated == ['front', 'back']
            press(key.H)
            click('Open modal overlay')
            assert isinstance(game.scene, Overlay)
            frame = capture('modal-above-all-layers')
            assert colors(frame, (50, 170, 300, 285)) == {INK}
            press(key.F)
            assert scene.activated == ['front', 'back']
            press(key.ESCAPE)
            assert game.scene is scene
            click('Activate front')
            assert scene.activated == ['front', 'back', 'front']
            capture('restored-controls')
            print(f'Native layer coverage, UI clicks and modal isolation passed: {output}')
        finally:
            game.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('/tmp/saga2d-screen-layers'))
    args = parser.parse_args()
    if args.verify:
        verify(args.output)
    else:
        Game('Screen layers', resolution=(900, 560)).run(Layers())
