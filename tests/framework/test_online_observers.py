"""Observers watch a hosted room through an explicit role, never a seat.

The scene-facing ``OnlineClient`` and raw sync websockets drive the real
server process: an observer says ``observe`` with only a room code, gets a
welcome with no seat credential, and sees only the game's observer hook.
"""
import json
import time

import pytest
from websockets.sync.client import connect

from saga2d.network import CommandError
from saga2d.online import OnlineClient
from saga2d.testing.online import COUNTER_GAMES, handshake, receive, running_server, server_fixture

GAME = 'counter-observer-v1'
RATED = 'counter-rated-v1'
PLAIN = 'counter-v1'

server_url = server_fixture(COUNTER_GAMES)


def pump(*clients, until, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for client in clients:
            client.poll()
        if until():
            return
        time.sleep(.01)
    raise AssertionError([(client.ready, client.closed, client.error) for client in clients])


def close(*clients):
    for client in clients:
        if client is not None:
            client.close()


def test_observer_watches_lobby_then_game_with_its_own_snapshot(server_url):
    """Watching starts before the guest arrives; seats see seats, the watcher its hook."""
    creator = OnlineClient(GAME, endpoint=server_url, options={'seed': 7})
    watcher = guest = None
    try:
        pump(creator, until=lambda: bool(creator.room))
        watcher = OnlineClient(GAME, endpoint=server_url, room=creator.room, observer=True)
        pump(watcher, until=lambda: watcher.state is not None)
        assert watcher.observer is True
        assert watcher.player is None
        assert watcher.resume_token == '' and watcher.player_token == '' and watcher.player_id == ''
        assert not watcher.ready and not creator.ready
        assert watcher.state == {'seed': 7, 'total': 0, 'ticks': 0, 'watching': True}
        assert watcher.present == 1 and watcher.seats == 2 and watcher.observer_count == 1
        guest = OnlineClient(GAME, endpoint=server_url, room=creator.room)
        pump(creator, guest, watcher, until=lambda: creator.ready and guest.ready and watcher.ready)
        assert watcher.state == {'seed': 7, 'total': 0, 'ticks': 0, 'watching': True}
        assert creator.state != watcher.state
        assert watcher.present == 2 and creator.present == 2
        assert watcher.observer_count == 1 and creator.observer_count == 1
        assert len(watcher.players) == 2 and all(entry['seat'] in (0, 1) for entry in watcher.players)
        assert 'resume_token' not in json.dumps(watcher.players)
        creator.submit({'action': 'add'}, revision=creator.revision)
        pump(creator, guest, watcher, until=lambda: watcher.state['total'] == 1
             and guest.state['counts'] == [1, 0])
    finally:
        close(creator, guest, watcher)


def test_observer_joins_full_seats_and_reobserves_without_a_seat(server_url):
    """Full seats never block a watcher, and watching again mints no seat."""
    creator = OnlineClient(GAME, endpoint=server_url)
    guest = watcher = again = None
    try:
        pump(creator, until=lambda: bool(creator.room))
        guest = OnlineClient(GAME, endpoint=server_url, room=creator.room)
        pump(creator, guest, until=lambda: creator.ready and guest.ready)
        room, first_state = creator.room, dict(guest.state)
        watcher = OnlineClient(GAME, endpoint=server_url, room=room, observer=True)
        pump(watcher, until=lambda: watcher.ready)
        assert watcher.state['total'] == first_state['counts'][0] + first_state['counts'][1]
        watcher.close()
        pump(creator, guest, until=lambda: watcher.closed and creator.observer_count == 0)
        assert creator.ready and guest.ready
        again = OnlineClient(GAME, endpoint=server_url, room=room, observer=True)
        pump(again, until=lambda: again.ready)
        assert again.resume_token == '' and again.player is None
        assert creator.present == 2
        assert [entry['seat'] for entry in creator.players if entry] == [0, 1]
    finally:
        close(creator, guest, watcher, again)


def test_raw_observer_command_is_refused_without_apply(server_url):
    """A forged order over an observer wire earns an error, never a move."""
    creator = None
    with connect(server_url, proxy=None) as host:
        welcome = handshake(host, game=GAME)
        room = welcome['room']
        receive(host)
        with connect(server_url, proxy=None) as watching:
            watching.send(json.dumps({'type': 'observe', 'protocol': 1, 'game': GAME,
                                      'seats': 4, 'room': room}))
            hello = json.loads(watching.recv(timeout=5))
            assert hello['type'] == 'welcome' and hello['observer'] is True
            assert hello['player'] is None
            assert 'resume_token' not in hello and 'player_token' not in hello
            assert 'player_id' not in hello
            first = json.loads(watching.recv(timeout=5))
            assert first['type'] == 'state' and first['observer'] is True
            assert first['state'] == {'seed': 0, 'total': 0, 'ticks': 0, 'watching': True}
            watching.send(json.dumps({'type': 'command', 'command': {'action': 'add'}}))
            refused = json.loads(watching.recv(timeout=5))
            assert refused['type'] == 'error' and 'bserver' in refused['error']
            creator = OnlineClient(GAME, endpoint=server_url, room=room)
            try:
                pump(creator, until=lambda: creator.ready)
                creator.submit({'action': 'add'}, revision=creator.revision)
                second = receive(watching, predicate=lambda message: message['state']['total'] == 1)
                assert second['state'] == {'seed': 0, 'total': 1, 'ticks': 0, 'watching': True}
                assert second['revision'] > first['revision']  # seats joining publish too
            finally:
                creator.close()


def test_observe_without_hook_is_rejected_and_play_continues(server_url):
    """Games that never opted in refuse watchers; their rooms play on untouched."""
    creator = OnlineClient(PLAIN, endpoint=server_url)
    watcher = guest = None
    try:
        pump(creator, until=lambda: bool(creator.room))
        watcher = OnlineClient(PLAIN, endpoint=server_url, room=creator.room, observer=True)
        pump(watcher, until=lambda: watcher.closed)
        assert not watcher.ready and watcher.player is None
        assert 'support observing' in watcher.error
        assert creator.present == 1  # the creator sits in its own room; the refusal changed nothing
        guest = OnlineClient(PLAIN, endpoint=server_url, room=creator.room)
        pump(creator, guest, until=lambda: creator.ready and guest.ready)
        creator.submit({'action': 'add'}, revision=creator.revision)
        pump(creator, guest, until=lambda: guest.state['counts'][0] == 1)
    finally:
        close(creator, guest, watcher)


def test_observer_watches_rated_finish_without_touching_it(server_url):
    """A rated receipt settles exactly once, and the watcher holds no account."""
    from urllib.request import urlopen
    first = OnlineClient(RATED, endpoint=server_url, rated=True,
                         player_options={'race': 'orc'}, player_name='First')
    watcher = second = None
    try:
        pump(first, until=lambda: bool(first.room))
        room = first.room
        watcher = OnlineClient(RATED, endpoint=server_url, room=room, observer=True)
        pump(watcher, until=lambda: watcher.state is not None)
        assert watcher.players[0]['name'] == 'First'
        second = OnlineClient(RATED, endpoint=server_url, room=room,
                              player_options={'race': 'human'}, player_name='Second')
        pump(first, second, watcher, until=lambda: first.ready and second.ready and watcher.ready)
        assert watcher.present == 2
        first.submit({'action': 'add'}, revision=first.revision)
        pump(first, second, watcher, until=lambda: watcher.state['counts'] == [1, 0])
        assert 'races' not in watcher.state
        second.submit({'action': 'resign'}, revision=second.revision)
        pump(first, second, watcher,
             until=lambda: first.result is not None and second.result is not None
             and watcher.result is not None)
        assert watcher.result['winner'] == 0
        assert watcher.result == first.result == second.result
        names = {entry['player_id']: entry for entry in watcher.result['ratings']}
        assert set(names) == {first.player_id, second.player_id}
        http = server_url.replace('ws://', 'http://')
        with urlopen(http + f'/ratings?game={RATED}', timeout=5) as response:
            board = json.loads(response.read())['players']
        assert {entry['player_id'] for entry in board} == {first.player_id, second.player_id}
    finally:
        close(first, second, watcher)


def test_observers_do_not_keep_an_emptied_room_alive():
    """Seats gone is gone: retention runs out under watching eyes, and the watch ends."""
    with running_server(COUNTER_GAMES, arguments=('--room-ttl', '0.4')) as (url, process):
        creator = OnlineClient(GAME, endpoint=url)
        watcher = None
        try:
            pump(creator, until=lambda: bool(creator.room))
            room = creator.room
            watcher = OnlineClient(GAME, endpoint=url, room=room, observer=True)
            pump(watcher, until=lambda: watcher.state is not None)
            creator.close()
            pump(watcher, until=lambda: watcher.closed, timeout=15)
            assert 'expired' in watcher.error
            probe = OnlineClient(GAME, endpoint=url, room=room)
            try:
                pump(probe, until=lambda: probe.closed)
                assert 'Room not found' in probe.error
            finally:
                probe.close()
        finally:
            close(creator, watcher)


def test_observer_constructor_rejects_seat_arguments():
    """Seat credentials and match-making options never ride an observe hello."""
    with pytest.raises(ValueError, match='room code is required'):
        OnlineClient(GAME, endpoint='ws://127.0.0.1:9', room='', observer=True)
    with pytest.raises(ValueError, match='only the room code'):
        OnlineClient(GAME, endpoint='ws://127.0.0.1:9', room='abc', observer=True,
                     resume_token='seat')
    with pytest.raises(ValueError, match='do not sign in'):
        OnlineClient(GAME, endpoint='ws://127.0.0.1:9', room='abc', observer=True,
                     player_token='account')
    with pytest.raises(ValueError, match='do not play rated'):
        OnlineClient(GAME, endpoint='ws://127.0.0.1:9', room='abc', observer=True, rated=True)
    with pytest.raises(ValueError, match='no player options'):
        OnlineClient(GAME, endpoint='ws://127.0.0.1:9', room='abc', observer=True,
                     player_options={'race': 'orc'})
    with pytest.raises(ValueError, match='create no matches'):
        OnlineClient(GAME, endpoint='ws://127.0.0.1:9', room='abc', observer=True,
                     options={'seed': 1})
    with pytest.raises(ValueError, match='no name'):
        OnlineClient(GAME, endpoint='ws://127.0.0.1:9', room='abc', observer=True,
                     player_name='Spy')
    with pytest.raises(ValueError, match='observer must be true or false'):
        OnlineClient(GAME, endpoint='ws://127.0.0.1:9', room='abc', observer='yes')


def test_observer_submit_is_refused_locally(server_url):
    """Watchers cannot even queue an order, online or off."""
    creator = OnlineClient(GAME, endpoint=server_url)
    watcher = None
    try:
        pump(creator, until=lambda: bool(creator.room))
        watcher = OnlineClient(GAME, endpoint=server_url, room=creator.room, observer=True)
        pump(watcher, until=lambda: watcher.state is not None)
        with pytest.raises(CommandError, match='bservers cannot submit'):
            watcher.submit({'action': 'add'})
    finally:
        close(creator, watcher)


def test_seats_learn_watcher_count_without_new_revision(server_url):
    """Watcher arrival and departure refresh seat metadata in place: the same
    revision and game data reach the seats, with no new match event."""
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        welcome = handshake(host, game=GAME)
        room = welcome['room']
        assert receive(host)['observer_count'] == 0
        handshake(guest, 'join', game=GAME, room=room)
        joined = receive(host, predicate=lambda message: message['ready'])
        revision, base = joined['revision'], joined['state']
        with connect(server_url, proxy=None) as watching:
            watching.send(json.dumps({'type': 'observe', 'protocol': 1, 'game': GAME,
                                      'seats': 4, 'room': room}))
            hello = receive(watching, 'welcome')
            assert hello['observer'] is True and hello['player'] is None
            refreshed = receive(host, predicate=lambda message: message['observer_count'] == 1)
            assert refreshed['revision'] == revision
            assert refreshed['state'] == base
            assert receive(watching)['observer'] is True
        left = receive(host, predicate=lambda message: message['observer_count'] == 0)
        assert left['revision'] == revision
        assert left['state'] == base


def test_suspend_detaches_watchers_and_reobserve_restores(tmp_path):
    """An emptied campaign lets its watchers go with an explicit refusal that
    keeps retention; watching again restores the room."""
    campaign = 'counter-campaign-observer-v1'
    arguments = ('--state-dir', str(tmp_path), '--room-ttl', '.15', '--campaign-ttl', '5')
    with running_server(COUNTER_GAMES, arguments=arguments) as (url, process):
        with connect(url, proxy=None) as watching:
            with connect(url, proxy=None) as host:
                seat = handshake(host, game=campaign)
                room = seat['room']
                with connect(url, proxy=None) as guest:
                    handshake(guest, 'join', game=campaign, room=room)
                    receive(host, predicate=lambda message: message['ready'])
                    watching.send(json.dumps({'type': 'observe', 'protocol': 1, 'game': campaign,
                                              'seats': 4, 'room': room}))
                    receive(watching, 'welcome')
                    receive(watching)
            time.sleep(.3)  # Both seats absent beyond the match TTL: the campaign suspends.
            refusal = None
            for _ in range(100):
                message = json.loads(watching.recv(timeout=5))
                if message['type'] == 'reject':
                    refusal = message
                    break
            assert refusal is not None and 'suspend' in refusal['error']
        with connect(url, proxy=None) as again:
            again.send(json.dumps({'type': 'observe', 'protocol': 1, 'game': campaign,
                                   'seats': 4, 'room': room}))
            hello = receive(again, 'welcome')
            assert hello['observer'] is True and hello['player'] is None
            assert receive(again)['observer'] is True


def test_oversized_watcher_view_refuses_only_the_watcher(server_url):
    """A watcher view grown past the frame cap ends watching; the seats play on."""
    creator = OnlineClient('counter-grow-v1', endpoint=server_url)
    guest = watcher = None
    try:
        pump(creator, until=lambda: bool(creator.room))
        guest = OnlineClient('counter-grow-v1', endpoint=server_url, room=creator.room)
        pump(creator, guest, until=lambda: creator.ready and guest.ready)
        watcher = OnlineClient('counter-grow-v1', endpoint=server_url, room=creator.room, observer=True)
        pump(watcher, until=lambda: watcher.ready)
        assert watcher.state['bulk'] == ''
        for _ in range(9):  # nine mebibytes of watcher view against an eight-mebibyte cap
            before = creator.revision
            creator.submit({'action': 'grow'}, revision=before)
            pump(creator, guest, until=lambda: creator.revision > before
                 and guest.revision == creator.revision)
        pump(watcher, until=lambda: watcher.closed, timeout=30)
        assert watcher.error == 'The observer view failed.'
        assert creator.ready and guest.ready
        creator.submit({'action': 'add'}, revision=creator.revision)
        pump(creator, guest, until=lambda: guest.state['counts'] == [1, 0])
    finally:
        close(creator, guest, watcher)
