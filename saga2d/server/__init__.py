"""Authoritative online rooms for any registered game.

The public interface is the versioned WebSocket protocol, served by ``run``
with a ``{game id: GameSpec}`` registry (see ``saga2d.server.games``).
Game rules and room membership run serially on one event loop. Per-player
writers coalesce snapshots so a slow connection never delays another player.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
import json
import ipaddress
import logging
import math
import secrets
import string
import time

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from saga2d.network import CommandError
from saga2d.server.games import GameSpec, load_games, option_choice, option_int, option_keys, option_seed
from saga2d.server.storage import RoomStore

__all__ = ['GameSpec', 'IncompatibleClient', 'MAX_MESSAGE', 'PROTOCOL', 'Peer', 'Room', 'RoomServer', 'decode',
           'load_games', 'option_choice', 'option_int', 'option_keys', 'option_seed', 'run']

PROTOCOL = 1
MAX_MESSAGE = 16_384
MAX_SNAPSHOT = 8 * 1024 * 1024
LOG = logging.getLogger(__name__)


def decode(data):
    """Keep all game inputs within a small, finite JSON object tree."""
    def reject_constant(value):
        raise ValueError(f'Invalid JSON number: {value}')

    try:
        message = json.loads(data, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CommandError('Invalid JSON message.') from exc
    if not isinstance(message, dict):
        raise CommandError('Network messages must be objects.')
    pending, count = [(message, 0)], 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > 12 or count > 2048:
            raise CommandError('Network message is too complex.')
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
        elif isinstance(value, float) and not math.isfinite(value):
            raise CommandError('Network numbers must be finite.')
        elif isinstance(value, str) and len(value) > 1024:
            raise CommandError('Network text is too long.')
    return message


class IncompatibleClient(CommandError):
    """The client's protocol or game version cannot join any room on this server."""


class Peer:
    """Bounded control messages and one replaceable snapshot per connection."""
    def __init__(self, websocket):
        self.websocket = websocket
        self.controls = deque()
        self.state = None
        self.wake = asyncio.Event()
        self.closing = False
        self.allowance = 40.
        self.last_message = time.monotonic()

    def send(self, message):
        if self.closing:
            return
        encoded = json.dumps(message, separators=(',', ':'), allow_nan=False)
        if len(encoded) > MAX_SNAPSHOT:
            raise RuntimeError('Game snapshot exceeds the network size limit.')
        if message['type'] == 'state':
            self.state = encoded
        elif len(self.controls) < 16:
            self.controls.append(encoded)
        else:
            self.reject('Connection cannot keep up with the match.')
        self.wake.set()

    def reject(self, error, reason=None):
        """End the connection; ``reason`` lets clients react beyond showing the text."""
        self.closing = True
        self.state = None
        self.controls.clear()
        message = {'type': 'reject', 'error': error}
        if reason is not None:
            message['reason'] = reason
        self.controls.append(json.dumps(message))
        self.wake.set()

    def check_rate(self):
        now = time.monotonic()
        self.allowance = min(40., self.allowance + (now - self.last_message) * 20)
        self.last_message = now
        if self.allowance < 1:
            raise CommandError('Too many commands. Reconnect and send orders more slowly.')
        self.allowance -= 1

    async def write(self):
        try:
            while True:
                await self.wake.wait()
                self.wake.clear()
                while self.controls or self.state is not None:
                    if self.controls:
                        data = self.controls.popleft()
                    else:
                        data, self.state = self.state, None
                    await asyncio.wait_for(self.websocket.send(data), timeout=3)
                if self.closing:
                    return
        except (ConnectionClosed, TimeoutError):
            pass
        finally:
            await self.websocket.close()


@dataclass
class Room:
    game: str
    match: object
    code: str
    tokens: list = field(default_factory=lambda: [secrets.token_urlsafe(32), None])
    peers: list = field(default_factory=lambda: [None, None])
    revision: int = 0
    disconnected_at: float = field(default_factory=time.monotonic)
    ticks: int = 0
    checkpointed_at: float = 0.

    @property
    def ready(self):
        return all(peer is not None and not peer.closing for peer in self.peers)

    def publish(self):
        self.revision += 1
        for player, peer in enumerate(self.peers):
            if peer is not None:
                peer.send({'type': 'state', 'player': player, 'revision': self.revision,
                           'ready': self.ready, 'state': self.match.snapshot(player)})


