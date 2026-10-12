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
#: How many watchers one host admits; guests never compete for these slots.
MAX_OBSERVERS = 8
_MAX_PENDING = 8
#: Seconds an accepted socket has to say hello or observe; pings do not extend it.
_HANDSHAKE_TIMEOUT = 10.
#: Seconds a refused watcher has to collect its error before the host hangs up.
_REFUSE_GRACE = 5.


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
        self.accepted_at = self.last_received
        self._waiting_state = None  # where in ``outgoing`` a state begins that is queued last and has not begun to leave

    def send(self, message):
        """Queue *message*.  A state replaces a state still waiting whole at the end of the queue: a peer slower
        than the match needs the newest one, not every one since it last kept up."""
        data = json.dumps(message, separators=(',', ':'), allow_nan=False).encode()
        is_state = message.get('type') == 'state'
        if is_state and self._waiting_state is not None:
            del self.outgoing[self._waiting_state:]
        if len(data) > _MAX_FRAME or len(self.outgoing) + len(data) + 4 > _MAX_QUEUE:
            raise ConnectionError('Connection cannot keep up with the match.')
        self._waiting_state = len(self.outgoing) if is_state else None
        self.outgoing.extend(struct.pack('!I', len(data)))
        self.outgoing.extend(data)

    def poll(self):
        """Send and receive all the socket takes and holds now: one chunk per call tied the link's speed to the frame rate."""
        while self.outgoing:
            try:
                sent = self.sock.send(self.outgoing)
            except BlockingIOError:
                break
            del self.outgoing[:sent]
            self.last_sent = time.monotonic()
            if self._waiting_state is not None:
                self._waiting_state = self._waiting_state - sent if sent <= self._waiting_state else None  # it has begun to leave
        closed = False
        while len(self.incoming) < _MAX_QUEUE:
            try:
                data = self.sock.recv(262144)
            except BlockingIOError:
                break
            if data == b'':
                closed = True  # what the peer said before it hung up (a rejection, say) is still to be read
                break
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
        if closed and not messages:
            raise ConnectionError('The other player disconnected.')
        if time.monotonic() - self.last_received > 15:
            raise ConnectionError('Connection timed out.')
        if time.monotonic() - self.last_sent > 3 and not self.outgoing:
            self.send({'type': 'ping'})
        return [m for m in messages if m.get('type') != 'ping']

    def close(self):
        self.sock.close()


