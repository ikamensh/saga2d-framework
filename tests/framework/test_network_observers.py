"""Observers watch a LAN match through an explicit role, never a seat.

Real loopback sockets exercise the same host/watch interface the games use:
an observer says ``observe``, never ``hello``, and only an explicit observer
welcome plus observer-flagged states may turn a watcher ready.
"""
import json
import socket
import struct
import time

import pytest

from saga2d import MatchClient, MatchHost
from saga2d.network import MAX_OBSERVERS, CommandError


def pump(host, clients, until, timeout=5):
    if not isinstance(clients, (list, tuple)):
        clients = [clients]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        host.poll()
        for client in clients:
            client.poll()
        if until():
            return
        time.sleep(.001)
    raise AssertionError('network did not converge')


def make_host(**kwargs):
    """A counter match whose seats and watchers see different shapes."""
    counts = [0, 0]
    calls = kwargs.pop('snapshot_calls', None)

    def apply(player, command):
        counts[player] += command['amount']

    def snapshot(player):
        if calls is not None:
            calls.append(player)
        return {'counts': list(counts), 'you': player}

    kwargs.setdefault('observer_snapshot', lambda: {'total': sum(counts), 'watching': True})
    host = MatchHost('counter-v1', apply, snapshot,
                     address=('127.0.0.1', 0), token='test', **kwargs)
    return host, counts


def recvn(sock, size):
    data = b''
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError('The test peer disconnected.')
        data += chunk
    return data


def send_frame(sock, message):
    data = json.dumps(message).encode()
    sock.sendall(struct.pack('!I', len(data)) + data)


def recv_frame(sock, timeout=5):
    sock.settimeout(timeout)
    (size,) = struct.unpack('!I', recvn(sock, 4))
    return json.loads(recvn(sock, size))


def test_observer_watches_its_own_snapshot_while_seats_play():
    """The watcher sees only the observer hook's data, never a seat snapshot."""
    host, _ = make_host()
    guest = MatchClient('counter-v1', host.address, token='test')
    watcher = MatchClient('counter-v1', host.address, token='test', observer=True)
    try:
        pump(host, [guest, watcher], lambda: guest.ready and host.ready and watcher.ready)
        assert watcher.observer is True
        assert watcher.player is None
        assert watcher.state == {'total': 0, 'watching': True}
        assert guest.state == {'counts': [0, 0], 'you': 1}
        assert host.observer_count == 1
        guest.submit({'amount': 3})
        pump(host, [guest, watcher], lambda: watcher.state == {'total': 3, 'watching': True})
        assert guest.state == {'counts': [0, 3], 'you': 1}
        host.submit({'amount': 2})
        pump(host, [guest, watcher], lambda: watcher.state == {'total': 5, 'watching': True})
        assert host.state == {'counts': [2, 3], 'you': 0}
    finally:
        guest.close()
        watcher.close()
        host.close()


def test_observer_joins_lobby_first_and_guest_joins_after():
    """Watchers may wait in the lobby; a later guest still claims its seat."""
    host, _ = make_host()
    watcher = MatchClient('counter-v1', host.address, token='test', observer=True)
    guest = None
    try:
        pump(host, watcher, lambda: watcher.state is not None)
        assert not watcher.ready and not host.ready
        assert watcher.state == {'total': 0, 'watching': True}
        guest = MatchClient('counter-v1', host.address, token='test')
        pump(host, [guest, watcher], lambda: guest.ready and host.ready and watcher.ready)
        assert guest.player == 1
        assert host.observer_count == 1
        guest.submit({'amount': 1})
        pump(host, [guest, watcher], lambda: watcher.state == {'total': 1, 'watching': True})
    finally:
        if guest is not None:
            guest.close()
        watcher.close()
        host.close()


