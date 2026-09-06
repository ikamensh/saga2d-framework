"""Two-player, host-authoritative matches over nonblocking TCP.

Games supply ``apply(player, command)`` and ``snapshot(player)``. Only the host
runs rules/simulation; snapshots are JSON presentation data chosen by the game.
Call poll every frame, publish after autonomous simulation, and close on exit.
No threads, global game, game rules, pickle, or dynamically dispatched methods.
"""
from __future__ import annotations

import errno
import json
import secrets
import select
import socket
import struct
import time
from collections.abc import Callable

_MAX_FRAME = 8 * 1024 * 1024
_MAX_QUEUE = 2 * _MAX_FRAME
_PROTOCOL = 1


class CommandError(ValueError):
    """An expected invalid player command; displayed to its sender."""


class _Peer:
    def __init__(self, sock):
        self.sock = sock
        sock.setblocking(False)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.incoming = bytearray()
        self.outgoing = bytearray()
        self.last_received = time.monotonic()
        self.last_sent = self.last_received

    def send(self, message):
        data = json.dumps(message, separators=(',', ':'), allow_nan=False).encode()
        if len(data) > _MAX_FRAME or len(self.outgoing) + len(data) + 4 > _MAX_QUEUE:
            raise ConnectionError('Connection cannot keep up with the match.')
        self.outgoing.extend(struct.pack('!I', len(data)))
        self.outgoing.extend(data)

    def poll(self):
        if self.outgoing:
            try:
                sent = self.sock.send(self.outgoing)
                del self.outgoing[:sent]
                self.last_sent = time.monotonic()
            except BlockingIOError:
                pass
        try:
            data = self.sock.recv(65536)
        except BlockingIOError:
            data = None
        if data == b'':
            raise ConnectionError('The other player disconnected.')
        if data:
            self.last_received = time.monotonic()
            self.incoming.extend(data)
        messages = []
        for _ in range(64):
            if len(self.incoming) < 4:
                break
            size = struct.unpack('!I', self.incoming[:4])[0]
            if size > _MAX_FRAME:
                raise ConnectionError('Network message exceeds the size limit.')
            if len(self.incoming) < size + 4:
                break
            try:
                message = json.loads(self.incoming[4:size + 4], parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise ConnectionError('Invalid JSON network message.') from exc
            del self.incoming[:size + 4]
            if not isinstance(message, dict):
                raise ConnectionError('Network messages must be objects.')
            messages.append(message)
        if time.monotonic() - self.last_received > 15:
            raise ConnectionError('Connection timed out.')
        if time.monotonic() - self.last_sent > 3 and not self.outgoing:
            self.send({'type': 'ping'})
        return [m for m in messages if m.get('type') != 'ping']

    def close(self):
        self.sock.close()


class MatchHost:
    """Host one guest. Seat 0 belongs to the host, seat 1 to the guest.

    ``apply`` raises CommandError for an invalid command. Other exceptions
    propagate. ``snapshot`` must return fresh JSON data, filtered for that seat.
    A disconnected guest can rejoin with the same token and receives a fresh
    snapshot. Games pause their simulation whenever ``ready`` is false.
    """
    player = 0

    def __init__(self, game_id: str, apply: Callable[[int, dict], None],
                 snapshot: Callable[[int], dict], *, address=('0.0.0.0', 7777), token: str | None = None):
        self.game_id, self.apply, self.snapshot = game_id, apply, snapshot
        self.token = token if token is not None else secrets.token_hex(6)
        if not self.token:
            raise ValueError('A nonempty room token is required.')
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind(address)
            self.listener.listen(4)
            self.listener.setblocking(False)
        except BaseException:
            self.listener.close()
            raise
        self.address = self.listener.getsockname()
        self.peer = None
        self.ready = False
        self.closed = False
        self.error = ''
        self.revision = 0
        self.state = None
        self._rejecting = False

    def _drop(self, error):
        self.peer.close()
        self.peer = None
        self.ready = False
        self.error = str(error)
        self._rejecting = False

    def poll(self):
        if self.closed:
            return
        try:
            sock, _ = self.listener.accept()
        except BlockingIOError:
            sock = None
        if sock is not None:
            if self.peer is not None:
                sock.close()
            else:
                self.peer = _Peer(sock)
        if self.peer is None:
            return
        try:
            for message in self.peer.poll():
                if self.peer is None:
                    break
                if self._rejecting:
                    continue
                if not self.ready:
                    if (message.get('type') != 'hello' or message.get('protocol') != _PROTOCOL
                            or message.get('game') != self.game_id
                            or not isinstance(message.get('token'), str)
                            or not secrets.compare_digest(message['token'].encode(), self.token.encode())):
                        self.peer.send({'type': 'reject', 'error': 'Wrong game version or room token.'})
                        self._rejecting = True
                        continue
                    self.ready = True
                    self.error = ''
                    self.publish()
                elif message.get('type') == 'command' and isinstance(message.get('command'), dict):
                    try:
                        self._apply(1, message['command'], message.get('revision'))
                    except CommandError as exc:
                        self.peer.send({'type': 'error', 'error': str(exc)})
                else:
                    raise ConnectionError('Unexpected network message.')
            if self.peer is not None and self._rejecting and not self.peer.outgoing:
                self._drop('Guest rejected: wrong game version or room token.')
        except (OSError, ConnectionError) as exc:
            self._drop(exc)

    def _apply(self, player, command, revision):
        if not self.ready:
            raise CommandError('Waiting for the other player.')
        if revision is not None and (type(revision) is not int or revision != self.revision):
            raise CommandError('The match changed. Please try that order again.')
        self.apply(player, command)
        self.publish()

    def submit(self, command: dict, *, revision: int | None = None):
        self._apply(0, command, revision)

    def publish(self):
        """Publish the current state after commands or a host simulation tick."""
        self.revision += 1
        self.state = self.snapshot(0)
        if self.ready:
            try:
                self.peer.send({'type': 'state', 'player': 1, 'revision': self.revision, 'state': self.snapshot(1)})
            except ConnectionError as exc:
                self._drop(exc)

    def close(self):
        if self.peer is not None:
            self.peer.close()
            self.peer = None
        self.listener.close()
        self.closed = True
        self.ready = False


class MatchClient:
    """Join a host; submit commands and read the latest authoritative state."""
    player = 1

    def __init__(self, game_id: str, address: tuple[str, int], *, token: str):
        self.ready = False
        self.closed = False
        self.error = ''
        self.state = None
        self.revision = 0
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.peer = _Peer(sock)
        try:
            result = sock.connect_ex(address)
            if result not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY):
                raise OSError(result, 'Could not connect to host.')
            self.peer.send({'type': 'hello', 'protocol': _PROTOCOL, 'game': game_id, 'token': token})
        except BaseException:
            sock.close()
            raise
        self._connecting = True

    def poll(self):
        if self.closed:
            return
        try:
            if self._connecting:
                _, writable, failed = select.select([], [self.peer.sock], [self.peer.sock], 0)
                if not writable and not failed:
                    if time.monotonic() - self.peer.last_received > 10:
                        raise ConnectionError('Could not connect to host: timed out.')
                    return
                error = self.peer.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if error:
                    raise OSError(error, 'Could not connect to host.')
                self._connecting = False
            for message in self.peer.poll():
                kind = message.get('type')
                if kind == 'state' and isinstance(message.get('state'), dict) and type(message.get('revision')) is int:
                    self.state = message['state']
                    self.revision = message['revision']
                    self.ready = True
                elif kind in ('error', 'reject') and isinstance(message.get('error'), str):
                    self.error = message['error']
                    if kind == 'reject':
                        self.close()
                        break
                else:
                    raise ConnectionError('Unexpected network message.')
        except (OSError, ConnectionError) as exc:
            self.error = str(exc)
            self.close()

    def submit(self, command: dict, *, revision: int | None = None):
        if not self.ready:
            raise CommandError(self.error or 'Waiting for the host.')
        self.peer.send({'type': 'command', 'command': command, 'revision': revision})

    def close(self):
        self.peer.close()
        self.closed = True
        self.ready = False
