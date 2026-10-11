"""Server-authoritative ratings and durable player identity, against the production server process.

Each test proves one public behaviour through the real WebSocket protocol or the
scene-facing client: who players are across rooms and restarts, which rooms may
be rated, and how a joining seat's private options reach the match.
"""
import json
import time

import pytest

from websockets.sync.client import connect

from saga2d.network import CommandError
from saga2d.server import player_name, settle_ratings
from saga2d.testing.online import COUNTER_GAMES, command, handshake, receive, running_server, server_fixture

GAME = 'counter-v1'
RATED = 'counter-rated-v1'
server_url = server_fixture(COUNTER_GAMES)


def test_unsupported_games_take_no_rated_rooms(server_url):
    """A rated create on a game without an authoritative result is refused clearly."""
    with connect(server_url, proxy=None) as host:
        host.send(json.dumps({'type': 'create', 'protocol': 1, 'game': GAME, 'rated': True}))
        rejection = receive(host, 'reject')
        assert 'rated' in rejection['error'].lower()


def test_every_create_and_join_gets_a_distinct_identity(server_url):
    """Old clients that send no account fields still come home with a player id and token."""
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        welcome = handshake(host, game=GAME)
        assert welcome['player_id'] and welcome['player_token']
        assert welcome['rating'] == {'player_id': welcome['player_id'], 'name': 'Commander',
                                     'rating': 1500.0, 'games': 0, 'wins': 0, 'losses': 0}
        joined = handshake(guest, 'join', game=GAME, room=welcome['room'])
        assert joined['player_id'] != welcome['player_id']
        assert joined['player_token'] != welcome['player_token']


def test_an_account_keeps_its_identity_across_rooms_while_names_collide_freely(server_url):
    """The token is the identity; the name is display data, so two Commanders are two players."""
    with connect(server_url, proxy=None) as first, connect(server_url, proxy=None) as second:
        welcome = handshake(first, game=GAME, player_name='Commander')
        second_welcome = handshake(second, game=GAME, player_name='Commander')
        assert second_welcome['player_id'] != welcome['player_id']
    with connect(server_url, proxy=None) as back:
        again = handshake(back, game=GAME, player_token=welcome['player_token'], player_name='Someone Else')
        assert again['player_id'] == welcome['player_id']
        assert again['player_token'] == welcome['player_token']


def test_a_nameless_resume_and_rejoin_keep_the_known_account_name(server_url):
    """Reconnect hellos carry the token but no name: resuming by seat token plus
    account token, and opening a new room by account token alone, both preserve
    Robin (and the rating), instead of renaming back to the default."""
    with connect(server_url, proxy=None) as host:
        welcome = handshake(host, game=RATED, rated=True, player_name='Robin')
        receive(host)
        code, seat_token, account_token = welcome['room'], welcome['resume_token'], welcome['player_token']
    with connect(server_url, proxy=None) as resumed:
        back = handshake(resumed, 'resume', game=RATED, room=code, resume_token=seat_token,
                         player_token=account_token)
        assert back['player'] == 0
        assert back['rating']['name'] == 'Robin'
        state = receive(resumed)
        assert state['players'][0]['name'] == 'Robin'
    with connect(server_url, proxy=None) as fresh:
        again = handshake(fresh, game=RATED, rated=True, player_token=account_token)
        assert again['player_id'] == welcome['player_id']
        assert again['rating'] == {'player_id': welcome['player_id'], 'name': 'Robin',
                                   'rating': 1500.0, 'games': 0, 'wins': 0, 'losses': 0}


def test_an_unknown_account_token_changes_nothing(server_url):
    """A forged token is refused before any seat is claimed or socket replaced."""
    with connect(server_url, proxy=None) as host:
        welcome = handshake(host, game=GAME)
        receive(host)
        with connect(server_url, proxy=None) as guest:
            guest.send(json.dumps({'type': 'join', 'protocol': 1, 'game': GAME,
                                   'room': welcome['room'], 'player_token': 'forged'}))
            assert 'token' in receive(guest, 'reject')['error'].lower()
        # A rejected socket is closed; a fresh connection takes the untouched seat in the same room.
        with connect(server_url, proxy=None) as guest:
            assert handshake(guest, 'join', game=GAME, room=welcome['room'])['player'] == 1
        assert receive(host, predicate=lambda message: message['ready'])['ready']


