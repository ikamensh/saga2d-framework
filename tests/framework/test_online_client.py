"""The scene-facing client works against the real dedicated server process."""
import time
import select
import socket
import threading
from urllib.parse import urlsplit

import pytest

from saga2d.online import OnlineClient
from saga2d.testing.online import COUNTER_GAMES, server_fixture

server_url = server_fixture(COUNTER_GAMES)


def pump(*clients, until):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for client in clients:
            client.poll()
        if until():
            return
        time.sleep(.01)
    raise AssertionError([(client.ready, client.closed, client.error) for client in clients])


def test_both_players_use_remote_authority_and_can_resume_private_seats(server_url):
    """Creation needs no local listener; closing the creator preserves the live room."""
    creator = OnlineClient('counter-v1', endpoint=server_url, options={'seed': 7})
    guest = resumed = None
    try:
        pump(creator, until=lambda: bool(creator.room))
        assert not creator.ready and creator.resume_token
        guest = OnlineClient('counter-v1', endpoint=server_url, room=creator.room)
        pump(creator, guest, until=lambda: creator.ready and guest.ready)
        assert creator.player == 0 and guest.player == 1
        assert creator.state == guest.state
        creator.submit({'action': 'add'}, revision=creator.revision)
        pump(creator, guest, until=lambda: guest.state['counts'][0] == 1)
        room, token = creator.room, creator.resume_token
        creator.close()
        pump(guest, until=lambda: not guest.ready)
        resumed = OnlineClient('counter-v1', endpoint=server_url, room=room, resume_token=token)
        pump(resumed, guest, until=lambda: resumed.ready and guest.ready)
        assert resumed.player == 0
        assert resumed.state == guest.state
        assert resumed.state['counts'][0] == 1
    finally:
        for client in (creator, guest, resumed):
            if client is not None:
                client.close()


def test_wrong_room_reports_actionable_failure_without_blocking_frames(server_url):
    """A rejected join becomes a visible closed session rather than a waiting lobby."""
    client = OnlineClient('counter-v1', endpoint=server_url, room='missing')
    try:
        pump(client, until=lambda: client.closed)
        assert not client.ready
        assert 'Room not found' in client.error
    finally:
        client.close()


def test_public_endpoint_requires_tls():
    """Room codes and private seats may cross plaintext only for local development."""
    with pytest.raises(ValueError, match='TLS'):
        OnlineClient('counter-v1', endpoint='ws://example.com/play')


def test_connection_break_resumes_same_seat_and_authoritative_turn(server_url):
    """An interrupted TCP route reconnects without requiring the player to leave the match."""
    target = urlsplit(server_url)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    stop, interrupt = threading.Event(), threading.Event()

    def relay():
        pairs = {}
        try:
            while not stop.is_set():
                if interrupt.is_set():
                    for stream in pairs:
                        stream.close()
                    pairs.clear()
                    interrupt.clear()
                readable, _, _ = select.select([listener, *pairs], [], [], .02)
                for stream in readable:
                    if stream is listener:
                        incoming, _ = listener.accept()
                        outgoing = socket.create_connection((target.hostname, target.port), timeout=2)
                        incoming.settimeout(2)
                        pairs[incoming], pairs[outgoing] = outgoing, incoming
                    elif stream in pairs:
                        other = pairs[stream]
                        try:
                            data = stream.recv(65536)
                            if data:
                                other.sendall(data)
                                continue
                        except OSError:
                            pass
                        pairs.pop(stream)
                        pairs.pop(other)
                        stream.close()
                        other.close()
        finally:
            for stream in pairs:
                stream.close()

    worker = threading.Thread(target=relay)
    worker.start()
    creator = OnlineClient('counter-v1', endpoint=f'ws://127.0.0.1:{listener.getsockname()[1]}')
    guest = None
    try:
        pump(creator, until=lambda: bool(creator.room))
        guest = OnlineClient('counter-v1', endpoint=server_url, room=creator.room)
        pump(creator, guest, until=lambda: creator.ready and guest.ready)
        token = creator.resume_token
        interrupt.set()
        pump(creator, guest, until=lambda: not creator.ready)
        pump(creator, guest, until=lambda: creator.ready and guest.ready)
        assert creator.resume_token == token and creator.player == 0
        creator.submit({'action': 'add'}, revision=creator.revision)
        pump(creator, guest, until=lambda: guest.state['counts'][0] == 1)
        assert creator.state == guest.state
    finally:
        creator.close()
        if guest is not None:
            guest.close()
        stop.set()
        worker.join(timeout=5)
        listener.close()
        assert not worker.is_alive()
