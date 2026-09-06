"""Independent wrapped-label flow, font changes and native input example.

Run normally to interact; --verify checks rendered bounds and real keyboard/mouse input.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['SAGA2D_SILENT'] = '1'

from saga2d import Anchor, Button, Column, Game, Label, Row, Scene, Style, TextStyle

INK = (12, 21, 32, 255)
PANEL = Style(padding=20, radius=12, background_color=(28, 43, 58, 255))
LONG = ('Gather the army at the northern gate before advancing toward the enemy.\n\n'
        'Keep the wounded behind the line. The next control follows this description.')
SHORT = 'The army is ready.'


class WrappedLabels(Scene):
    background_color = INK

    def __init__(self):
        self.message = LONG
        self.large = False
        self.clicks = 0

    def on_enter(self):
        self.set_font()
        self.description = Label(lambda: self.message, width=350, wrap=True, text_style='description')
        self.confirm = Button('Confirm order', on_click=self.confirm_order, width=350)
        self.ui.add(Column(Label('Reactive description', font_size=22), self.description, self.confirm,
                           spacing=16, anchor=Anchor.TOP_LEFT, margin=(30, 110), style=PANEL))
        self.ui.add(Column(
            Label('One width, three alignments', font_size=22),
            *(Label('Measured lines stay inside this column.\nExplicit breaks stay intact.',
                    width=350, wrap=True, align=align, font_size=16,
                    text_color=(119, 218, 204, 255)) for align in ('left', 'center', 'right')),
            spacing=24, anchor=Anchor.TOP_LEFT, margin=(470, 110), style=PANEL,
        ))
        self.ui.add(Row(
            Button('Change text', shortcut='T', on_click=self.change_text),
            Button('Change font', shortcut='F', on_click=self.change_font),
            Button('Overlay', shortcut='O', on_click=lambda: self.game.push(Overlay())),
            Button('Quit', shortcut='Esc', on_click=self.game.quit),
            spacing=12, anchor=Anchor.BOTTOM_LEFT, margin=(30, 24),
        ))

    def set_font(self):
        self.game.theme.set_text_style('description', TextStyle(22 if self.large else 16, (248, 250, 252, 255),
                                                               'Georgia' if self.large else 'Arial'))

    def change_text(self):
        self.message = SHORT if self.message == LONG else LONG

    def change_font(self):
        self.large = not self.large
        self.set_font()

    def confirm_order(self):
        self.clicks += 1

    def draw(self):
        self.draw_text('Text that fits its flow', 30, 35, font_size=30, color=(238, 197, 109, 255))
        self.draw_text(f'Confirmations: {self.clicks}. Text and font changes move the next button automatically.',
                       30, 78, font_size=16)


class Overlay(Scene):
    transparent = True

    def on_enter(self):
        self.ui.add(Button('Close overlay', shortcut='Esc', on_click=self.game.pop, anchor=Anchor.CENTER))

    def draw(self):
        self.draw_rect(0, 0, self.game.width, self.game.height, (0, 0, 0, 90))


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='saga2d-wrapped-label-') as directory:
        game = Game('Wrapped labels', resolution=(900, 760), visible=False, save_dir=Path(directory) / 'saves')
        from pyglet.window import key, mouse
        inputs = 0

        def press(symbol):
            nonlocal inputs
            window = game.backend.window
            window.dispatch_event('on_key_press', symbol, 0)
            window.dispatch_event('on_key_release', symbol, 0)
            game.tick(1 / 60)
            inputs += 1

        def click(button):
            nonlocal inputs
            x, y, w, h = button.bounds
            window = game.backend.window
            scale = min(window.width / game.width, window.height / game.height)
            px = (window.width - game.width * scale) / 2 + (x + w / 2) * scale
            py = (window.height - game.height * scale) / 2 + (game.height - y - h / 2) * scale
            window.dispatch_event('on_mouse_press', round(px), round(py), mouse.LEFT, 0)
            window.dispatch_event('on_mouse_release', round(px), round(py), mouse.LEFT, 0)
            game.tick(1 / 60)
            inputs += 1

        def capture(name):
            frame = game.backend.capture_frame()
            frame.save(output / f'{name}.png')
            return frame

        def check_text_pixels(frame, label):
            x, y, w, h = label.bounds
            sx, sy = frame.width / game.width, frame.height / game.height
            # Inspect actual bright glyph pixels, including the surrounding gutter.
            crop = frame.crop((round((x - 8) * sx), round(y * sy), round((x + w + 8) * sx), round((y + h) * sy)))
            points = [(px, py) for py in range(crop.height) for px in range(crop.width)
                      if min(crop.getpixel((px, py))[:3]) > 180]
            assert len(points) > 20
            assert min(px for px, _ in points) >= round(6 * sx)
            assert max(px for px, _ in points) <= round((w + 10) * sx)
            assert scene.confirm.bounds[1] >= y + h + 16

        try:
            scene = WrappedLabels()
            game.push(scene)
            game.tick(1 / 60)
            check_text_pixels(capture('initial-flow'), scene.description)
            initial_height = scene.description.bounds[3]
            press(key.T)
            assert scene.description.bounds[3] < initial_height
            press(key.F)
            press(key.T)
            assert scene.description.bounds[3] > initial_height
            check_text_pixels(capture('larger-font-flow'), scene.description)
            click(scene.confirm)
            assert scene.clicks == 1
            press(key.O)
            scene.message = SHORT
            game.tick(1 / 60)
            assert scene.description.bounds[3] < initial_height
            capture('paused-overlay-reflow')
            press(key.ESCAPE)
            assert game.scene is scene
            click(scene.confirm)
            assert scene.clicks == 2
            press(key.T)
            game.set_window_size((720, 608))
            game.tick(1 / 60)
            check_text_pixels(capture('resized-flow'), scene.description)
            click(scene.confirm)
            assert scene.clicks == 3
            report = dict(input_activations=inputs, confirmations=scene.clicks, resolution=game.resolution,
                          window_size=game.window_size, initial_height=initial_height,
                          expanded_height=scene.description.bounds[3])
            (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
            print(f'Native wrapped bounds, reactive/paused flow, fonts and clicks passed: {report}')
            return report
        finally:
            game._teardown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('/tmp/saga2d-wrapped-label'))
    args = parser.parse_args()
    if args.verify:
        verify(args.output)
    else:
        Game('Wrapped labels', resolution=(900, 760)).run(WrappedLabels())
