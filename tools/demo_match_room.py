"""An independent two-seat counter: local authority, shared lobby, ordinary UI.

Start ``--serve`` in one terminal, then launch this file in two more terminals.
Create a room in the first window; enter its code and join in the second.
All Online traffic uses the explicit loopback port, never the hosted service.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from saga2d import Anchor, Button, Column, CommandError, Game, Label, MatchLobby, MatchMenu, Scene, Style
from saga2d.online import OnlineClient


GAME_ID = 'counter-demo-v1'
PANEL = Style(padding=24, background_color=(22, 32, 48, 255), radius=10)


class CounterMatch:
    """The entire game: a valid order adds one to the authenticated sender's counter."""

    def __init__(self):
        self.counts = [0, 0]

    def apply(self, player, command):
        if command != {'action': 'add'}:
            raise CommandError('Choose Add one.')
        self.counts[player] += 1

    def snapshot(self, player):
        return {'counts': self.counts.copy(), 'you': player}


class CounterScene(Scene):
    def __init__(self, session, match=None):
        # A LAN host receives match; guests and both Online seats receive None.
        # This counter needs no autonomous simulation, so only apply changes it.
        self.session = session
        self.message = ''

    def on_enter(self):
        self.add_button = Button('Add one', shortcut='Space', on_click=self.add)
        self.ui.add(Column(
            Label(f'Counter room · you are seat {self.session.player + 1}', font_size=26),
            *(Label(lambda seat=seat: f'Seat {seat + 1}: {self.session.state["counts"][seat]}',
                    font_size=22) for seat in range(2)),
            Label(lambda: self.message or self.session.error or
                  ('Both seats connected' if self.session.ready else 'Waiting for your partner'),
                  width=600, wrap=True),
            self.add_button,
            Button('Help', shortcut='H', on_click=lambda: self.game.push(Help())),
            Button('Quit', shortcut='Esc', on_click=self.game.quit),
            width=650, spacing=18, anchor=Anchor.CENTER, style=PANEL))
        # An update hook pauses under a modal; this owned timer keeps the connection alive.
        self.every(1 / 30, self.poll)

    def poll(self):
        self.session.poll()
        self.add_button.enabled = self.session.ready

    def add(self):
        try:
            self.session.submit({'action': 'add'}, revision=self.session.revision)
        except CommandError as error:
            self.message = str(error)
        else:
            self.message = ''

    def on_close(self):
        self.session.close()


class Help(Scene):
    def on_enter(self):
        self.ui.add(Column(
            Label('The other seat can still add while this panel is open.', width=540, wrap=True),
            Label('Closing Help preserves the connection. Quitting closes this client.', width=540, wrap=True),
            Button('Close', shortcut='Esc', on_click=self.game.pop),
            width=590, spacing=20, anchor=Anchor.CENTER, style=PANEL))


def make_menu():
    return MatchMenu('Independent counter room', GAME_ID, CounterMatch, CounterScene,
                     create_options=dict)


def online_lobby(endpoint, *, room=None):
    """The same scene factory, with an explicit OnlineClient instead of menu input."""
    session = OnlineClient(GAME_ID, endpoint=endpoint, room=room, options={})
    return MatchLobby(session, lambda connection: CounterScene(connection, None), title='Counter room')


