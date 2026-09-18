"""Rooms of more than two seats (S2D-011), against the production server process.

The game says how many seats a room has and which of them must be connected for play to go on; a client says
how many seats it handles, and one from before larger rooms says nothing and is kept to rooms of two.
"""
from contextlib import ExitStack, contextmanager
import json
import time

from websockets.sync.client import connect

from saga2d import Game, Scene
from saga2d.testing.online import COUNTER_GAMES, command, handshake, receive, running_server, server_fixture

SEATED = 'counter-seats-v1'
server_url = server_fixture(COUNTER_GAMES)


def refusal(socket, kind='create', **fields) -> dict:
    """The server's answer to a request it turns down."""
    socket.send(json.dumps({'type': kind, 'protocol': 1, **fields}))
    message = json.loads(socket.recv(timeout=5))
    assert message['type'] == 'reject', message
    return message


@contextmanager
def seated(url: str, count: int):
    """*count* connections, the first creating a room of *count* seats and the rest joining it in order."""
    with ExitStack() as stack:
        sockets = [stack.enter_context(connect(url, proxy=None)) for _ in range(count)]
        welcome = handshake(sockets[0], game=SEATED, seats=4, options={'seats': count})
        seats = [welcome] + [handshake(socket, 'join', game=SEATED, room=welcome['room'], seats=4) for socket in sockets[1:]]
        yield sockets, seats


def test_a_four_seat_room_fills_in_order_starts_when_all_are_in_and_refuses_a_fifth(server_url):
    with seated(server_url, 4) as (sockets, seats):
        assert [(seat['player'], seat['seats']) for seat in seats] == [(0, 4), (1, 4), (2, 4), (3, 4)]
        assert len({seat['resume_token'] for seat in seats}) == 4
        full = receive(sockets[0], predicate=lambda message: message['ready'])
        assert (full['seats'], full['present']) == (4, 4)
        for socket in sockets[1:]:
            assert receive(socket, predicate=lambda message: message['ready'])['player'] == sockets.index(socket)
        command(sockets[2], {'action': 'add'})
        counted = receive(sockets[0], predicate=lambda message: message['state']['counts'][2] == 1)
        assert counted['state']['counts'] == [0, 0, 1, 0]
        with connect(server_url, proxy=None) as fifth:
            assert 'Every seat is claimed' in refusal(fifth, 'join', game=SEATED, room=seats[0]['room'], seats=4)['error']


def test_a_needed_seat_that_leaves_pauses_the_room_and_one_out_of_the_match_does_not(server_url):
    with seated(server_url, 3) as (sockets, seats):
        first, second, third = sockets
        receive(first, predicate=lambda message: message['ready'])
        third.close()
        paused = receive(first, predicate=lambda message: not message['ready'])
        assert paused['present'] == 2
        with connect(server_url, proxy=None) as back:
            returned = handshake(back, 'resume', game=SEATED, room=seats[0]['room'], resume_token=seats[2]['resume_token'], seats=4)
            assert returned['player'] == 2
            receive(first, predicate=lambda message: message['ready'] and message['present'] == 3)
            command(second, {'action': 'drop'})  # out of the match: no longer needed in the room
            time.sleep(.2)
            second.close()
            left = receive(first, predicate=lambda message: message['present'] == 2)
            assert left['ready'], "a player out of the match paused the room by leaving"
            ticks = left['state']['ticks']
            assert receive(first, predicate=lambda message: message['state']['ticks'] > ticks + 5)['ready']


def test_a_restart_keeps_every_seats_token(tmp_path):
    with running_server(COUNTER_GAMES, arguments=('--state-dir', tmp_path)) as (url, process):
        with seated(url, 3) as (sockets, seats):
            receive(sockets[0], predicate=lambda message: message['ready'])
    with running_server(COUNTER_GAMES, arguments=('--state-dir', tmp_path)) as (url, process), ExitStack() as stack:
        sockets = [stack.enter_context(connect(url, proxy=None)) for _ in seats]
        for socket, seat in zip(sockets, seats):
            back = handshake(socket, 'resume', game=SEATED, room=seat['room'], resume_token=seat['resume_token'], seats=4)
            assert (back['player'], back['seats']) == (seat['player'], 3)
        assert receive(sockets[0], predicate=lambda message: message['ready'])['present'] == 3


def test_a_client_from_before_larger_rooms_is_refused_from_them_and_plays_in_rooms_of_two(server_url):
    with connect(server_url, proxy=None) as old:
        refused = refusal(old, game=SEATED, options={'seats': 3})  # its hello says nothing of seats
        assert refused.get('reason') == 'incompatible' and 'Update your game client' in refused['error']
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as old, \
            connect(server_url, proxy=None) as first, connect(server_url, proxy=None) as second:
        welcome = handshake(host, game=SEATED, seats=4, options={'seats': 3})
        assert refusal(old, 'join', game=SEATED, room=welcome['room']).get('reason') == 'incompatible'
        assert handshake(first, 'join', game=SEATED, room=welcome['room'], seats=4)['player'] == 1  # the refusal took no seat
        assert handshake(second, 'join', game=SEATED, room=welcome['room'], seats=4)['player'] == 2
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        welcome = handshake(host, game='counter-v1', options={'seed': 3})
        assert (welcome['player'], welcome['seats']) == (0, 2)
        assert handshake(guest, 'join', game='counter-v1', room=welcome['room'])['player'] == 1
        assert receive(host, predicate=lambda message: message['ready'])['present'] == 2


def test_the_online_client_and_lobby_know_a_room_of_three(server_url, tmp_path):
    from saga2d.multiplayer_ui import MatchLobby
    from saga2d.online import OnlineClient

    game = Game('seats lobby', backend='mock', resolution=(1280, 800), save_dir=tmp_path / 'saves')
    creator = OnlineClient(SEATED, endpoint=server_url, options={'seats': 3})
    guests = []

    def texts():
        return '\n'.join(item['text'] for item in game.backend.texts)

    def until(condition):
        deadline = time.monotonic() + 10
        while not condition() and time.monotonic() < deadline:
            game.tick(.03)
            for guest in guests:
                guest.poll()
            time.sleep(.02)
        assert condition()

    try:
        game.push(MatchLobby(creator, lambda session: Scene(), title="Counter online"))
        until(lambda: creator.state is not None)
        assert (creator.player, creator.seats, creator.present, creator.ready) == (0, 3, 1, False)
        until(lambda: 'Waiting for players · 1 of 3' in texts())
        assert 'all 3 of you' in texts()
        guests.append(OnlineClient(SEATED, endpoint=server_url, room=creator.room))
        until(lambda: 'Waiting for players · 2 of 3' in texts())
        guests.append(OnlineClient(SEATED, endpoint=server_url, room=creator.room))
        until(lambda: creator.ready and all(guest.ready for guest in guests))
        assert creator.present == 3 and sorted(guest.player for guest in guests) == [1, 2]
    finally:
        for client in (creator, *guests):
            client.close()
        game.close()
