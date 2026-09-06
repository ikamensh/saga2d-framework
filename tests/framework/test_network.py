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