def test_observer_and_guest_disconnects_are_independent():
    """Losing a watcher never pauses the match; losing the guest still does."""
    host, _ = make_host()
    guest = MatchClient('counter-v1', host.address, token='test')
    watcher = MatchClient('counter-v1', host.address, token='test', observer=True)
    try:
        pump(host, [guest, watcher], lambda: guest.ready and watcher.ready)
        watcher.close()
        pump(host, guest, lambda: host.observer_count == 0)
        assert host.ready and guest.ready
        guest.submit({'amount': 1})
        pump(host, guest, lambda: guest.state == {'counts': [0, 1], 'you': 1})
        watcher = MatchClient('counter-v1', host.address, token='test', observer=True)
        pump(host, [guest, watcher], lambda: watcher.ready)
        guest.close()
        pump(host, watcher, lambda: not host.ready and not watcher.ready)
        assert host.observer_count == 1
        guest = MatchClient('counter-v1', host.address, token='test')
        pump(host, [guest, watcher], lambda: guest.ready and watcher.ready)
        assert watcher.state == {'total': 1, 'watching': True}
    finally:
        guest.close()
        watcher.close()
        host.close()


def test_observer_orders_are_refused_without_touching_the_match():
    """A watcher cannot submit, and a raw order over its wire is refused in place."""
    from saga2d.network import CommandError as LanCommandError
    host, counts = make_host()
    guest = MatchClient('counter-v1', host.address, token='test')
    watcher = MatchClient('counter-v1', host.address, token='test', observer=True)
    raw = socket.socket()
    try:
        pump(host, [guest, watcher], lambda: guest.ready and watcher.ready)
        with pytest.raises(LanCommandError, match='bserver'):
            watcher.submit({'amount': 1})
        raw.connect(host.address)
        send_frame(raw, {'type': 'observe', 'protocol': 1, 'game': 'counter-v1', 'token': 'test'})
        assert recv_frame(raw)['type'] == 'welcome'
        first = recv_frame(raw)
        assert first['type'] == 'state' and first['observer'] is True
        send_frame(raw, {'type': 'command', 'command': {'amount': 10}, 'revision': None})
        refused = recv_frame(raw)
        assert refused['type'] == 'error' and 'bserver' in refused['error']
        assert counts == [0, 0]
        host.submit({'amount': 2})
        pump(host, [guest, watcher], lambda: watcher.state == {'total': 2, 'watching': True})
        assert recv_frame(raw)['state'] == {'total': 2, 'watching': True}
    finally:
        raw.close()
        guest.close()
        watcher.close()
        host.close()


def test_several_observers_watch_and_one_rotten_wire_spoils_only_itself():
    """Garbage from one watcher drops only that watcher; the match plays on."""
    host, _ = make_host()
    guest = MatchClient('counter-v1', host.address, token='test')
    first = MatchClient('counter-v1', host.address, token='test', observer=True)
    raw = socket.socket()
    try:
        pump(host, [guest, first], lambda: guest.ready and first.ready)
        raw.connect(host.address)
        send_frame(raw, {'type': 'observe', 'protocol': 1, 'game': 'counter-v1', 'token': 'test'})
        assert recv_frame(raw)['type'] == 'welcome'
        assert host.observer_count == 2
        raw.sendall(struct.pack('!I', 4) + b'{oops')
        pump(host, [guest, first], lambda: host.observer_count == 1)
        guest.submit({'amount': 4})
        pump(host, [guest, first], lambda: first.state == {'total': 4, 'watching': True})
        assert guest.ready and host.ready
    finally:
        raw.close()
        guest.close()
        first.close()
        host.close()


def test_observe_without_hook_is_rejected_and_the_seat_stays_free():
    """A legacy-shaped refusal: no hook means a reject, never a claimed seat."""
    host, _ = make_host(observer_snapshot=None)
    watcher = MatchClient('counter-v1', host.address, token='test', observer=True)
    guest = None
    try:
        pump(host, watcher, lambda: watcher.closed)
        assert not watcher.ready
        assert watcher.player is None
        assert 'support observing' in watcher.error
        assert not host.ready and host.peer is None
        guest = MatchClient('counter-v1', host.address, token='test')
        pump(host, guest, lambda: guest.ready and host.ready)
        assert guest.player == 1
    finally:
        if guest is not None:
            guest.close()
        watcher.close()
        host.close()


