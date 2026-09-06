"""Place a preview above its controls by measuring it before it joins the UI.

Run interactively, or --verify for native size, font, resize and input checks.
This example uses only Saga2D; there are no Shardbound imports or assets.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SAGA2D_SILENT', '1')

from saga2d import Anchor, Button, Column, Game, Label, Row, Scene, Style, TextStyle

SHORT = 'Deliver a letter to the harbour.'
LONG = ('Carry the observatory supplies through the mountain pass. Stop at the inn before nightfall.\n\n'
        'The astronomer needs the complete delivery: lenses, charts and a carefully packed telescope.')


class JobPreview(Scene):
    background_color = (12, 21, 32, 255)

    def __init__(self):
        self.shown, self.large, self.long = False, False, False
        self.accepted = 0

    def on_enter(self):
        self.refresh()

    def update(self, dt):
        if self.display != self.game.window_size:
            self.refresh()

    def refresh(self):
        self.ui.clear()
        self.display = self.game.window_size
        self.game.theme.set_text_style('job', TextStyle(20 if self.large else 14,
                                                       (235, 241, 246, 255), 'Georgia' if self.large else 'Arial'))
        self.card = Column(Label('Observatory courier' if self.long else 'A letter home', font_size=23),
                           Label(LONG if self.long else SHORT, width=330, wrap=True, text_style='job'),
                           Button('Accept job', shortcut='A', on_click=self.accept), spacing=16,
                           style=Style(padding=20, radius=12, background_color=(28, 43, 58, 255)))
        self.measured = self.measure(self.card)
        if self.shown:
            # The card grows upwards; all complete content stays above the controls.
            self.ui.add(Column(self.card, anchor=Anchor.TOP_LEFT,
                               margin=(35, round(self.game.height - 105 - self.measured[1]))))
        self.ui.add(Row(Button('Preview', shortcut='P', on_click=lambda: self.toggle('shown')),
                        Button('Description', shortcut='T', on_click=lambda: self.toggle('long')),
                        Button('Font', shortcut='F', on_click=lambda: self.toggle('large')),
                        Button('Quit', shortcut='Esc', on_click=self.game.quit), spacing=16,
                        anchor=Anchor.BOTTOM_LEFT, margin=(35, 30)))

    def toggle(self, name):
        setattr(self, name, not getattr(self, name))
        self.refresh()

    def accept(self):
        self.accepted += 1

    def draw(self):
        self.draw_text('A preview that fits', 35, 35, font_size=30, color=(238, 197, 109, 255))
        self.draw_text('Measure before showing. Change the text or font; the card keeps its place above the controls.',
                       35, 86, font_size=14)
        self.draw_text(f'Accepted jobs: {self.accepted}', 485, 175, font_size=22)
        self.draw_text(f'Preview size: {self.measured[0]} × {self.measured[1]}', 485, 220, font_size=18)
        self.draw_text('Press A while hidden: no job is accepted.', 485, 265, font_size=14)


def verify(output):
    from pyglet.window import key, mouse
    output.mkdir(parents=True, exist_ok=True)
    sources = [*ROOT.glob('saga2d/**/*.py'), Path(__file__)]
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    inputs, layouts = 0, []
    with TemporaryDirectory(prefix='saga2d-ui-measurement-') as directory:
        game = Game('UI measurement', resolution=(900, 760), visible=False, save_dir=Path(directory) / 'saves')
        scene = JobPreview()

        def press(symbol):
            nonlocal inputs
            game.backend.window.dispatch_event('on_key_press', symbol, 0)
            game.backend.window.dispatch_event('on_key_release', symbol, 0)
            game.tick(1 / 60)
            inputs += 1

        try:
            game.push(scene)
            game.tick(1 / 60)
            press(key.A)
            assert scene.accepted == 0 and scene.card.parent is None
            press(key.P)
            for size in ((900, 760), (720, 608), (1440, 900)):
                game.set_window_size(size)
                for _ in range(3): game.tick(1 / 60)
                for long in (False, True):
                    if scene.long != long: press(key.T)
                    for large in (False, True):
                        if scene.large != large: press(key.F)
                        assert scene.card.bounds[2:] == scene.measured
                        x, y, width, height = scene.card.bounds
                        assert y >= 125 and y + height <= game.height - 100
                        for component in scene.card.walk():
                            cx, cy, cw, ch = component.bounds
                            assert x <= cx and y <= cy and cx + cw <= x + width and cy + ch <= y + height
                        layouts.append({'window': size, 'long': long, 'large': large, 'measured': scene.measured})
                        if size == (900, 760) and large:
                            game.backend.capture_frame().save(output / ('long.png' if long else 'short.png'))
            press(key.A)
            control = scene.card.find(lambda c: isinstance(c, Button))
            x, y, width, height = control.bounds
            window = game.backend.window
            scale = min(window.width / game.width, window.height / game.height)
            px = (window.width - game.width * scale) / 2 + (x + width / 2) * scale
            py = (window.height - game.height * scale) / 2 + (game.height - y - height / 2) * scale
            window.dispatch_event('on_mouse_press', round(px), round(py), mouse.LEFT, 0)
            window.dispatch_event('on_mouse_release', round(px), round(py), mouse.LEFT, 0)
            game.tick(1 / 60); inputs += 1
            assert scene.accepted == 2
            press(key.P); press(key.A)
            assert scene.accepted == 2 and scene.card.parent is None
            assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha for path, sha in hashes.items())
            report = {'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                      'source_sha256': hashes, 'layouts': layouts, 'input_activations': inputs, 'accepted_jobs': scene.accepted}
            (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
            print(f'Native unattached measurement passed: {len(layouts)} layouts / {inputs} inputs')
        finally:
            game.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('/tmp/saga2d-ui-measurement'))
    args = parser.parse_args()
    if args.verify:
        verify(args.output)
    else:
        Game('UI measurement', resolution=(900, 760)).run(JobPreview())