def test_a_race_choice_reaches_the_match_and_a_bad_choice_leaves_the_seat_free(server_url):
    """The joiner's private options configure their seat; malformed ones consume no seat."""
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        welcome = handshake(host, game=RATED, rated=True, player_options={'race': 'orc'})
        handshake(guest, 'join', game=RATED, room=welcome['room'], player_options={'race': 'orc'})
        ready = receive(host, predicate=lambda message: message['ready'])
        assert ready['state']['races'] == ['orc', 'orc']
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as bad:
        welcome = handshake(host, game=RATED, rated=True)
        receive(host)
        bad.send(json.dumps({'type': 'join', 'protocol': 1, 'game': RATED,
                             'room': welcome['room'], 'player_options': {'race': 'elf'}}))
        assert 'race' in receive(bad, 'reject')['error'].lower()
        with connect(server_url, proxy=None) as guest:
            assert handshake(guest, 'join', game=RATED, room=welcome['room'])['player'] == 1


@pytest.mark.parametrize('value, expected', [
    (None, 'Commander'),
    ('  Robin  ', 'Robin'),
    ('x' * 32, 'x' * 32),
])
def test_player_names_trim_and_accept_the_maximum(value, expected):
    """Display names trim padding and accept the full 32 characters."""
    assert player_name(value) == expected


@pytest.mark.parametrize('value', [
    '', '   ', 'x' * 33, 'Robin\n', '\nRobin\n', 'Rob\tin', 'Rob\x7fin', 123, ['Robin'],
])
def test_player_names_reject_empty_long_control_and_foreign_values(value):
    """Names are display data with clear errors: padded newlines do not sneak through,
    and long names are refused rather than silently truncated."""
    with pytest.raises(CommandError):
        player_name(value)


def test_elo_moves_points_from_losers_to_winner_and_conserves_the_sum():
    """The winner's gain equals the losers' combined loss; games, wins and losses tally."""
    entries = [{'player_id': f'p{i}', 'name': f'P{i}', 'rating': 1500.0, 'games': 2, 'wins': 1, 'losses': 1}
               for i in range(3)]
    records = settle_ratings(entries, 0)
    assert abs(sum(record['delta'] for record in records)) < 1e-9
    assert records[0]['delta'] > 0 and all(record['delta'] < 0 for record in records[1:])
    assert records[0]['after'] == 1500.0 + records[0]['delta']
    assert [(record['games'], record['wins'], record['losses']) for record in records] == [(3, 2, 1)] + [(3, 1, 2)] * 2
    assert entries[0]['rating'] == 1500.0, 'settlement must read pre-match ratings, not mutate its inputs'


def test_a_rated_lobby_waits_out_grace_and_starts_normally_when_the_guest_arrives():
    """The abandon clock never runs before every needed seat connected once: a lone
    creator waits past a short grace with no winner and no ratings, then a valid
    guest joins and the game starts."""
    with running_server(COUNTER_GAMES, arguments=('--rated-grace', '0.3')) as (url, process):
        with connect(url, proxy=None) as host:
            welcome = handshake(host, game=RATED, rated=True)
            assert welcome['rated'] is True and welcome['match_id']
            assert welcome['rated_grace'] == 0.3
            lobby = receive(host)
            assert lobby['rated'] is True and lobby['result'] is None and not lobby['ready']
            time.sleep(0.6)
            assert lobby['result'] is None
            with connect(url, proxy=None) as guest:
                handshake(guest, 'join', game=RATED, room=welcome['room'])
                ready = receive(host, predicate=lambda message: message['ready'])
                receive(guest, predicate=lambda message: message['ready'])
                assert ready['match_id'] == welcome['match_id']
                assert ready['result'] is None
                command(host, {'action': 'add'})
                assert receive(guest)['state']['counts'] == [1, 0]


