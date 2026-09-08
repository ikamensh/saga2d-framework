"""Room-code online play and explicit direct LAN play shared by all three games.

Games supply server creation options, a LAN match factory and a scene factory.
Online creators and guests both receive their authoritative state from the server.
"""
import webbrowser

from saga2d.network import MatchHost, MatchClient
from saga2d.scene import Scene
from saga2d.settings import Settings
from saga2d.ui import Anchor, Button, Column, Label, Row, Style

_PANEL = Style(background_color=(18, 28, 41, 255), padding=28, radius=10)


def _last_room(game):
    return Settings(game.data_dir / 'online-room.json',
                    {'game_id': '', 'endpoint': '', 'room': '', 'resume_token': ''})


def _duration(seconds):
    for unit, size in (('day', 86400), ('hour', 3600), ('minute', 60)):
        count = round(seconds / size)
        if count >= 2 or unit == 'minute':
            return f'{count} {unit}{"s" if count != 1 else ""}'


def open_page(url):
    """Show a website page in the player's browser without blocking the game."""
    webbrowser.open_new_tab(url)


class MatchLobby(Scene):
    controls = {'escape': 'leave'}

    def __init__(self, session, make_scene, *, title='Multiplayer'):
        self.session, self.make_scene, self.title = session, make_scene, title
        self._transferred = False
        self._reported_room = False
        self._saved_room = False
        self._offered_update = False

    def on_enter(self):
        self._build()

    def _build(self):
        self.ui.clear()
        controls = []
        if getattr(self.session, 'online', False):
            if self.session.incompatible:
                controls.append(Button('Open download page', on_click=self.open_download, width=280))
            else:
                self.copy_button = Button('Copy room code', on_click=self.copy_room, width=280, enabled=False)
                controls.append(self.copy_button)
        self.ui.add(Column(Label(self.title, font_size=28),
                           Label(self._status, font_size=20),
                           Label(self._instructions, width=580, wrap=True, font_size=18),
                           Label(lambda: self.session.error, width=580, wrap=True, font_size=15),
                           *controls,
                           Button('Cancel', shortcut='Esc', on_click=self.leave, width=240),
                           width=640, spacing=24, anchor=Anchor.CENTER, style=_PANEL))

    def open_download(self):
        from saga2d.release import home_page
        open_page(home_page())

    def _status(self):
        if self.session.closed:
            return 'Update required' if self.session.incompatible else 'Could not connect'
        if getattr(self.session, 'online', False):
            return ('Waiting for your partner' if self.session.state is not None else
                    'Connecting to the online server')
        return 'Waiting for partner' if isinstance(self.session, MatchHost) else 'Joining match'

    def _instructions(self):
        if getattr(self.session, 'online', False):
            if self.session.incompatible:
                return 'This version of the game cannot play online any more. Install the current release and try again.'
            if self.session.state is not None:
                return (f'Room code: {self.session.room}\n'
                        'Copy the code and send it to your friend. They paste it in Multiplayer and choose Join room.\n'
                        'The match starts when you both connect. '
                        f'Your seats are kept for {_duration(self.session.retention)} without both players.')
            if self.session.room:
                return f'Joining online room {self.session.room}…'
            return 'Creating your online room. You will receive a code to share.'
        if isinstance(self.session, MatchHost):
            return (f'Listening on port {self.session.address[1]}\nRoom code: {self.session.token}\n'
                    'Share your LAN or VPN address and this code with your partner.')
        return 'Connecting to the host. Both games must use the same version.'

    def copy_room(self):
        self.game.backend.set_clipboard_text(self.session.room)
        self.copy_button.text = 'Copied!'

    def update(self, dt):
        self.session.poll()
        confirmed = getattr(self.session, 'online', False) and self.session.state is not None
        if getattr(self.session, 'online', False):
            if self.session.incompatible and not self._offered_update:
                self._offered_update = True
                self._build()
            elif not self.session.incompatible:
                self.copy_button.enabled = confirmed and not self.session.closed
        if confirmed and not self._reported_room:
            print(f'{self.title}: online room {self.session.room}', flush=True)
            self._reported_room = True
        if confirmed and not self._saved_room:
            record = _last_room(self.game)
            if record.error:
                record.reset()  # Preserve a damaged record as a recovery file before saving the new seat.
            for field in ('game_id', 'endpoint', 'room', 'resume_token'):
                record[field] = getattr(self.session, field)
            record.save()
            self._saved_room = True
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
    """Online room-code entry, with an explicit LAN address/code mode."""
    controls = {'escape': 'leave', 'tab': 'next_field', 'return': 'join'}

    def __init__(self, title, game_id, create_match, create_scene, *, create_options=None):
        self.title, self.game_id = title, game_id
        self.create_match, self.create_scene = create_match, create_scene
        self.create_options = create_options or dict
        self.mode = 'online'
        self.fields = ['127.0.0.1', '7777', '']
        self.focus = 2
        self.message = ''
        self._replace_field = True

    def on_enter(self):
        from saga2d.release import UpdateCheck
        self.update_check = UpdateCheck(self.game_id)
        self._shown_update = False
        self.last_room = _last_room(self.game)
        if self.last_room.error:
            self.message = 'Could not read the last online room. You can create or join a new room.'
        self._build_form()

    def update(self, dt):
        if self.update_check.poll() == 'update' and not self._shown_update:
            self._shown_update = True
            self._build_form()

    def open_download(self):
        open_page(self.update_check.page)

    def on_reveal(self):
        self.last_room = _last_room(self.game)
        self._build_form()

    def _build_form(self):
        self.ui.clear()
        names = ('Host address', 'Port', 'Room code')
        rows = []
        for i in ((2,) if self.mode == 'online' else (0, 1, 2)):
            field = Button(lambda i=i: f'{"> " if i == self.focus else ""}{names[i]}: {self.fields[i] or "(type here)"}',
                           on_click=lambda i=i: self.select_field(i), width=390 if self.mode == 'online' else 580)
            rows.append(Row(field, Button('Paste code', on_click=self.paste_code, width=170), spacing=20)
                        if self.mode == 'online' else field)
        rejoin = []
        if (self.mode == 'online' and self.last_room['game_id'] == self.game_id
                and self.last_room['room'] and self.last_room['resume_token']):
            rejoin.append(Button(f"Rejoin last room · {self.last_room['room']}", on_click=self.rejoin, width=580))
        instructions = ('Create a room and share its code with a friend.\n'
                        'To join, copy their code and choose Paste code below.' if self.mode == 'online' else
                        'Play on the same network or a private VPN. Share the host address, port and code.\n'
                        'Click a field and type; Tab moves to the next field.')
        notice = []
        if self.mode == 'online' and self.update_check.status == 'update':
            latest = self.update_check.latest
            notice.append(Row(Label(f"Update available: {latest['name']} {latest['version']}", width=390, wrap=True,
                                    font_size=15),
                              Button('Open download page', on_click=self.open_download, width=170), spacing=20))
        self.ui.add(Column(Label(self.title, font_size=28),
                           Row(Button('Online' + (' · selected' if self.mode == 'online' else ''),
                                      on_click=lambda: self.set_mode('online'), width=280),
                               Button('LAN' + (' · selected' if self.mode == 'lan' else ''),
                                      on_click=lambda: self.set_mode('lan'), width=280), spacing=20),
                           Label(instructions, width=580, wrap=True, font_size=15),
                           *notice,
                           *rows,
                           Row(Button('Create room' if self.mode == 'online' else 'Host room', on_click=self.host, width=280),
                               Button('Join room', shortcut='Enter', on_click=self.join, width=280), spacing=20),
                           *rejoin,
                           Label(lambda: self.message, width=580, wrap=True, font_size=15),
                           Button('Back', shortcut='Esc', on_click=self.leave, width=240),
                           width=640, spacing=18, anchor=Anchor.CENTER, style=_PANEL))

    def set_mode(self, mode):
        self.mode = mode
        self.fields[2] = ''
        self.message = ''
        self.select_field(2 if mode == 'online' else 0)
        self._build_form()

    def select_field(self, index):
        self.focus = index
        self._replace_field = True

    def next_field(self):
        self.select_field(2 if self.mode == 'online' else (self.focus + 1) % 3)

    def paste_code(self):
        code = self.game.backend.get_clipboard_text().strip()
        if not (code and len(code) <= 12 and code.isascii() and code.isalnum()):
            self.message = 'Copy just the room code from your friend, then choose Paste code.'
            return
        self.fields[2] = code.upper()
        self.focus = 2
        self._replace_field = False
        self.message = ''

    def handle_input(self, event):
        if (self.mode == 'online' and event.type == 'key_press' and event.key == 'v'
                and (event.ctrl or event.meta)):
            self.paste_code()
            return True
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
            if self.mode == 'online':
                if not char.isalnum():
                    return True
                char = char.upper()
            value = '' if self._replace_field else self.fields[self.focus]
            if len(value) < (12 if self.mode == 'online' else 128):
                self.fields[self.focus] = value + char
        self._replace_field = False
        return True

    def _port(self):
        if not self.fields[1].isdigit() or not 1 <= int(self.fields[1]) <= 65535:
            raise ValueError('Port must be between 1 and 65535.')
        return int(self.fields[1])

    def host(self):
        try:
            if self.mode == 'online':
                from saga2d.online import OnlineClient
                session = OnlineClient(self.game_id, options=self.create_options())
                match = None
            else:
                port = self._port()
                match = self.create_match()
                session = MatchHost(self.game_id, match.apply, match.snapshot,
                                    address=('0.0.0.0', port), token=self.fields[2] or None)
                self.fields[2] = session.token
        except (OSError, ValueError) as exc:
            self.message = str(exc)
            return
        self.game.push(MatchLobby(session, lambda connection: self.create_scene(connection, match), title=self.title))

    def join(self):
        try:
            if self.mode == 'online':
                if not self.fields[2]:
                    raise ValueError('Enter a room code first.')
                from saga2d.online import OnlineClient
                session = OnlineClient(self.game_id, room=self.fields[2])
            else:
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

    def rejoin(self):
        from saga2d.online import OnlineClient
        record = self.last_room
        try:
            session = OnlineClient(self.game_id, endpoint=record['endpoint'], room=record['room'],
                                   resume_token=record['resume_token'])
        except (OSError, ValueError) as exc:
            self.message = str(exc)
            return
        self.game.push(MatchLobby(session, lambda connection: self.create_scene(connection, None), title=self.title))