class MatchHost:
    """Host one guest plus up to ``MAX_OBSERVERS`` watchers. Seat 0 belongs to
    the host, seat 1 to the guest; watchers hold no seat.

    ``apply`` raises CommandError for an invalid command. Other exceptions
    propagate. ``snapshot`` must return fresh JSON data, filtered for that seat.
    ``observer_snapshot`` returns the watcher's whole view, or None for games
    that cannot be watched. A disconnected guest can rejoin with the same token
    and receives a fresh snapshot; a watcher rejoins by saying ``observe``
    again. Games pause their simulation whenever ``ready`` is false, and only
    the guest affects ``ready``. ``observer_count`` says how many are watching.
    """
    player = 0

    def __init__(self, game_id: str, apply: Callable[[int, dict], None],
                 snapshot: Callable[[int], dict], *, address=('0.0.0.0', 7777), token: str | None = None,
                 observer_snapshot: Callable[[], dict] | None = None):
        if observer_snapshot is not None and not callable(observer_snapshot):
            raise ValueError('observer_snapshot must be a callable or None.')
        self.game_id, self.apply, self.snapshot = game_id, apply, snapshot
        self.observer_snapshot = observer_snapshot
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
        self.observers: list[_Peer] = []
        self._pending: list[_Peer] = []
        self._refusing: list[_Peer] = []
        self.ready = False
        self.closed = False
        self.error = ''
        self.revision = 0
        self.state = None
        self._guest_payload = None  # last published guest payload; metadata refresh only

    @property
    def observer_count(self):
        return len(self.observers)

    def _drop(self, error):
        self.peer.close()
        self.peer = None
        self.ready = False
        self.error = str(error)
        self._send_observer_states()

    def _remove_pending(self, peer):
        peer.close()
        if peer in self._pending:
            self._pending.remove(peer)

    def _reject_pending(self, peer, error):
        peer.send({'type': 'reject', 'error': error})
        peer._rejecting = True

    def _remove_observer(self, peer):
        peer.close()
        if peer in self.observers:
            self.observers.remove(peer)
        self._refresh_observers()

    def _valid_hello(self, message):
        return (message.get('protocol') == _PROTOCOL
                and message.get('game') == self.game_id
                and isinstance(message.get('token'), str)
                and secrets.compare_digest(message['token'].encode(), self.token.encode()))

    def _route_pending(self, peer, message):
        kind = message.get('type')
        if kind == 'hello' and self._valid_hello(message):
            if self.peer is not None:
                self._reject_pending(peer, 'The guest seat is already taken.')
            else:
                self._pending.remove(peer)
                self.peer = peer
                self.ready = True
                self.error = ''
                self.publish()
        elif kind == 'observe' and self._valid_hello(message):
            if self.observer_snapshot is None:
                self._reject_pending(peer, 'This match does not support observing.')
            elif len(self.observers) >= MAX_OBSERVERS:
                self._reject_pending(peer, 'This match has too many observers.')
            else:
                self._pending.remove(peer)
                self.observers.append(peer)
                peer.send({'type': 'welcome', 'observer': True, 'player': None,
                           'ready': self.ready, 'observer_count': len(self.observers)})
                self._refresh_observers()
        else:
            self._reject_pending(peer, 'Wrong game version or room token.')

    def _poll_pending(self):
        now = time.monotonic()
        for peer in list(self._pending):
            if now - peer.accepted_at > _HANDSHAKE_TIMEOUT:
                self._remove_pending(peer)
                continue
            try:
                messages = peer.poll()
            except (OSError, ConnectionError):
                self._remove_pending(peer)
                continue
            for message in messages:
                if peer._rejecting:
                    continue
                self._route_pending(peer, message)
                if peer not in self._pending:
                    break
            if peer in self._pending and peer._rejecting and not peer.outgoing:
                self._remove_pending(peer)

    def _poll_guest(self):
        if self.peer is None:
            return
        try:
            for message in self.peer.poll():
                if self.peer is None:
                    break
                if message.get('type') == 'command' and isinstance(message.get('command'), dict):
                    try:
                        self._apply(1, message['command'], message.get('revision'))
                    except CommandError as exc:
                        if self.peer is None:
                            break
                        self.peer.send({'type': 'error', 'error': str(exc)})
                else:
                    raise ConnectionError('Unexpected network message.')
        except (OSError, ConnectionError) as exc:
            self._drop(exc)

    def _poll_observers(self):
        for peer in list(self.observers):
            try:
                for message in peer.poll():
                    if message.get('type') == 'command':
                        peer.send({'type': 'error', 'error': 'Observers cannot submit orders.'})
                    else:
                        raise ConnectionError('Unexpected network message.')
            except (OSError, ConnectionError):
                self._remove_observer(peer)

    def _observer_view(self):
        """The shared watcher payload, or None when watching must end.

        Hook, serialization, and size failures refuse every watcher with an
        explicit error; the match never pays for a view only watchers see.
        """
        try:
            view = self.observer_snapshot()
        except Exception as exc:
            return self._refuse_observers(f'Observer view failed: {exc}')
        try:
            data = json.dumps(view, separators=(',', ':'), allow_nan=False)
        except (TypeError, ValueError) as exc:
            return self._refuse_observers(f'Invalid observer view: {exc}')
        if len(data) > _MAX_FRAME:
            return self._refuse_observers('Observer view exceeds the network size limit.')
        return view

    def _refuse_observers(self, error):
        """Refuse every watcher explicitly; the match plays on.

        Refusals flush like pending rejections: a refused socket lingers only
        until its error leaves or the link proves wedged, never silently.
        """
        for peer in list(self.observers):
            try:
                peer.send({'type': 'reject', 'error': error})
            except ConnectionError:
                peer.close()
            else:
                self._refusing.append(peer)
        self.observers = []
        return None

    def _poll_refusing(self):
        for peer in list(self._refusing):
            try:
                peer.poll()
            except (OSError, ConnectionError):
                pass
            if not peer.outgoing or time.monotonic() - peer.last_sent > _REFUSE_GRACE:
                peer.close()
                self._refusing.remove(peer)

    def _send_observer_states(self):
        """Send the current view to every watcher without moving the revision."""
        if not self.observers:
            return  # never run game code when nobody watches
        view = self._observer_view()
        if view is None:
            return
        while self.observers:
            count = len(self.observers)
            failed = False
            for peer in list(self.observers):
                try:
                    peer.send({'type': 'state', 'observer': True, 'revision': self.revision,
                               'ready': self.ready, 'state': view, 'observer_count': count})
                except ConnectionError:
                    peer.close()
                    if peer in self.observers:
                        self.observers.remove(peer)
                    failed = True
            if not failed:
                return
            # A dropped watcher left earlier sends overstating the count; correct them.

    def _refresh_seat_metadata(self):
        """Re-send the guest its last state with fresh watcher counts.

        Same revision, same game data, no callbacks: a paused match's guest
        learns the new count without a new match event. Advisory only.
        """
        if self.peer is None or self._guest_payload is None:
            return
        try:
            self.peer.send({'type': 'state', 'player': 1, 'revision': self.revision,
                            'state': self._guest_payload, 'observer_count': len(self.observers)})
        except ConnectionError:
            pass

    def _refresh_observers(self):
        """Watcher membership changed: update watchers and the guest's counts."""
        self._send_observer_states()
        self._refresh_seat_metadata()

    def poll(self):
        if self.closed:
            return
        try:
            sock, _ = self.listener.accept()
        except BlockingIOError:
            sock = None
        if sock is not None:
            if len(self._pending) >= _MAX_PENDING:
                sock.close()
            else:
                peer = _Peer(sock)
                peer._rejecting = False
                self._pending.append(peer)
        self._poll_guest()
        self._poll_pending()
        self._poll_observers()
        self._poll_refusing()

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
                payload = self.snapshot(1)
                self.peer.send({'type': 'state', 'player': 1, 'revision': self.revision,
                                'state': payload, 'observer_count': len(self.observers)})
                self._guest_payload = payload
            except ConnectionError as exc:
                self._drop(exc)
        self._send_observer_states()

    def close(self):
        if self.peer is not None:
            self.peer.close()
            self.peer = None
        for peer in self._pending:
            peer.close()
        self._pending = []
        for peer in self.observers:
            peer.close()
        self.observers = []
        for peer in self._refusing:
            peer.close()
        self._refusing = []
        self.listener.close()
        self.closed = True
        self.ready = False