def test_a_restart_gives_absent_seats_fresh_grace_before_any_forfeit():
    """After a restart one returning player must not instantly defeat the others:
    every claimed absent seat's grace runs from startup."""
    import tempfile
    with tempfile.TemporaryDirectory() as state_dir:
        with running_server(COUNTER_GAMES, arguments=('--state-dir', state_dir, '--rated-grace', '0.3')) as (url, process):
            with connect(url, proxy=None) as host, connect(url, proxy=None) as guest:
                welcome = handshake(host, game=RATED, rated=True)
                guest_welcome = handshake(guest, 'join', game=RATED, room=welcome['room'])
                assert receive(host, predicate=lambda message: message['ready'])['ready']
        with running_server(COUNTER_GAMES, arguments=('--state-dir', state_dir, '--rated-grace', '0.3')) as (url, process):
            with connect(url, proxy=None) as host:
                resumed = handshake(host, 'resume', game=RATED, room=welcome['room'],
                                    resume_token=welcome['resume_token'])
                assert resumed['player'] == 0
                time.sleep(0.15)  # inside the fresh post-restart grace: no forfeit yet
                with connect(url, proxy=None) as guest:
                    handshake(guest, 'resume', game=RATED, room=welcome['room'],
                              resume_token=guest_welcome['resume_token'])
                    assert receive(host, predicate=lambda message: message['ready'])['ready']
                    receive(guest, predicate=lambda message: message['ready'])
                    command(host, {'action': 'add'})
                    assert receive(guest)['state']['counts'] == [1, 0]


def test_a_shared_outage_grants_a_fresh_window_instead_of_an_instant_defeat():
    """While no needed seat is connected the outage consumes no grace: both seats
    return before the fresh window ends and play on with no forfeit."""
    with running_server(COUNTER_GAMES, arguments=('--rated-grace', '0.4')) as (url, process):
        with connect(url, proxy=None) as host, connect(url, proxy=None) as guest:
            welcome = handshake(host, game=RATED, rated=True)
            guest_welcome = handshake(guest, 'join', game=RATED, room=welcome['room'])
            assert receive(host, predicate=lambda message: message['ready'])['ready']
        time.sleep(0.6)  # both offline past the grace: still paused, nobody forfeited
        with connect(url, proxy=None) as host, connect(url, proxy=None) as guest:
            handshake(host, 'resume', game=RATED, room=welcome['room'], resume_token=welcome['resume_token'])
            handshake(guest, 'resume', game=RATED, room=welcome['room'],
                      resume_token=guest_welcome['resume_token'])
            ready = receive(host, predicate=lambda message: message['ready'])
            receive(guest, predicate=lambda message: message['ready'])
            assert ready['result'] is None
            command(host, {'action': 'add'})
            assert receive(guest)['state']['counts'] == [1, 0]


def test_one_account_cannot_hold_two_seats_in_a_rated_room(server_url):
    """The same identity claiming a second rated seat is refused before any seat
    token changes; a valid guest still joins the untouched seat."""
    with connect(server_url, proxy=None) as host:
        welcome = handshake(host, game=RATED, rated=True, player_name='Robin')
        receive(host)
        with connect(server_url, proxy=None) as double:
            double.send(json.dumps({'type': 'join', 'protocol': 1, 'game': RATED,
                                    'room': welcome['room'], 'player_token': welcome['player_token']}))
            assert 'already holds a seat' in receive(double, 'reject')['error']
        with connect(server_url, proxy=None) as guest:
            joined = handshake(guest, 'join', game=RATED, room=welcome['room'], player_name='Robin')
            assert joined['player'] == 1 and joined['player_id'] != welcome['player_id']
        assert receive(host, predicate=lambda message: message['ready'])['ready']