def test_observer_client_refuses_a_legacy_seat_claim():
    """If a host answers an observe handshake by claiming the guest seat and
    sending its snapshot, the watcher must never mistake that for its own
    welcome and state. (Real old hosts reject the unknown type instead.)"""
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    address = listener.getsockname()

    def legacy_host():
        conn, _ = listener.accept()
        try:
            conn.settimeout(5)
            (size,) = struct.unpack('!I', recvn(conn, 4))
            recvn(conn, size)  # the observe hello; a legacy host reads it as a guest hello
            send_frame(conn, {'type': 'state', 'player': 1, 'revision': 1,
                              'state': {'counts': [9, 9], 'you': 1}})
            time.sleep(2)
        except OSError:
            pass
        finally:
            conn.close()

    import threading
    worker = threading.Thread(target=legacy_host, daemon=True)
    worker.start()
    watcher = MatchClient('counter-v1', address, token='test', observer=True)
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not watcher.closed and not watcher.ready:
            watcher.poll()
            time.sleep(.005)
        assert watcher.player is None
        assert not watcher.ready
        assert watcher.state is None
        assert watcher.closed or watcher.error
    finally:
        watcher.close()
        listener.close()
        worker.join(timeout=5)


def test_observer_admission_is_bounded():
    """Only so many watchers fit; the guest seat is never what runs out."""
    host, _ = make_host()
    watchers = [MatchClient('counter-v1', host.address, token='test', observer=True)
                for _ in range(MAX_OBSERVERS)]
    extra = None
    guest = MatchClient('counter-v1', host.address, token='test')
    try:
        pump(host, [guest], lambda: guest.ready and host.ready)
        pump(host, watchers + [guest], lambda: all(w.ready for w in watchers), timeout=10)
        assert host.observer_count == MAX_OBSERVERS
        extra = MatchClient('counter-v1', host.address, token='test', observer=True)
        pump(host, watchers + [extra], lambda: extra.closed)
        assert not extra.ready and host.observer_count == MAX_OBSERVERS
        assert guest.ready and host.ready
    finally:
        if extra is not None:
            extra.close()
        guest.close()
        for watcher in watchers:
            watcher.close()
        host.close()


def test_oversized_watcher_view_drops_only_the_watcher():
    """A watcher payload past the frame cap ends watching; the seats play on."""
    host, counts = make_host(observer_snapshot=lambda: {'bulk': 'g' * (9 * 1024 * 1024)})
    guest = MatchClient('counter-v1', host.address, token='test')
    watcher = MatchClient('counter-v1', host.address, token='test', observer=True)
    try:
        pump(host, [guest, watcher], lambda: guest.ready and host.ready)
        pump(host, [guest, watcher], lambda: watcher.closed, timeout=10)
        assert host.observer_count == 0
        assert guest.ready and host.ready
        guest.submit({'amount': 3})
        pump(host, guest, lambda: guest.state['counts'] == [0, 3])
        assert counts == [0, 3]
    finally:
        guest.close()
        watcher.close()
        host.close()


def test_pinging_squatters_cannot_hold_the_guest_seat():
    """Sockets that ping without ever saying hello are dropped on an absolute
    deadline, freeing the seat for a real guest."""
    from saga2d.network import _HANDSHAKE_TIMEOUT
    host, _ = make_host()
    squatters = []
    try:
        for _ in range(8):
            sock = socket.socket()
            sock.connect(host.address)
            send_frame(sock, {'type': 'ping'})
            squatters.append(sock)
        pump(host, [], lambda: len(host._pending) == 8, timeout=10)
        for peer in host._pending:
            peer.accepted_at -= _HANDSHAKE_TIMEOUT + 1  # simulate elapsed time
        pump(host, [], lambda: not host._pending, timeout=10)
        guest = MatchClient('counter-v1', host.address, token='test')
        try:
            pump(host, guest, lambda: guest.ready and host.ready)
            assert guest.player == 1
        finally:
            guest.close()
    finally:
        for sock in squatters:
            sock.close()
        host.close()