class MatchClient:
    """Join a host as its guest, or watch it with ``observer=True``.

    A watcher says ``observe`` instead of ``hello``: it holds no seat, so
    ``player`` is None, and it only ever sees the host's observer hook. Only
    an explicit observer welcome followed by observer-flagged states may turn
    a watcher ready; anything shaped like a seat claim is refused. Watchers
    cannot submit: ``submit`` raises CommandError locally.
    """
    player = 1

    def __init__(self, game_id: str, address: tuple[str, int], *, token: str, observer: bool = False):
        if type(observer) is not bool:
            raise ValueError('observer must be true or false.')
        self.observer = observer
        self.player = None if observer else 1
        self.ready = False
        self.closed = False
        self.error = ''
        self.state = None
        self.revision = 0
        self.observer_count = 0
        self._welcomed = not observer
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.peer = _Peer(sock)
        try:
            result = sock.connect_ex(address)
            if result not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY):
                raise OSError(result, 'Could not connect to host.')
            if observer:
                self.peer.send({'type': 'observe', 'protocol': _PROTOCOL, 'game': game_id, 'token': token})
            else:
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
                if kind == 'welcome' and self.observer:
                    if message.get('observer') is not True or message.get('player') is not None:
                        raise ConnectionError('Unexpected network message.')
                    self._welcomed = True
                    if type(message.get('observer_count')) is int:
                        self.observer_count = message['observer_count']
                elif (kind == 'state' and isinstance(message.get('state'), dict)
                        and type(message.get('revision')) is int):
                    if self.observer:
                        if not self._welcomed or message.get('observer') is not True:
                            raise ConnectionError('Unexpected network message.')
                        self.state = message['state']
                        self.revision = message['revision']
                        self.ready = message.get('ready') is True
                        if type(message.get('observer_count')) is int:
                            self.observer_count = message['observer_count']
                    else:
                        if message.get('observer') is True:
                            raise ConnectionError('Unexpected network message.')
                        self.state = message['state']
                        self.revision = message['revision']
                        self.ready = True
                        if type(message.get('observer_count')) is int:
                            self.observer_count = message['observer_count']
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
        if self.observer:
            raise CommandError('Observers cannot submit orders.')
        if not self.ready:
            raise CommandError(self.error or 'Waiting for the host.')
        self.peer.send({'type': 'command', 'command': command, 'revision': revision})

    def close(self):
        self.peer.close()
        self.closed = True
        self.ready = False