def test_a_rated_finish_rates_winner_and_losers_once(server_url):
    """The authoritative finish settles every participant exactly once: the winner
    gains, the loser loses, games tally, and the receipt names the match."""
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        welcome = handshake(host, game=RATED, rated=True, player_name='Robin')
        guest_welcome = handshake(guest, 'join', game=RATED, room=welcome['room'], player_name='Wren')
        receive(host, predicate=lambda message: message['ready'])
        receive(guest, predicate=lambda message: message['ready'])
        command(host, {'action': 'add'})
        receive(host)
        receive(guest)
        command(guest, {'action': 'finish'})
        settled = receive(host, predicate=lambda message: message['result'] is not None)
        result = settled['result']
        assert result['match_id'] == welcome['match_id'] and result['winner'] == 0
        assert abs(sum(entry['delta'] for entry in result['ratings'])) < 1e-9
        winner, loser = result['ratings']
        assert winner['delta'] > 0 and loser['delta'] < 0
        assert (winner['games'], winner['wins'], winner['losses']) == (1, 1, 0)
        assert (loser['games'], loser['wins'], loser['losses']) == (1, 0, 1)
        assert receive(guest)['result'] == result
        players = {entry['player_id']: entry for entry in settled['players'] if entry is not None}
        assert players[welcome['player_id']]['rating'] == winner['after']
        assert players[guest_welcome['player_id']]['rating'] == loser['after']
        command(host, {'action': 'add'})
        assert 'over' in receive(host, 'error')['error'].lower()
        names = sorted(entry['name'] for entry in result['ratings'])
        assert names == ['Robin', 'Wren']


def test_a_three_seat_rated_match_splits_the_win_across_two_losers(server_url):
    """With three seats each pair delta is halved: the winner takes both halves,
    each loser gives up one, and the sum stays zero."""
    from contextlib import ExitStack
    with ExitStack() as stack:
        sockets = [stack.enter_context(connect(server_url, proxy=None)) for _ in range(3)]
        welcome = handshake(sockets[0], game=RATED, rated=True, seats=3, options={'seats': 3})
        handshake(sockets[1], 'join', game=RATED, room=welcome['room'], seats=3)
        handshake(sockets[2], 'join', game=RATED, room=welcome['room'], seats=3)
        receive(sockets[0], predicate=lambda message: message['ready'])
        command(sockets[2], {'action': 'add'})
        command(sockets[2], {'action': 'add'})
        for socket in sockets:
            receive(socket, predicate=lambda message: message['state']['counts'] == [0, 0, 2])
        command(sockets[0], {'action': 'finish'})
        settled = receive(sockets[0], predicate=lambda message: message['result'] is not None)
        result = settled['result']
        assert result['winner'] == 2
        assert abs(sum(entry['delta'] for entry in result['ratings'])) < 1e-9
        assert result['ratings'][2]['delta'] > 0
        assert all(entry['delta'] < 0 for entry in result['ratings'][:2])
        assert all(entry['games'] == 1 for entry in result['ratings'])


def test_a_resign_hands_the_rated_match_to_the_last_seat_standing(server_url):
    """An accepted resign is an authoritative outcome too: the resigner loses."""
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        welcome = handshake(host, game=RATED, rated=True)
        handshake(guest, 'join', game=RATED, room=welcome['room'])
        receive(host, predicate=lambda message: message['ready'])
        command(guest, {'action': 'resign'})
        settled = receive(host, predicate=lambda message: message['result'] is not None)
        assert settled['result']['winner'] == 0
        assert settled['result']['ratings'][1]['losses'] == 1
        assert settled['result']['ratings'][0]['wins'] == 1


def test_a_casual_finish_rates_nobody(server_url):
    """The same authoritative finish in a casual room leaves every rating at its start."""
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        welcome = handshake(host, game=RATED)
        assert welcome['rated'] is False
        handshake(guest, 'join', game=RATED, room=welcome['room'])
        receive(host, predicate=lambda message: message['ready'])
        command(host, {'action': 'finish'})
        finished = receive(host, predicate=lambda message: message['state']['winner'] == 0)
        assert finished['result'] is None
        assert all(entry['games'] == 0 for entry in finished['players'] if entry is not None)