class RoomServer:
    """Matches expire after ``room_ttl`` without both players; campaigns are retained
    for ``campaign_ttl`` and leave memory after ``room_ttl`` until a seat returns."""
    def __init__(self, games, *, max_rooms=64, max_connections=128, room_ttl=900, campaign_ttl=7 * 86400,
                 state_dir=None, trusted_proxy=False):
        if not games:
            raise ValueError('The server needs at least one registered game.')
        if max_rooms < 1 or max_connections < 2 or not math.isfinite(room_ttl) or room_ttl <= 0:
            raise ValueError('Room and connection limits must be positive.')
        if not math.isfinite(campaign_ttl) or campaign_ttl < room_ttl:
            raise ValueError('Campaign retention must be at least the match room retention.')
        self.games = dict(games)
        self.rooms = {}
        self.max_rooms, self.max_connections = max_rooms, max_connections
        self.room_ttl, self.campaign_ttl = room_ttl, campaign_ttl
        self.connections = set()
        self.by_ip = {}
        self.creations = {}
        self.trusted_proxy = trusted_proxy
        self.store = RoomStore(state_dir) if state_dir is not None else None
        self.last_keep_alive = time.monotonic()
        if self.store is not None:
            for saved in self.store.load():
                self.rooms[saved['code']] = self.restore(saved)

    def retention(self, game):
        return self.campaign_ttl if self.games[game].campaign else self.room_ttl

    def restore(self, saved):
        room = Room(saved['game'], self.games[saved['game']].restore(saved['state']), saved['code'],
                    tokens=saved['tokens'], revision=saved['revision'])
        remaining = saved['expires_at'] - time.time()
        room.disconnected_at = time.monotonic() - (self.retention(room.game) - remaining)
        return room

    def checkpoint(self, room, *, force=False):
        if self.store is not None and (force or time.monotonic() - room.checkpointed_at >= 5):
            self.store.save(room, self.retention(room.game), self.games[room.game].checkpoint(room.match))
            room.checkpointed_at = time.monotonic()

    def suspend(self, room):
        """Keep a campaign's seats in storage only, freeing memory and the room limit."""
        self.store.suspend(room, self.retention(room.game), self.games[room.game].checkpoint(room.match))
        del self.rooms[room.code]

    def find_room(self, code, game):
        room = self.rooms.get(code) if isinstance(code, str) else None
        if room is None and self.store is not None and isinstance(code, str):
            saved = self.store.suspended(code)
            if saved is not None and saved['game'] == game:
                if len(self.rooms) >= self.max_rooms:
                    raise CommandError('The server is full. Please try again later.')
                room = self.rooms[code] = self.restore(saved)
        if room is None or room.game != game:
            raise CommandError('Room not found for this game. Check the room code.')
        return room

    def client_address(self, websocket):
        address = websocket.remote_address[0]
        if self.trusted_proxy and ipaddress.ip_address(address).is_loopback:
            forwarded = websocket.request.headers.get_all('X-Forwarded-For')
            if forwarded:
                if len(forwarded) != 1:
                    raise CommandError('Invalid proxy address.')
                try:
                    return str(ipaddress.ip_address(forwarded[0].split(',')[-1].strip()))
                except ValueError as exc:
                    raise CommandError('Invalid proxy address.') from exc
        return address

    def enter(self, message, address):
        if type(message.get('protocol')) is not int or message['protocol'] != PROTOCOL:
            raise IncompatibleClient('Incompatible multiplayer protocol. Update your game client.')
        game, kind = message.get('game'), message.get('type')
        if game not in self.games:
            raise IncompatibleClient('Unknown game version. Update your game client.')
        if kind == 'create':
            if len(self.rooms) >= self.max_rooms:
                raise CommandError('The server is full. Please try again later.')
            recent = self.creations.setdefault(address, deque())
            now = time.monotonic()
            while recent and recent[0] < now - 60:
                recent.popleft()
            if len(recent) >= 4:
                raise CommandError('Too many new rooms. Please wait a minute.')
            recent.append(now)
            match = self.games[game].create(message.get('options', {}))
            while True:
                code = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(12))
                if code not in self.rooms:
                    break
            room = Room(game, match, code)
            self.rooms[code] = room
            return room, 0
        room = self.find_room(message.get('room'), game)
        if kind == 'join':
            if room.tokens[1] is not None:
                raise CommandError('Both seats are claimed. Reconnect using your saved seat.')
            room.tokens[1] = secrets.token_urlsafe(32)
            return room, 1
        if kind == 'resume':
            token = message.get('resume_token')
            if isinstance(token, str):
                for player, expected in enumerate(room.tokens):
                    if expected is not None and secrets.compare_digest(token.encode(), expected.encode()):
                        if room.peers[player] is not None:
                            room.peers[player].reject('Your seat reconnected from another connection.')
                        return room, player
            raise CommandError('The saved seat does not belong to this room.')
        raise CommandError('Choose create, join or resume.')

    def fail_room(self, room, error):
        self.rooms.pop(room.code, None)
        for peer in room.peers:
            if peer is not None:
                peer.reject(error)
        if self.store is not None:
            self.store.delete(room.code)

    def apply(self, room, player, message):
        if message.get('type') != 'command' or not isinstance(message.get('command'), dict):
            raise CommandError('Expected a game command.')
        if not room.ready:
            raise CommandError('Waiting for the other player.')
        revision = message.get('revision')
        if revision is not None and (type(revision) is not int or revision != room.revision):
            raise CommandError('The match changed. Please try that order again.')
        room.match.apply(player, message['command'])
        room.publish()
        self.checkpoint(room, force=not self.games[room.game].realtime)

    async def handle(self, websocket):
        peer = Peer(websocket)
        try:
            address = self.client_address(websocket)
        except CommandError as exc:
            peer.reject(str(exc))
            await peer.write()
            return
        if len(self.connections) >= self.max_connections or self.by_ip.get(address, 0) >= 16:
            peer.reject('Too many connections. Please try again later.')
            await peer.write()
            return
        self.connections.add(peer)
        self.by_ip[address] = self.by_ip.get(address, 0) + 1
        writer = asyncio.create_task(peer.write())
        room = None
        player = None
        try:
            message = decode(await asyncio.wait_for(websocket.recv(), timeout=10))
            room, player = self.enter(message, address)
            peer.send({'type': 'welcome', 'room': room.code, 'resume_token': room.tokens[player],
                       'player': player, 'protocol': PROTOCOL, 'game': room.game,
                       'retention': self.retention(room.game)})
            room.peers[player] = peer
            room.publish()
            self.checkpoint(room, force=True)
            async for data in websocket:
                if room.peers[player] is not peer or peer.closing:
                    break
                peer.check_rate()
                message = decode(data)
                try:
                    self.apply(room, player, message)
                except CommandError as exc:
                    peer.send({'type': 'error', 'error': str(exc)})
        except IncompatibleClient as exc:
            peer.reject(str(exc), reason='incompatible')
            await writer
        except CommandError as exc:
            peer.reject(str(exc))
            await writer
        except TimeoutError:
            peer.reject('Timed out waiting for the room request.')
            await writer
        except ConnectionClosed:
            pass
        except Exception:
            LOG.exception('Unexpected failure in %s room', room.game if room else 'unassigned')
            if room is not None:
                self.fail_room(room, 'The match failed on the server. Please create a new room.')
            else:
                peer.reject('The server could not create this match.')
            await writer
        finally:
            self.connections.discard(peer)
            self.by_ip[address] -= 1
            if not self.by_ip[address]:
                del self.by_ip[address]
            if room is not None and room.peers[player] is peer:
                room.peers[player] = None
                room.disconnected_at = time.monotonic()
                if room.code in self.rooms:
                    try:
                        room.publish()
                        self.checkpoint(room, force=True)
                    except Exception:
                        LOG.exception('Could not publish disconnected %s room', room.game)
                        self.fail_room(room, 'The match failed on the server. Please create a new room.')
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)

    async def maintain(self):
        """Advance realtime matches once per 50 ms; discard missed time after overload/suspension."""
        while True:
            started = time.monotonic()
            for room in list(self.rooms.values()):
                try:
                    if not room.ready:
                        idle = started - room.disconnected_at
                        if idle >= self.retention(room.game):
                            self.fail_room(room, 'This room expired while waiting for players. Create a new room.')
                        elif (self.store is not None and self.games[room.game].campaign and idle >= self.room_ttl
                                and all(peer is None for peer in room.peers)):
                            self.suspend(room)
                    elif self.games[room.game].realtime:
                        room.match.step()
                        room.ticks += 1
                        if room.ticks % 2 == 0:
                            room.publish()
                        self.checkpoint(room)
                except Exception:
                    LOG.exception('Simulation failed in %s room', room.game)
                    self.fail_room(room, 'The match failed on the server. Please create a new room.')
            if self.store is not None and started - self.last_keep_alive >= min(60, self.room_ttl / 3):
                self.store.keep_alive([(room.code, self.retention(room.game))
                                       for room in self.rooms.values() if room.ready])
                self.store.purge()
                self.last_keep_alive = started
            self.creations = {address: times for address, times in self.creations.items()
                              if times and times[-1] > started - 60}
            await asyncio.sleep(max(0.001, .05 - (time.monotonic() - started)))

    def health(self, connection, request):
        if request.path == '/healthz':
            return connection.respond(HTTPStatus.OK, 'ok\n')
        if request.path not in ('/', '/ws', '/play'):
            return connection.respond(HTTPStatus.NOT_FOUND, 'not found\n')


async def run(host='127.0.0.1', port=8765, *, games, **limits):
    """Serve ``games`` until cancelled; close every socket, timer and checkpoint on shutdown."""
    rooms = RoomServer(games, **limits)
    try:
        async with serve(rooms.handle, host, port, process_request=rooms.health, origins=[None],
                         max_size=MAX_MESSAGE, max_queue=8, ping_interval=10, ping_timeout=10,
                         close_timeout=2, open_timeout=10, server_header=None, backlog=64) as server:
            address = server.sockets[0].getsockname()
            print(f'LISTENING ws://{address[0]}:{address[1]}', flush=True)
            # Awaiting maintenance also makes a broken persistence store fail the service visibly.
            await rooms.maintain()
    finally:
        if rooms.store is not None:
            for room in rooms.rooms.values():
                rooms.checkpoint(room, force=True)
            rooms.store.close()
