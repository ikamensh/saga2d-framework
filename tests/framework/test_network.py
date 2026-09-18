"""Real loopback sockets exercise the same host/join interface the games use."""
import time

from saga2d import MatchHost, MatchClient


def pump(host, client, until):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        host.poll()
        client.poll()
        if until():
            return
        time.sleep(.001)
    raise AssertionError('network did not converge')


def test_two_players_receive_authoritative_state_after_a_guest_command():
    """Clients get their assigned seat and the host applies their commands exactly once."""
    counts = [0, 0]
    def apply(player, command):
        counts[player] += command['amount']
    host = MatchHost('counter-v1', apply, lambda player: {'counts': counts, 'you': player}, address=('127.0.0.1', 0), token='test')
    client = MatchClient('counter-v1', host.address, token='test')
    try:
        pump(host, client, lambda: client.ready and host.ready)
        assert client.player == 1
        client.submit({'amount': 3})
        pump(host, client, lambda: client.state['counts'] == [0, 3])
        host.submit({'amount': 2})
        pump(host, client, lambda: client.state['counts'] == [2, 3])
        assert host.state == {'counts': [2, 3], 'you': 0}
    finally:
        client.close()
        host.close()


def test_rejected_and_stale_commands_leave_match_unchanged_and_rejoin_resyncs():
    """Bad commands stay local to their sender; a dropped guest can reclaim its seat."""
    from saga2d import CommandError
    count = [0]
    def apply(player, command):
        if command.get('amount') != 1:
            raise CommandError('Only one at a time.')
        count[0] += 1
    host = MatchHost('counter-v1', apply, lambda _: {'count': count[0]}, address=('127.0.0.1', 0), token='test')
    client = MatchClient('counter-v1', host.address, token='test')
    try:
        pump(host, client, lambda: client.ready)
        old = client.revision
        host.submit({'amount': 1})
        client.submit({'amount': 1}, revision=old)
        pump(host, client, lambda: bool(client.error))
        assert count == [1]
        client.error = ''
        client.submit({'amount': 3})
        pump(host, client, lambda: bool(client.error))
        assert client.error == 'Only one at a time.'
        assert count == [1]
        client.close()
        pump(host, client, lambda: not host.ready)
        client = MatchClient('counter-v1', host.address, token='test')
        pump(host, client, lambda: client.ready)
        assert client.state == {'count': 1}
    finally:
        client.close()
        host.close()


def test_wrong_game_and_token_are_rejected_without_consuming_the_seat():
    """A lobby cannot accidentally pair different games or admit the wrong room code."""
    host = MatchHost('game-a', lambda *_: None, lambda _: {}, address=('127.0.0.1', 0), token='secret')
    try:
        for game_id, token in [('game-b', 'secret'), ('game-a', 'wrong')]:
            client = MatchClient(game_id, host.address, token=token)
            try:
                pump(host, client, lambda: client.closed and host.peer is None)
                assert not host.ready
                assert 'Wrong game' in client.error
            finally:
                client.close()
    finally:
        host.close()


def test_scene_connection_survives_overlays_and_closes_on_removal(game):
    """Covering a scene must keep its socket alive; removing it must release it."""
    from saga2d import Scene
    host = MatchHost('test', lambda *_: None, lambda _: {}, address=('127.0.0.1', 0), token='test')
    class Room(Scene):
        def on_close(self):
            host.close()
    game.push(Room())
    game.push(Scene())
    assert not host.closed
    game.pop()
    assert not host.closed
    game.pop()
    assert host.closed


def test_failed_scene_entry_closes_its_connection(game):
    """An unusable match scene must not leave its listening port behind."""
    import pytest
    from saga2d import Scene
    host = MatchHost('test', lambda *_: None, lambda _: {}, address=('127.0.0.1', 0), token='test')
    class FailedRoom(Scene):
        def on_enter(self):
            raise RuntimeError('broken setup')
        def on_close(self):
            host.close()
    with pytest.raises(RuntimeError, match='broken setup'):
        game.push(FailedRoom())
    assert host.closed


def test_entering_a_match_removes_lobby_and_title_resources(game):
    """A title backdrop must not remain visible through a new match's fog of war."""
    from saga2d import MatchLobby, Scene
    host = MatchHost('test', lambda *_: None, lambda _: {}, address=('127.0.0.1', 0), token='test')
    client = MatchClient('test', host.address, token='test')
    match_scene = Scene()
    try:
        game.push(Scene())
        game.push(MatchLobby(client, lambda _: match_scene))
        pump(host, client, lambda: client.ready)
        game.tick(.03)
        assert game.scenes == [match_scene]
        assert client.ready
    finally:
        client.close()
        host.close()


def test_a_guest_slower_than_the_match_sees_the_newest_state_not_a_growing_backlog():
    """A real-time host publishes ten large states a second whatever the guest's frame rate.

    The guest once read at most 64 KB per poll and the host queued every state behind the last,
    so a guest rendering slowly fell further behind with every frame until the host's queue
    overflowed and dropped it.  A poll now reads all there is, and a state still waiting to be
    sent is replaced by the newer one.
    """
    ballast = 'x' * 150_000  # a Warband snapshot is 100 to 140 KB
    tick = [0]
    host = MatchHost('rts-v1', lambda player, command: None, lambda player: {'tick': tick[0], 'ballast': ballast},
                     address=('127.0.0.1', 0), token='test')
    client = MatchClient('rts-v1', host.address, token='test')
    try:
        pump(host, client, lambda: client.ready and host.ready)
        behind = []
        for _ in range(60):  # six seconds of match for a guest at two frames a second
            for _ in range(5):
                tick[0] += 1
                host.publish()
                host.poll()
            client.poll()
            assert host.ready, f'the host dropped its guest: {host.error}'
            behind.append(tick[0] - client.state['tick'])
        assert max(behind[10:]) <= 10, f'the guest fell behind without bound: {behind}'
        assert len(host.peer.outgoing) < 4 * len(ballast), 'the host queues states the guest will never need'
        pump(host, client, lambda: client.state['tick'] == tick[0])  # and once the match pauses it has the last word
    finally:
        client.close()
        host.close()