def test_resumes_and_restarts_cannot_rate_a_match_twice(tmp_path):
    """Reconnects, duplicate end polls and a server restart all see one receipt:
    every participant's games tally stays at one."""
    with running_server(COUNTER_GAMES, arguments=('--state-dir', str(tmp_path))) as (url, process):
        with connect(url, proxy=None) as host, connect(url, proxy=None) as guest:
            welcome = handshake(host, game=RATED, rated=True)
            guest_welcome = handshake(guest, 'join', game=RATED, room=welcome['room'])
            receive(host, predicate=lambda message: message['ready'])
            command(host, {'action': 'finish'})
            first = receive(host, predicate=lambda message: message['result'] is not None)
            assert first['result']['winner'] == 0
    with running_server(COUNTER_GAMES, arguments=('--state-dir', str(tmp_path))) as (url, process):
        with connect(url, proxy=None) as host, connect(url, proxy=None) as guest:
            resumed = handshake(host, 'resume', game=RATED, room=welcome['room'],
                                resume_token=welcome['resume_token'])
            assert resumed['player'] == 0
            handshake(guest, 'resume', game=RATED, room=welcome['room'],
                      resume_token=guest_welcome['resume_token'])
            returned = receive(host, predicate=lambda message: message['ready'])
            assert returned['result'] == first['result']
            assert all(entry['games'] == 1 for entry in returned['players'] if entry is not None)


def test_a_resume_with_a_foreign_account_token_is_refused(server_url):
    """A valid seat token paired with another account's token resolves to neither:
    the seat stays with its owner, whose plain seat-token resume still works."""
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        welcome = handshake(host, game=RATED, rated=True)
        other = handshake(guest, game=GAME)
        receive(host)
        with connect(server_url, proxy=None) as intruder:
            intruder.send(json.dumps({'type': 'resume', 'protocol': 1, 'game': RATED,
                                      'room': welcome['room'], 'resume_token': welcome['resume_token'],
                                      'player_token': other['player_token']}))
            assert 'different account' in receive(intruder, 'reject')['error']
        with connect(server_url, proxy=None) as owner:
            resumed = handshake(owner, 'resume', game=RATED, room=welcome['room'],
                                resume_token=welcome['resume_token'])
            assert resumed['player'] == 0


def test_an_absent_rated_seat_forfeits_past_grace_while_the_lobby_never_does():
    """One missing seat past a short grace loses to the connected seat through the
    game's abandon hook; both offline stays paused with no result."""
    with running_server(COUNTER_GAMES, arguments=('--rated-grace', '0.3')) as (url, process):
        with connect(url, proxy=None) as host, connect(url, proxy=None) as guest:
            welcome = handshake(host, game=RATED, rated=True)
            handshake(guest, 'join', game=RATED, room=welcome['room'])
            assert receive(host, predicate=lambda message: message['ready'])['ready']
            guest.close()
            forfeited = receive(host, predicate=lambda message: message['result'] is not None)
            assert forfeited['result']['winner'] == 0
            assert forfeited['result']['ratings'][1]['losses'] == 1
            assert forfeited['state']['winner'] == 0, 'only the actual game winner settles'


