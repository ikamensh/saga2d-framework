"""Native regression: resizing must not reuse text measurements at the old scale.

Compare warm-cache and fresh-window metrics, wrapped flow and pixels in both
resize directions. Real mouse input confirms the following button still works.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['SAGA2D_SILENT'] = '1'

from PIL import ImageChops
from saga2d import Anchor, Button, Column, Game, Label, Scene

TEXT = 'The same visible text must measure consistently. A following control stays below every wrapped line.'


class MeasuredText(Scene):
    background_color = (12, 21, 32, 255)

    def __init__(self, font_size):
        self.font_size = font_size
        self.confirmations = 0

    def on_enter(self):
        self.paragraph = Label(TEXT, width=380, wrap=True, font='Verdana', font_size=self.font_size)
        self.confirm = Button('Confirm', width=380, on_click=self.confirm_order)
        self.ui.add(Column(self.paragraph, self.confirm, spacing=20,
                           anchor=Anchor.TOP_LEFT, margin=(70, 140)))

    def confirm_order(self):
        self.confirmations += 1

    def draw(self):
        self.draw_text('Text measurements follow the current window', 70, 55, font_size=22)
        x, y, width, height = self.paragraph.bounds
        self.draw_rect(x - 4, y - 4, width + 8, height + 8, (28, 43, 58, 255),
                       border_color=(90, 190, 170, 255), border_width=1)


def run_case(output, direction, initial, final, *, warm):
    game = Game('Text scale measurement', resolution=(1280, 800), visible=False)
    try:
        if warm:
            game.set_window_size(initial[0])
            game.push(MeasuredText(initial[1]))
            game.tick(1 / 60)
            game.backend.measure_text(TEXT, initial[1], 'Verdana')
        game.set_window_size(final[0])
        scene = MeasuredText(final[1])
        game.clear_and_push(scene)
        for _ in range(2):
            game.tick(1 / 60)
        metrics = dict(text=game.backend.measure_text(TEXT, final[1], 'Verdana'),
                       paragraph=scene.paragraph.get_preferred_size(), button=scene.confirm.bounds)
        _, top, _, height = scene.paragraph.bounds
        assert scene.confirm.bounds[1] >= top + height + 20
        frame = game.backend.capture_frame()
        frame.save(output / f'{direction}-{"warm" if warm else "fresh"}.png')
        from pyglet.window import mouse
        window = game.backend.window
        x, y, width, height = scene.confirm.bounds
        scale = min(window.width / game.width, window.height / game.height)
        px = (window.width - game.width * scale) / 2 + (x + width / 2) * scale
        py = (window.height - game.height * scale) / 2 + (game.height - y - height / 2) * scale
        window.dispatch_event('on_mouse_press', round(px), round(py), mouse.LEFT, 0)
        window.dispatch_event('on_mouse_release', round(px), round(py), mouse.LEFT, 0)
        game.tick(1 / 60)
        assert scene.confirmations == 1
        return metrics, frame
    finally:
        game._teardown()
        game.backend.quit()


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    small = ((1280, 720), 18)
    large = ((1920, 1080), 12)
    # The font requests share the rounded physical size on either 1x or 2x
    # displays, but their logical metrics must differ with the viewport scale.
    report = {}
    for direction, initial, final in (('grow', small, large), ('shrink', large, small)):
        warm, warm_frame = run_case(output, direction, initial, final, warm=True)
        fresh, fresh_frame = run_case(output, direction, initial, final, warm=False)
        report[direction] = dict(warm=warm, fresh=fresh)
        assert warm == fresh, (direction, warm, fresh)
        assert ImageChops.difference(warm_frame.convert('RGB'), fresh_frame.convert('RGB')).getbbox() is None, direction
    (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Native resize measurement/flow/pixel equality and clicks passed both directions: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/saga2d-text-measurement'))
    verify(parser.parse_args().output)
