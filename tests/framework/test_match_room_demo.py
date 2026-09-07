"""A tiny independent game crosses real room sockets through ordinary scene input."""

from contextlib import contextmanager
import os
from pathlib import Path
import select
import subprocess
import sys
import time

from saga2d import Button, Game, MatchLobby
from saga2d.online import OnlineClient


@contextmanager
def counter_server():
    process = subprocess.Popen(
        [sys.executable, 'tools/demo_match_room.py', '--serve', '--port', '0'],
        cwd=Path(__file__).resolve().parents[2], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env={**os.environ, 'PYTHONUNBUFFERED': '1'},
    )
    try:
        readable, _, _ = select.select([process.stdout, process.stderr], [], [], 5)
        assert process.stdout in readable, 'The loopback counter server did not start'
        line = process.stdout.readline().strip()
        assert line.startswith('LISTENING ws://127.0.0.1:'), line
        yield line.removeprefix('LISTENING ')
    finally:
        process.terminate()
        try:
            _, errors = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            _, errors = process.communicate(timeout=5)
        assert 'Traceback (most recent call last)' not in errors, errors


def test_counter_menu_handoff_keeps_polling_under_help_and_closes_its_seat(tmp_path, monkeypatch):
    """Menu creation, two seats, input, overlay polling and permanent cleanup work together."""
    from tools.demo_match_room import CounterScene, GAME_ID, make_menu

    with counter_server() as endpoint:
        monkeypatch.setenv('SAGA2D_SERVER_URL', endpoint)
        game = Game('Counter room', backend='mock', resolution=(960, 720), save_dir=tmp_path / 'saves')
        guest = None

        def wait(until):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if game.scenes:
                    game.tick(1 / 30)
                if guest is not None:
                    guest.poll()
                if until():
                    return
                time.sleep(1 / 30)
            raise AssertionError('The local counter room did not reach the expected state')

        def click(label):
            control = game.scene.ui.find(lambda item: isinstance(item, Button) and item.text == label)
            assert control is not None and control.enabled
            x, y, width, height = control.bounds
            game.backend.inject_click(x + width / 2, y + height / 2)
            game.backend.inject_release(x + width / 2, y + height / 2)
            game.tick(1 / 30)

        try:
            game.push(make_menu())
            game.tick(1 / 30)
            click('Create room')
            assert isinstance(game.scene, MatchLobby)
            lobby = game.scene
            wait(lambda: bool(lobby.session.room))
            assert not lobby.session.ready
            guest = OnlineClient(GAME_ID, endpoint=endpoint, room=lobby.session.room)
            wait(lambda: isinstance(game.scene, CounterScene) and guest.ready)
            room = game.scene
            assert game.scenes == [room] and room.session is lobby.session
            assert room.session.player == 0 and guest.player == 1
            click('Add one')
            wait(lambda: guest.state['counts'] == room.session.state['counts'] == [1, 0])
            assert room.session.state == {'counts': [1, 0], 'you': 0}
            click('Help')
            assert not room.session.closed
            guest.submit({'action': 'add'})
            wait(lambda: room.session.state['counts'] == [1, 1])
            game.backend.inject_key('escape')
            game.tick(1 / 30)
            assert game.scene is room and room.session.ready
            assert any('Seat 2: 1' in item['text'] for item in game.backend.texts)
            game.close()
            assert room.session.closed and not game.backend.is_running
            wait(lambda: not guest.ready)
        finally:
            game.close()
            if guest is not None:
                guest.close()