def test_public_status_leaderboard_and_profile_hide_every_secret(tmp_path):
    """Counts and public profiles are JSON for anyone; room codes, tokens, names of
    rooms and hidden game info never appear, and bad queries fail appropriately."""
    from urllib.request import urlopen
    from urllib.error import HTTPError
    with running_server(COUNTER_GAMES, arguments=('--state-dir', str(tmp_path))) as (url, process):
        http = url.replace('ws://', 'http://')
        with connect(url, proxy=None) as host, connect(url, proxy=None) as guest:
            welcome = handshake(host, game=RATED, rated=True, player_name='Robin')
            handshake(guest, 'join', game=RATED, room=welcome['room'], player_name='Wren')
            receive(host, predicate=lambda message: message['ready'])
            command(host, {'action': 'finish'})
            settled = receive(host, predicate=lambda message: message['result'] is not None)

        def get(path):
            with urlopen(http + path, timeout=5) as response:
                assert response.headers.get_content_type() == 'application/json'
                return json.loads(response.read())

        def fails(path, code):
            try:
                urlopen(http + path, timeout=5)
            except HTTPError as exc:
                assert exc.code == code, (path, exc.code)
                assert exc.headers.get_content_type() == 'application/json'
            else:
                raise AssertionError(f'{path} should fail with {code}')

        status = get('/status')
        assert status['protocol'] == 1 and RATED in status['games']
        assert status['rooms'] >= 1 and status['rated_grace'] == 60
        assert status['ratings'][RATED] == {'enabled': True, 'seats': [2, 3, 4], 'starting_rating': 1500.0}
        assert status['ratings'][GAME] == {'enabled': False, 'seats': [], 'starting_rating': 1500.0}
        blob = json.dumps(status)
        assert 'token' not in blob.lower() and welcome['room'] not in blob
        assert welcome['player_id'] not in blob, 'status carries counts only, no identities'

        board = get(f'/ratings?game={RATED}')
        assert board['game'] == RATED
        assert [entry['player_id'] for entry in board['players']] == [
            entry['player_id'] for entry in settled['result']['ratings']]
        assert board['players'][0]['wins'] == 1 and board['players'][1]['losses'] == 1
        assert 'token' not in json.dumps(board).lower()
        assert get(f'/ratings?game={RATED}&limit=1')['players'] and len(get(f'/ratings?game={RATED}&limit=1')['players']) == 1
        fails('/ratings?game=nope', 404)
        fails(f'/ratings?game={RATED}&limit=0', 400)
        fails(f'/ratings?game={RATED}&limit=101', 400)
        fails(f'/ratings?game={RATED}&limit=many', 400)

        profile = get(f'/players/{welcome["player_id"]}?game={RATED}')
        assert profile == {'player_id': welcome['player_id'], 'name': 'Robin', 'rating': profile['rating'],
                           'games': 1, 'wins': 1, 'losses': 0}
        assert profile['rating'] > 1500.0
        fails(f'/players/nobody?game={RATED}', 404)
        fails(f'/players/{welcome["player_id"]}?game=nope', 404)

        with urlopen(http + '/healthz', timeout=5) as health:
            assert health.status == 200 and health.read() == b'ok\n'


