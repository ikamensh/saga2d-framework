"""Drive and close two independent sessions without owning a framework loop.

    uv run python tools/demo_game_close.py
    uv run python tools/demo_game_close.py --backend pyglet

The optional native check opens hidden windows and advances at most 30 FPS.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from saga2d import Game, Scene
from tools.native_frames import tick


class Counter(Scene):
    frames = 0

    def update(self, dt):
        self.frames += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('mock', 'pyglet'), default='mock')
    args = parser.parse_args()
    for session in range(2):
        game = Game(f'Explicit session {session + 1}', backend=args.backend,
                    visible=False, resolution=(320, 200))
        scene = Counter()
        try:
            game.push(scene)
            for _ in range(3):
                if args.backend == 'pyglet':
                    tick(game)
                else:
                    game.tick(1 / 60)
        finally:
            game.close()
        assert scene.frames == 3 and scene.game is None
        if args.backend == 'pyglet':
            assert game.backend.window is None
        else:
            assert not game.backend.is_running
    print(f'{args.backend}: two explicitly ticked sessions closed; six updates completed.')


if __name__ == '__main__':
    main()
