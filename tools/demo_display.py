"""A fixed-canvas display example and bounded native acceptance check.

    uv run python tools/demo_display.py
    uv run python tools/demo_display.py --verify --out /tmp/saga2d-display

F11 toggles fullscreen. Keys 1/2/3 select windowed sizes. Drag the native
window border, then toggle fullscreen twice: the actual size is restored.
"""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SAGA2D_SILENT', '1')

from PIL import Image
from saga2d import Anchor, Button, Camera, Game, Scene, Sprite  # noqa: E402


class Display(Scene):
    background_color = (5, 8, 15, 255)
    controls = {'f11': 'toggle', '1': 'small', '2': 'normal', '3': 'letterbox', 'escape': 'quit'}

    def on_enter(self):
        self.clicks = 0
        self.last_world = None
        self.camera = Camera(self.game.resolution, zoom=1.5)
        self.targets = []
        for name, anchor in [('Top left', Anchor.TOP_LEFT), ('Top right', Anchor.TOP_RIGHT),
                             ('Bottom left', Anchor.BOTTOM_LEFT), ('Bottom right', Anchor.BOTTOM_RIGHT)]:
            self.targets.append(self.ui.add(Button(name, on_click=self.hit, width=184, height=66,
                                                    anchor=anchor, margin=28)))
        self.game.assets.image_from_pil('display-target', Image.new('RGBA', (24, 24), (255, 205, 99, 255)))
        self.add_sprite(Sprite('display-target', position=(440, 335), size=(24, 24)))

    def hit(self):
        self.clicks += 1

    def toggle(self):
        self.game.set_fullscreen(not self.game.fullscreen)

    def small(self):
        self.game.set_window_size((960, 600))

    def normal(self):
        self.game.set_window_size((1280, 800))

    def letterbox(self):
        self.game.set_window_size((1000, 800))

    def quit(self):
        self.game.quit()

    def handle_input(self, event):
        if event.type == 'click':
            self.last_world = (event.world_x, event.world_y)
            return True
        return False

    def draw(self):
        for x in range(0, 900, 40):
            self.draw_line(x, 0, x, 540, (22, 39, 52, 255), space='world')
        for y in range(0, 560, 40):
            self.draw_line(0, y, 860, y, (22, 39, 52, 255), space='world')
        self.draw_rect(245, 195, 790, 238, (20, 33, 48, 255), radius=12)
        self.draw_text('One canvas. Any window.', 280, 236, font_size=34)
        self.draw_text(f'Logical canvas: {self.game.width} × {self.game.height}', 282, 292, font_size=24)
        width, height = self.game.window_size
        mode = 'Fullscreen' if self.game.fullscreen else 'Windowed'
        self.draw_text(f'{mode}: {width} × {height}  ·  Button hits: {self.clicks}', 282, 336, font_size=24)
        self.draw_text('F11: fullscreen  ·  1: 960×600  ·  2: 1280×800  ·  3: 1000×800', 282, 388, font_size=18)
        self.draw_text('Gold square: retained world sprite at (440, 335), zoom 1.5', 640, 565,
                       font_size=20, anchor_x='center')
        self.draw_text('Click each corner. Resize the OS window. Toggle fullscreen twice.', 640, 623,
                       font_size=19, anchor_x='center')
        self.draw_text('Esc closes the example. Game settings and logical text scale stay game-owned.', 640, 659,
                       font_size=15, anchor_x='center')
        for x, y, width, height in [(0, 0, 1280, 3), (0, 797, 1280, 3), (0, 0, 3, 800), (1277, 0, 3, 800)]:
            self.draw_rect(x, y, width, height, (79, 191, 177, 255))


def verify(out: Path):
    from pyglet.window import key, mouse

    out.mkdir(parents=True, exist_ok=True)
    game = Game('Saga2D display verification', resolution=(1280, 800), visible=False)
    observations = []

    def press(symbol):
        game.backend.window.dispatch_event('on_key_press', symbol, 0)
        game.backend.window.dispatch_event('on_key_release', symbol, 0)
        game.tick(1 / 60)

    def click(x, y):
        window = game.backend.window
        scale = min(window.width / 1280, window.height / 800)
        px = (window.width - 1280 * scale) / 2 + x * scale
        py = (window.height - 800 * scale) / 2 + (800 - y) * scale
        window.dispatch_event('on_mouse_press', round(px), round(py), mouse.LEFT, 0)
        window.dispatch_event('on_mouse_release', round(px), round(py), mouse.LEFT, 0)
        game.tick(1 / 60)

    def check(name):
        for _ in range(3):
            game.tick(1 / 60)
        assert game.resolution == (1280, 800)
        before = game.scene.clicks
        for target in game.scene.targets:
            x, y, width, height = target.bounds
            click(x + width / 2, y + height / 2)
        assert game.scene.clicks == before + 4
        click(660, 502.5)
        assert all(abs(actual - expected) < 1 for actual, expected in zip(game.scene.last_world, (440, 335)))
        image = game.backend.capture_frame().convert('RGB')
        image.save(out / f'{name}.png')
        scale = min(image.width / 1280, image.height / 800)
        offset_x, offset_y = (image.width - 1280 * scale) / 2, (image.height - 800 * scale) / 2

        def pixel(x, y):
            return image.getpixel((round(offset_x + x * scale), round(offset_y + y * scale)))

        for point in ((1, 400), (1278, 400), (640, 1), (640, 798)):
            assert pixel(*point) == (79, 191, 177), (name, 'canvas border', point, pixel(*point))
        assert pixel(665, 507) == (255, 205, 99), (name, 'retained world sprite', pixel(665, 507))
        if offset_y > 20 * scale:
            assert pixel(660, 805) == (5, 8, 15), (name, 'world drawing leaked into letterbox')
        observations.append({'name': name, 'fullscreen': game.fullscreen, 'window_size': game.window_size,
                             'framebuffer_size': game.backend.window.get_framebuffer_size(),
                             'logical_canvas': game.resolution, 'button_hits': game.scene.clicks})

    try:
        game.push(Display())
        check('initial')
        press(key._1)
        assert game.window_size == (960, 600)
        check('small')
        press(key._3)
        assert game.window_size == (1000, 800)
        check('letterboxed')
        # Native resize goes around Game, as dragging the OS window border does.
        game.backend.window.set_size(940, 720)
        game.tick(1 / 60)
        actual_windowed = game.window_size
        assert actual_windowed == (940, 720)
        check('os-resized')
        press(key.F11)
        assert game.fullscreen
        check('fullscreen')
        press(key.F11)
        assert not game.fullscreen and game.window_size == actual_windowed
        check('restored')
        press(key.F11)
        press(key._2)
        assert not game.fullscreen and game.window_size == (1280, 800)
        check('size-exits-fullscreen')
    finally:
        game.close()
    game = Game('Saga2D fullscreen startup verification', resolution=(1280, 800), fullscreen=True, visible=False)
    try:
        game.push(Display())
        assert game.fullscreen
        check('fullscreen-start')
        press(key.F11)
        assert not game.fullscreen and game.window_size == (1280, 800)
        check('fullscreen-start-restored')
    finally:
        game.close()
    (out / 'report.json').write_text(json.dumps(observations, indent=2) + '\n')
    print(f'Native resize/fullscreen restoration, letterboxed UI/world input and captures passed: {out}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--out', type=Path, default=Path('/tmp/saga2d-display'))
    args = parser.parse_args()
    if args.verify:
        verify(args.out)
    else:
        Game('Saga2D display example', resolution=(1280, 800)).run(Display())