def pump(*clients, until):
    """Drive scene-facing clients until a condition holds, like the client suite does."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for client in clients:
            client.poll()
        if until():
            return
        time.sleep(.01)
    raise AssertionError([(client.ready, client.closed, client.error) for client in clients])


def test_the_client_carries_identity_rating_and_result(server_url):
    """The scene-facing client exposes its durable identity, its live rating and the
    rated receipt, and keeps its account token across the automatic reconnect."""
    from saga2d.online import OnlineClient
    creator = OnlineClient(RATED, endpoint=server_url, player_name='Robin', rated=True)
    guest = None
    try:
        pump(creator, until=lambda: bool(creator.room))
        assert creator.player_id and creator.player_token and creator.rating['games'] == 0
        assert creator.rated is True and creator.match_id and creator.result is None
        token = creator.player_token
        guest = OnlineClient(RATED, endpoint=server_url, room=creator.room, player_name='Wren')
        pump(creator, guest, until=lambda: creator.ready and guest.ready)
        assert guest.player_id != creator.player_id
        assert {entry['seat'] for entry in creator.players if entry is not None} == {0, 1}
        creator.submit({'action': 'finish'}, revision=creator.revision)
        pump(creator, guest, until=lambda: creator.result is not None and guest.result is not None)
        assert creator.result['winner'] == 0 and creator.result == guest.result
        assert creator.rating['wins'] == 1 and guest.rating['losses'] == 1
        assert creator.player_token == token, 'reconnects retain the account token'
    finally:
        creator.close()
        if guest is not None:
            guest.close()


def test_ranked_and_optioned_clients_fail_clearly_against_an_old_server_while_casual_works():
    """A rated create or an optioned join against a welcome without capabilities is a
    clear rejection before ready, never a silent casual fallback; plain casual works."""
    import threading
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.server import serve
    from saga2d.online import OnlineClient

    def old_room(websocket):
        websocket.recv()
        websocket.send(json.dumps({'type': 'welcome', 'room': 'abc', 'resume_token': 't',
                                   'player': 0, 'retention': 900}))
        websocket.send(json.dumps({'type': 'state', 'player': 0, 'revision': 1, 'ready': False,
                                   'state': {}}))
        try:
            websocket.recv()  # until the client hangs up
        except ConnectionClosed:
            pass

    with serve(old_room, '127.0.0.1', 0) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.socket.getsockname()[1]
        endpoint = f'ws://127.0.0.1:{port}'
        ranked = OnlineClient(RATED, endpoint=endpoint, rated=True)
        try:
            pump(ranked, until=lambda: ranked.closed)
            assert not ranked.ready and 'ranked' in ranked.error.lower()
        finally:
            ranked.close()
        optioned = OnlineClient(RATED, endpoint=endpoint, player_options={'race': 'orc'})
        try:
            pump(optioned, until=lambda: optioned.closed)
            assert not optioned.ready and 'per-player options' in optioned.error.lower()
        finally:
            optioned.close()
        casual = OnlineClient(RATED, endpoint=endpoint)
        try:
            pump(casual, until=lambda: casual.state is not None)
            assert casual.room == 'abc' and casual.rating is None
            assert casual.player_id == '' and casual.result is None
        finally:
            casual.close()
        server.shutdown()


def test_the_client_accepts_a_rated_receipt_and_reports_the_configured_grace():
    """A legitimate final receipt (records carry before/after/delta, no rating field)
    reaches the client's result and refreshes its rating; the welcome's grace lands
    on the client instead of a hard-coded guess."""
    import threading
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.server import serve
    from saga2d.online import OnlineClient

    receipt = {'match_id': 'm1', 'winner': 0, 'ratings': [
        {'player_id': 'p0', 'name': 'Robin', 'before': 1500.0, 'after': 1516.0, 'delta': 16.0,
         'games': 1, 'wins': 1, 'losses': 0},
        {'player_id': 'p1', 'name': 'Wren', 'before': 1500.0, 'after': 1484.0, 'delta': -16.0,
         'games': 1, 'wins': 0, 'losses': 1}]}
    roster = [
        {'player_id': 'p0', 'name': 'Robin', 'rating': 1516.0, 'games': 1, 'wins': 1, 'losses': 0,
         'seat': 0, 'connected': True},
        {'player_id': 'p1', 'name': 'Wren', 'rating': 1484.0, 'games': 1, 'wins': 0, 'losses': 1,
         'seat': 1, 'connected': True}]

    def rated_room(websocket):
        websocket.recv()
        websocket.send(json.dumps({'type': 'welcome', 'room': 'abc', 'resume_token': 't', 'player': 0,
                                   'retention': 900, 'rated_grace': 45, 'seats': 2,
                                   'player_id': 'p0', 'player_token': 'secret', 'rated': True,
                                   'match_id': 'm1', 'capabilities': {'ratings': True, 'player_options': True},
                                   'rating': {'player_id': 'p0', 'name': 'Robin', 'rating': 1500.0,
                                              'games': 0, 'wins': 0, 'losses': 0}}))
        websocket.send(json.dumps({'type': 'state', 'player': 0, 'revision': 2, 'ready': True,
                                   'state': {}, 'players': roster, 'rated': True, 'match_id': 'm1',
                                   'result': receipt}))
        try:
            websocket.recv()  # until the client hangs up
        except ConnectionClosed:
            pass

    with serve(rated_room, '127.0.0.1', 0) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.socket.getsockname()[1]
        client = OnlineClient(RATED, endpoint=f'ws://127.0.0.1:{port}', rated=True)
        try:
            pump(client, until=lambda: client.result is not None)
            assert client.result == receipt
            assert client.rating == {'player_id': 'p0', 'name': 'Robin', 'rating': 1516.0,
                                     'games': 1, 'wins': 1, 'losses': 0}
            assert client.rated_grace == 45 and client.rated is True and client.match_id == 'm1'
        finally:
            client.close()
        server.shutdown()