class CounterRoom:
    """One ephemeral loopback room, solely to make this example self-contained.

    This is demo policy, not a reusable server: one room, two counters, no disk
    storage. Restart --serve to start a new room. Claimed seats can resume while
    this process lives. No reference-game catalog or server package is imported.
    """

    def __init__(self):
        self.match = None
        self.peers = [None, None]
        self.tokens = [None, None]
        self.revision = 0
        self.lock = asyncio.Lock()

    def enter(self, hello):
        if not isinstance(hello, dict) or hello.get('game') != GAME_ID or hello.get('protocol') != 1:
            raise CommandError('Use the counter demo client and protocol 1.')
        kind = hello.get('type')
        if kind == 'create':
            if self.match is not None:
                raise CommandError('This demo has one room. Join counter, or restart its server.')
            if hello.get('options', {}) != {}:
                raise CommandError('The counter has no creation options.')
            self.match = CounterMatch()
            player = 0
        elif kind in ('join', 'resume') and hello.get('room') == 'counter' and self.match is not None:
            if kind == 'join':
                if self.tokens[1] is not None:
                    raise CommandError('Seat 2 is claimed. Rejoin with its saved credential.')
                player = 1
            else:
                token = hello.get('resume_token')
                player = next((seat for seat, saved in enumerate(self.tokens) if saved and saved == token), None)
                if player is None or self.peers[player] is not None:
                    raise CommandError('The saved seat is invalid or still connected.')
        else:
            raise CommandError('Create a room first, then join counter.')
        self.tokens[player] = self.tokens[player] or secrets.token_urlsafe(24)
        return player

    async def publish(self):
        from websockets.exceptions import ConnectionClosed
        self.revision += 1
        for seat, peer in enumerate(self.peers):
            if peer is not None:
                try:
                    await peer.send(json.dumps({'type': 'state', 'revision': self.revision,
                                                'ready': all(self.peers), 'state': self.match.snapshot(seat)}))
                except ConnectionClosed:
                    pass  # That peer's handler removes it and publishes the disconnected state.

    async def handle(self, websocket):
        from websockets.exceptions import ConnectionClosed
        player = None
        try:
            hello = json.loads(await websocket.recv())
            async with self.lock:
                player = self.enter(hello)
                self.peers[player] = websocket
                await websocket.send(json.dumps({'type': 'welcome', 'room': 'counter', 'player': player,
                                                 'resume_token': self.tokens[player]}))
                await self.publish()
            async for raw in websocket:
                async with self.lock:
                    try:
                        message = json.loads(raw)
                        if not isinstance(message, dict) or message.get('type') != 'command':
                            raise CommandError('Send an Add one command.')
                        if not all(self.peers):
                            raise CommandError('Waiting for your partner.')
                        if message.get('revision') not in (None, self.revision):
                            raise CommandError('State changed. Try Add one again.')
                        self.match.apply(player, message.get('command'))
                    except (CommandError, json.JSONDecodeError) as error:
                        await websocket.send(json.dumps({'type': 'error', 'error': str(error)}))
                    else:
                        await self.publish()
        except (CommandError, json.JSONDecodeError) as error:
            await websocket.send(json.dumps({'type': 'reject', 'error': str(error)}))
        except ConnectionClosed:
            pass
        finally:
            if player is not None:
                async with self.lock:
                    self.peers[player] = None
                    await self.publish()


async def serve_counter(port):
    from websockets.asyncio.server import serve
    room = CounterRoom()
    async with serve(room.handle, '127.0.0.1', port, max_size=1024, max_queue=4,
                     ping_interval=10, ping_timeout=10, close_timeout=1) as server:
        print(f'LISTENING ws://127.0.0.1:{server.sockets[0].getsockname()[1]}', flush=True)
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', help='serve one in-memory room on loopback')
    parser.add_argument('--port', type=int, default=8766, help='local WebSocket port (server may use 0)')
    parser.add_argument('--join', metavar='CODE', help='join directly through OnlineClient and MatchLobby')
    args = parser.parse_args()
    if not (0 if args.serve else 1) <= args.port <= 65535:
        parser.error('Choose a port from 1 to 65535, or 0 for an OS-assigned server port.')
    if args.serve and args.join:
        parser.error('--serve and --join are separate processes.')
    if args.serve:
        try:
            asyncio.run(serve_counter(args.port))
        except KeyboardInterrupt:
            pass
        return
    endpoint = f'ws://127.0.0.1:{args.port}'
    os.environ['SAGA2D_SERVER_URL'] = endpoint  # MatchMenu's existing endpoint configuration seam.
    with TemporaryDirectory(prefix='saga2d-counter-room-') as directory:
        game = Game('Independent counter room', resolution=(960, 720), save_dir=Path(directory) / 'saves')
        try:
            game.run(online_lobby(endpoint, room=args.join) if args.join else make_menu(), fps=30)
        finally:
            game.close()


if __name__ == '__main__':
    main()
