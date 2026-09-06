"""Host/join UI shared by games using MatchHost/MatchClient.

Games provide a match factory and a scene factory; their rules and presentation
stay in those factories. Rooms are direct TCP connections on LAN/private VPN.
"""
from saga2d.network import MatchHost, MatchClient
from saga2d.scene import Scene
from saga2d.ui import Anchor, Button, Column, Label, Row, Style

_PANEL = Style(background_color=(18, 28, 41, 255), padding=28, radius=10)


class MatchLobby(Scene):
    controls = {'escape': 'leave'}

    def __init__(self, session, make_scene, *, title='Multiplayer'):
        self.session, self.make_scene, self.title = session, make_scene, title
        self._transferred = False

    def on_enter(self):
        host = isinstance(self.session, MatchHost)
        instructions = (f'Listening on port {self.session.address[1]}\nRoom code: {self.session.token}\n'
                        'Share your LAN or VPN address and this code with your partner.' if host else
                        'Connecting to the host. Both games must use the same version.')
        self.ui.add(Column(Label(self.title, font_size=28), Label('Waiting for partner' if host else 'Joining match', font_size=20),
                           Label(instructions, width=580, wrap=True, font_size=16),
                           Label(lambda: self.session.error, width=580, wrap=True, font_size=15),
                           Button('Cancel', shortcut='Esc', on_click=self.leave, width=240),
                           width=640, spacing=24, anchor=Anchor.CENTER, style=_PANEL))

    def update(self, dt):
        self.session.poll()
        if self.session.ready:
            scene = self.make_scene(self.session)
            self._transferred = True
            try:
                self.game.clear_and_push(scene)
            except BaseException:
                self.session.close()
                raise

    def leave(self):
        self.game.pop() if len(self.game.scenes) > 1 else self.game.quit()

    def on_close(self):
        if not self._transferred:
            self.session.close()


class MatchMenu(Scene):
    """A small ASCII address/code form with keyboard and clickable focus controls."""
    controls = {'escape': 'leave', 'tab': 'next_field', 'return': 'join'}

    def __init__(self, title, game_id, create_match, create_scene):
        self.title, self.game_id = title, game_id
        self.create_match, self.create_scene = create_match, create_scene
        self.fields = ['127.0.0.1', '7777', '']
        self.focus = 0
        self.message = ''
        self._replace_field = True

    def on_enter(self):
        rows = []
        for i, name in enumerate(('Host address', 'Port', 'Room code')):
            rows.append(Button(lambda i=i, name=name: f'{"> " if i == self.focus else ""}{name}: {self.fields[i] or "(type here)"}',
                               on_click=lambda i=i: self.select_field(i), width=580))
        self.ui.add(Column(Label(self.title, font_size=28),
                           Label('Two players · Direct LAN / private VPN', font_size=17),
                           Label('Host a room, then share your address, port and room code.\nTo join, click a field and type; Tab moves to the next field.',
                                 width=580, wrap=True, font_size=15),
                           *rows,
                           Row(Button('Host room', on_click=self.host, width=280),
                               Button('Join room', shortcut='Enter', on_click=self.join, width=280), spacing=20),
                           Label(lambda: self.message, width=580, wrap=True, font_size=15),
                           Button('Back', shortcut='Esc', on_click=self.leave, width=240),
                           width=640, spacing=18, anchor=Anchor.CENTER, style=_PANEL))

    def select_field(self, index):
        self.focus = index
        self._replace_field = True

    def next_field(self):
        self.select_field((self.focus + 1) % 3)

    def handle_input(self, event):
        if event.type != 'key_press' or not event.key or event.ctrl or event.meta:
            return False
        if event.key in ('backspace', 'delete'):
            self.fields[self.focus] = '' if self._replace_field else self.fields[self.focus][:-1]
        else:
            char = {'period': '.', 'minus': '-', 'underscore': '_'}.get(event.key, event.key)
            if len(char) != 1 or char not in 'abcdefghijklmnopqrstuvwxyz0123456789.-_':
                return False
            if self.focus == 1 and not char.isdigit():
                return True
            value = '' if self._replace_field else self.fields[self.focus]
            if len(value) < 128:
                self.fields[self.focus] = value + char
        self._replace_field = False
        return True

    def _port(self):
        if not self.fields[1].isdigit() or not 1 <= int(self.fields[1]) <= 65535:
            raise ValueError('Port must be between 1 and 65535.')
        return int(self.fields[1])

    def host(self):
        try:
            port = self._port()
            match = self.create_match()
            session = MatchHost(self.game_id, match.apply, match.snapshot,
                                address=('0.0.0.0', port), token=self.fields[2] or None)
        except (OSError, ValueError) as exc:
            self.message = str(exc)
            return
        self.fields[2] = session.token
        self.game.push(MatchLobby(session, lambda connection: self.create_scene(connection, match), title=self.title))

    def join(self):
        try:
            port = self._port()
            if not self.fields[0] or not self.fields[2]:
                raise ValueError('Enter the host address and room code first.')
            session = MatchClient(self.game_id, (self.fields[0], port), token=self.fields[2])
        except (OSError, ValueError) as exc:
            self.message = str(exc)
            return
        self.game.push(MatchLobby(session, lambda connection: self.create_scene(connection, None), title=self.title))

    def leave(self):
        self.game.pop() if len(self.game.scenes) > 1 else self.game.quit()


def add_match_arguments(parser):
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--host', action='store_true', help='host a two-player LAN/VPN match')
    group.add_argument('--join', metavar='ADDRESS', help='join a LAN/VPN host')
    parser.add_argument('--port', type=int, default=7777, help='multiplayer TCP port (default 7777)')
    parser.add_argument('--room', help='room code (required to join; generated when hosting)')


def match_from_arguments(args, parser, *, title, game_id, create_match, create_scene):
    """Return a lobby for an explicit CLI host/join request, or None for solo play."""
    if not (args.host or args.join):
        return None
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if args.join:
        if not args.room:
            parser.error('--join requires --room CODE')
        session = MatchClient(game_id, (args.join, args.port), token=args.room)
        make_scene = lambda connection: create_scene(connection, None)
    else:
        match = create_match()
        session = MatchHost(game_id, match.apply, match.snapshot, address=('0.0.0.0', args.port), token=args.room)
        print(f'{title}: port {session.address[1]}, room code {session.token}', flush=True)
        make_scene = lambda connection: create_scene(connection, match)
    return MatchLobby(session, make_scene, title=title)