def add_match_arguments(parser):
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--online-host', action='store_true', help='create an online two-player room')
    group.add_argument('--online-join', metavar='CODE', help='join an online room by its code')
    group.add_argument('--online-resume', action='store_true', help='rejoin your last online room on this computer')
    group.add_argument('--host', action='store_true', help='host a two-player LAN/VPN match')
    group.add_argument('--join', metavar='ADDRESS', help='join a LAN/VPN host')
    parser.add_argument('--server', metavar='URL', help='online server URL (overrides SAGA2D_SERVER_URL)')
    parser.add_argument('--port', type=int, default=7777, help='LAN multiplayer TCP port (default 7777)')
    parser.add_argument('--room', help='LAN room code (required to join; generated when hosting)')


def match_from_arguments(args, parser, *, title, game_id, create_match, create_scene, create_options=None, game=None):
    """Return an online or LAN lobby for an explicit CLI request, otherwise None."""
    if args.online_resume:
        from saga2d.online import OnlineClient
        record = _last_room(game)
        if record.error or record['game_id'] != game_id or not record['room'] or not record['resume_token']:
            parser.error('No saved online room for this game. Create or join a room first.')
        session = OnlineClient(game_id, endpoint=args.server or record['endpoint'], room=record['room'],
                               resume_token=record['resume_token'])
        return MatchLobby(session, lambda connection: create_scene(connection, None), title=title)
    if args.online_host or args.online_join:
        from saga2d.online import OnlineClient
        session = OnlineClient(game_id, endpoint=args.server, room=args.online_join,
                               options=(create_options or dict)() if args.online_host else None)
        return MatchLobby(session, lambda connection: create_scene(connection, None), title=title)
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
