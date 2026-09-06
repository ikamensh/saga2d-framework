"""Measure one real window at a time; demonstrate pacing independently of either game.

    uv run python tools/verify_frame_pacing.py --output /tmp/frame-pacing

The hidden verification window receives native focus/visibility callbacks to
exercise active, unfocused, minimized and restored pacing without taking focus.
--scene shard adds Shardbound's real map under the same observation overlay.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path.cwd()  # Run this same probe in old/new checkouts for a paired comparison.
sys.path.insert(0, str(ROOT))
os.environ['SAGA2D_SILENT'] = '1'

from saga2d import Game, Scene


class Probe(Scene):
    transparent = True
    pause_below = False
    controls = {'space': 'press'}
    phases = ('active', 'unfocused', 'hidden', 'restored')

    def __init__(self, seconds, output, background=None):
        super().__init__()
        self.seconds, self.output, self.background = seconds, output, background
        self.rows = []
        self.presses = 0
        self.game_time = 0

    def press(self):
        self.presses += 1

    def on_enter(self):
        self.phase = -1
        self.next_phase()

    def next_phase(self):
        self.phase += 1
        if self.phase == len(self.phases):
            self.phase -= 1
            self.game.quit()
            return
        for name in {'active': ('on_show', 'on_activate'),
                     'unfocused': ('on_deactivate',),
                     'hidden': ('on_hide', 'on_activate'),
                     'restored': ('on_show', 'on_activate')}[self.phases[self.phase]]:
            self.game.backend.window.dispatch_event(name)
        from pyglet.window import key
        self.game.backend.window.dispatch_event('on_key_press', key.SPACE, 0)
        self.game.backend.window.dispatch_event('on_key_release', key.SPACE, 0)
        self.started, self.cpu_started = time.monotonic(), time.process_time()
        self.frames = 0

    def update(self, dt):
        self.game_time += dt
        self.frames += 1
        if self.frames == 2:
            self.game.backend.capture_frame().save(self.output / f'{self.phases[self.phase]}.png')
        elapsed = time.monotonic() - self.started
        if elapsed >= self.seconds:
            self.rows.append(dict(phase=self.phases[self.phase], seconds=elapsed, frames=self.frames,
                                  fps=self.frames / elapsed,
                                  cpu_percent=100 * (time.process_time() - self.cpu_started) / elapsed))
            self.next_phase()

    def draw(self):
        if self.background is None:
            self.draw_rect(0, 0, self.game.width, self.game.height, (15, 27, 34, 255))
            self.draw_circle(120 + self.game_time * 40 % 900, 390, 28, (100, 207, 164, 255))
            self.draw_text('Saga2D frame pacing', 40, 80, font_size=32)
            self.draw_text('A scene needs no timer or sleep loop of its own.', 40, 135, font_size=17)
            self.draw_text(self.phases[self.phase], 40, 180, font_size=17)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=2)
    parser.add_argument('--scene', choices=('demo', 'shard'), default='demo')
    parser.add_argument('--check', action='store_true', help='require60/15FPS pacing (omit for a pre-fix measurement)')
    args = parser.parse_args()
    if not 0 < args.seconds <= 30:
        parser.error('seconds must be greater than zero and at most 30 per phase')
    args.output.mkdir(parents=True, exist_ok=False)
    sources = [*ROOT.glob('saga2d/**/*.py'), *ROOT.glob('eador/**/*.py')]
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    background = None
    if args.scene == 'shard':
        from eador.app import create_game
        from eador.model import State
        from eador.scene import ShardScene
        game = create_game('Frame pacing check', visible=False, save_dir=args.output / 'saves')
        background = ShardScene(State.new(7))
        game.push(background)
    else:
        game = Game('Frame pacing example', visible=False)
    probe = Probe(args.seconds, args.output, background)
    game.run(probe)
    report = dict(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  working_tree_status=subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).splitlines(),
                  source_sha256=hashes,
                  source_unchanged=all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest for path, digest in hashes.items()),
                  platform=platform.platform(), scene=args.scene, rows=probe.rows,
                  game_time=probe.game_time, input_presses=probe.presses,
                  closed=game.backend.window is None,
                  scope='One hidden native window; synthetic native focus/visibility events; no battery measurement.')
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'source_sha256'}, indent=2))
    if args.check:
        assert report['closed'] and report['input_presses'] == 4
        for row in report['rows']:
            limit = 60 if row['phase'] in ('active', 'restored') else 15
            assert row['fps'] <= limit + 2, row
        assert abs(report['game_time'] - sum(row['seconds'] for row in report['rows'])) < .5


if __name__ == '__main__':
    main()