def test_unserializable_observer_view_refuses_watchers_explicitly():
    """A hook payload JSON cannot carry refuses every watcher out loud, with
    the reason attached; the seats play on untouched."""
    host, _ = make_host(observer_snapshot=lambda: {'total': float('nan')})
    guest = MatchClient('counter-v1', host.address, token='test')
    watcher = MatchClient('counter-v1', host.address, token='test', observer=True)
    try:
        pump(host, [guest], lambda: guest.ready and host.ready)
        pump(host, [guest, watcher], lambda: watcher.closed, timeout=10)
        assert 'observer view' in watcher.error.lower(), watcher.error
        assert host.observer_count == 0
        guest.submit({'amount': 2})
        pump(host, guest, lambda: guest.state['counts'] == [0, 2])
    finally:
        guest.close()
        watcher.close()
        host.close()


def test_hook_failing_midgame_ends_only_watching():
    """A hook that breaks after the match started refuses its watchers with
    the cause; the order that tripped it still lands for the seats."""
    calls = []

    def hook():
        calls.append(1)
        if len(calls) > 2:
            raise RuntimeError('boom mid-game')
        return {'total': 0, 'watching': True}

    host, _ = make_host(observer_snapshot=hook)
    guest = MatchClient('counter-v1', host.address, token='test')
    first = MatchClient('counter-v1', host.address, token='test', observer=True)
    second = None
    try:
        pump(host, [guest], lambda: guest.ready and host.ready)
        pump(host, [guest, first], lambda: first.ready)
        second = MatchClient('counter-v1', host.address, token='test', observer=True)
        pump(host, [guest, first, second], lambda: second.ready)
        guest.submit({'amount': 1})  # its publish trips the hook the third time
        pump(host, [guest, first, second], lambda: host.observer_count == 0, timeout=10)
        assert 'boom' in first.error and 'boom' in second.error, (first.error, second.error)
        assert guest.ready and host.ready
        assert guest.state == {'counts': [0, 1], 'you': 1}
    finally:
        guest.close()
        first.close()
        if second is not None:
            second.close()
        host.close()


def test_watcher_turnover_refreshes_guest_count_without_new_revision():
    """Arrivals and departures reach the guest at the same revision, from its
    last published state; the game is never re-asked for a snapshot."""
    calls = []
    host, _ = make_host(snapshot_calls=calls)
    guest = MatchClient('counter-v1', host.address, token='test')
    first = second = None
    try:
        pump(host, [guest], lambda: guest.ready and host.ready)
        revision, taken = host.revision, len(calls)
        first = MatchClient('counter-v1', host.address, token='test', observer=True)
        second = MatchClient('counter-v1', host.address, token='test', observer=True)
        pump(host, [guest, first, second], lambda: all(w.ready for w in (first, second)))
        pump(host, [guest, first, second], lambda: guest.observer_count == 2, timeout=10)
        assert host.revision == revision and guest.revision == revision
        assert len(calls) == taken
        second.close()
        pump(host, [guest, first], lambda: guest.observer_count == 1, timeout=10)
        assert host.revision == revision and guest.revision == revision
        assert len(calls) == taken
        assert guest.state == {'counts': [0, 0], 'you': 1}
    finally:
        guest.close()
        if first is not None:
            first.close()
        if second is not None:
            second.close()
        host.close()


def test_observer_constructor_rejects_bad_arguments():
    """Role confusion fails fast, before any socket work starts."""
    with pytest.raises(ValueError, match='observer must be true or false'):
        MatchClient('counter-v1', ('127.0.0.1', 9), token='test', observer='yes')
    with pytest.raises(ValueError, match='observer_snapshot must be a callable or None'):
        MatchHost('counter-v1', lambda *_: None, lambda _: {}, address=('127.0.0.1', 0),
                  token='test', observer_snapshot={'total': 0})
