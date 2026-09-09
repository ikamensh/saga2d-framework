"""The room server's policies, exercised with the counter test game instead of a reference game."""
import json
import os
import time

import pytest
from websockets.sync.client import connect

from saga2d import CommandError
from saga2d.server.games import GameSpec, load_games, option_choice, option_int, option_keys
from saga2d.testing.online import COUNTER_GAMES, GAMES, command, handshake, receive, running_server, server_fixture

GAME = 'counter-v1'
server_url = server_fixture(COUNTER_GAMES)


def test_registries_are_named_modules_and_reject_duplicates_or_foreign_values():
    assert load_games([COUNTER_GAMES]) == GAMES
    with pytest.raises(ValueError, match='twice'):
        load_games([COUNTER_GAMES, COUNTER_GAMES])
    with pytest.raises(ValueError, match='module:ATTRIBUTE'):
        load_games(['saga2d.testing.online'])
    with pytest.raises(TypeError, match='GameSpec'):
        load_games(['saga2d.testing.online:COUNTER_GAMES'])


def test_option_helpers_bound_untrusted_input():
    assert option_keys({'seed': 1}, {'seed'}) == {'seed': 1}
    for options, fragment in [([], 'object'), ({'extra': 1}, 'option')]:
        with pytest.raises(CommandError, match=fragment):
            option_keys(options, {'seed'})
    assert option_int({}, 'size', 14, 11, 18) == 14
    for value in (True, 19, 'x', 3.0):
        with pytest.raises(CommandError, match='size'):
            option_int({'size': value}, 'size', 14, 11, 18)
    assert option_choice({}, 'theme', 'summer', {'summer', 'winter'}) == 'summer'
    with pytest.raises(CommandError, match='theme'):
        option_choice({'theme': 'spring'}, 'theme', 'summer', {'summer', 'winter'})


def test_room_publishes_authoritative_state_to_both_seats(server_url):
    """A guest joins by room code, both seats see the same state, and orders are attributed."""
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        welcome = handshake(host, game=GAME, options={'seed': 7, 'start': 2})
        waiting = receive(host)
        assert waiting['player'] == 0 and not waiting['ready']
        assert waiting['state'] == {'seed': 7, 'counts': [2, 2], 'ticks': 0}
        joined = handshake(guest, 'join', game=GAME, room=welcome['room'])
        assert joined['player'] == 1 and joined['resume_token'] != welcome['resume_token']
        ready = receive(host, predicate=lambda message: message['ready'])
        assert receive(guest)['state'] == ready['state']
        command(guest, {'action': 'subtract'})
        assert 'add' in receive(guest, 'error')['error']
        command(guest, {'action': 'add'}, ready['revision'])
        changed = receive(host)
        assert changed['state']['counts'] == [2, 3]
        assert changed['revision'] > ready['revision']
        assert receive(guest)['state'] == changed['state']


@pytest.mark.parametrize('fields, fragment', [
    ({'protocol': 2}, 'protocol'),
    ({'game': 'counter-v999'}, 'version'),
    ({'options': []}, 'options'),
    ({'options': {'start': 100000}}, 'start'),
    ({'options': {'start': True}}, 'start'),
    ({'options': {'seed': {'surprise': 'object'}}}, 'seed'),
    ({'options': {'undeclared': 'field'}}, 'option'),
])
def test_invalid_handshakes_are_rejected_without_breaking_other_rooms(server_url, fields, fragment):
    """Untrusted options cannot allocate oversized worlds or take down the room server."""
    with connect(server_url, proxy=None) as bad:
        bad.send(json.dumps({'type': 'create', 'protocol': 1, 'game': GAME, **fields}))
        assert fragment in receive(bad, 'reject')['error'].lower()
    with connect(server_url, proxy=None) as good:
        handshake(good, game=GAME)
        assert receive(good)['state']['counts'] == [0, 0]


def test_private_seats_resume_without_room_code_takeover(server_url):
    """A shared invitation never grants a claimed seat; its private token can replace a stale socket."""
    from websockets.exceptions import ConnectionClosed
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        host_seat = handshake(host, game=GAME)
        receive(host)
        guest_seat = handshake(guest, 'join', game=GAME, room=host_seat['room'])
        receive(host)
        ready = receive(guest)
        with connect(server_url, proxy=None) as intruder:
            intruder.send(json.dumps({'type': 'join', 'protocol': 1, 'game': GAME, 'room': host_seat['room']}))
            assert 'claimed' in receive(intruder, 'reject')['error']
        with connect(server_url, proxy=None) as returned:
            resumed = handshake(returned, 'resume', game=GAME, room=host_seat['room'],
                                resume_token=guest_seat['resume_token'])
            assert resumed['player'] == 1
            state = receive(returned)
            assert state['ready'] and state['state'] == ready['state']
            assert 'reconnected' in receive(guest, 'reject')['error']
            with pytest.raises(ConnectionClosed):
                guest.recv(timeout=5)
        paused = receive(host, predicate=lambda message: not message['ready'])
        command(host, {'action': 'add'})
        assert 'Waiting' in receive(host, 'error')['error']
        with connect(server_url, proxy=None) as returned:
            handshake(returned, 'resume', game=GAME, room=host_seat['room'], resume_token=guest_seat['resume_token'])
            assert receive(returned)['state'] == paused['state']


def test_rooms_are_isolated_and_stale_orders_do_not_mutate_state(server_url):
    """Knowledge of another room code or an obsolete revision cannot redirect an order."""
    with (connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest,
          connect(server_url, proxy=None) as other):
        room = handshake(host, game=GAME)
        initial = receive(host)
        handshake(other, game=GAME, options={'seed': 99})
        untouched = receive(other)
        handshake(guest, 'join', game=GAME, room=room['room'])
        receive(host)
        receive(guest)
        command(host, {'action': 'add'}, initial['revision'])
        assert 'changed' in receive(host, 'error')['error']
        command(host, {'action': 'add'})
        assert receive(guest)['state']['counts'] == [1, 0]
        command(other, {'action': 'add'})
        assert 'Waiting' in receive(other, 'error')['error']
        assert untouched['state']['counts'] == [0, 0]


def test_realtime_matches_run_on_the_server_clock_and_pause_for_a_disconnected_player(server_url):
    """A realtime game advances without a host scene and stops while a seat is away."""
    game = 'counter-realtime-v1'
    with connect(server_url, proxy=None) as host, connect(server_url, proxy=None) as guest:
        room = handshake(host, game=game)
        assert receive(host)['state']['ticks'] == 0
        guest_seat = handshake(guest, 'join', game=game, room=room['room'])
        receive(host)
        moved = receive(guest, predicate=lambda message: message['state']['ticks'] >= 6)
        assert moved['ready']
        guest.close()
        paused = receive(host, predicate=lambda message: not message['ready'])
        with pytest.raises(TimeoutError):
            host.recv(timeout=.15)
        with connect(server_url, proxy=None) as returned:
            handshake(returned, 'resume', game=game, room=room['room'], resume_token=guest_seat['resume_token'])
            resumed = receive(returned, predicate=lambda message: message['state']['ticks'] > paused['state']['ticks'])
            assert resumed['ready']


@pytest.mark.parametrize('message', ['[]', '{', '{"value":1e999}', '{"value":NaN}'])
def test_malformed_json_is_a_connection_rejection(server_url, message):
    """Invalid JSON cannot escape into rules or crash the room event loop."""
    with connect(server_url, proxy=None) as bad:
        bad.send(message)
        assert receive(bad, 'reject')['error']
    with connect(server_url, proxy=None) as good:
        handshake(good, game=GAME)
        assert receive(good)['state']


@pytest.mark.parametrize('game', ['counter-v1', 'counter-realtime-v1'])
def test_rooms_and_private_seats_survive_server_restart(tmp_path, game):
    """Trusted checkpoints restore private seats and the match after process loss."""
    with running_server(COUNTER_GAMES, arguments=('--state-dir', tmp_path)) as (url, process):
        with connect(url, proxy=None) as host, connect(url, proxy=None) as guest:
            seat0 = handshake(host, game=game)
            receive(host)
            seat1 = handshake(guest, 'join', game=game, room=seat0['room'])
            receive(host)
            before = receive(guest)
            if game == 'counter-v1':
                command(host, {'action': 'add'})
                before = receive(guest)
                # Acknowledged orders survive even an abrupt power/process loss.
                process.kill()
                process.wait(timeout=5)
            else:
                before = receive(guest, predicate=lambda state: state['state']['ticks'] >= 4)
    if os.name != 'nt':  # Windows has no POSIX mode bits to check.
        assert (tmp_path / 'rooms.sqlite3').stat().st_mode & 0o777 == 0o600
    with running_server(COUNTER_GAMES, arguments=('--state-dir', tmp_path)) as (url, process):
        with connect(url, proxy=None) as host, connect(url, proxy=None) as guest:
            returned = handshake(host, 'resume', game=game, room=seat0['room'], resume_token=seat0['resume_token'])
            assert returned['player'] == 0
            assert not receive(host)['ready']
            handshake(guest, 'resume', game=game, room=seat0['room'], resume_token=seat1['resume_token'])
            resumed = receive(guest)
            assert resumed['ready']
            if game == 'counter-v1':
                assert resumed['state'] == before['state']
                assert resumed['revision'] > before['revision']
            else:
                assert resumed['state']['ticks'] >= before['state']['ticks'] >= 4


def test_expired_rooms_do_not_return_after_server_restart(tmp_path):
    """Wall time, rather than process uptime, bounds how long a disconnected seat stays resumable."""
    arguments = ('--state-dir', tmp_path, '--room-ttl', '.15')
    with running_server(COUNTER_GAMES, arguments=arguments) as (url, process):
        with connect(url, proxy=None) as host:
            seat = handshake(host, game=GAME)
            receive(host)
    time.sleep(.2)
    with running_server(COUNTER_GAMES, arguments=arguments) as (url, process):
        with connect(url, proxy=None) as returned:
            returned.send(json.dumps({'type': 'resume', 'protocol': 1, 'game': GAME,
                                      'room': seat['room'], 'resume_token': seat['resume_token']}))
            assert 'not found' in receive(returned, 'reject')['error']


def test_room_capacity_is_explicit_and_health_remains_available():
    """A full server rejects new rooms while its health endpoint and existing rooms stay usable."""
    from urllib.request import urlopen
    with running_server(COUNTER_GAMES, arguments=('--max-rooms', '1')) as (url, process):
        with connect(url + '/play', proxy=None) as host:
            handshake(host, game=GAME)
            receive(host)
            with connect(url, proxy=None) as extra:
                extra.send(json.dumps({'type': 'create', 'protocol': 1, 'game': GAME}))
                assert 'full' in receive(extra, 'reject')['error']
            with urlopen(url.replace('ws://', 'http://') + '/healthz', timeout=3) as health:
                assert health.status == 200 and health.read() == b'ok\n'


@pytest.mark.parametrize('trusted', [False, True])
def test_only_configured_loopback_proxy_can_supply_client_ip(trusted):
    """An internet client cannot bypass room quotas by forging a forwarding header."""
    arguments = ('--trusted-proxy',) if trusted else ()
    with running_server(COUNTER_GAMES, arguments=arguments) as (url, process):
        for index in range(5):
            with connect(url, proxy=None, additional_headers={'X-Forwarded-For': f'192.0.2.{index + 1}'}) as host:
                host.send(json.dumps({'type': 'create', 'protocol': 1, 'game': GAME}))
                if index == 4 and not trusted:
                    assert 'Too many' in receive(host, 'reject')['error']
                else:
                    receive(host, 'welcome')
                    assert receive(host)['state']


def test_incompatible_clients_learn_to_update_rather_than_retry():
    """Version mismatches carry a machine-readable reason so games can offer the download page."""
    with running_server(COUNTER_GAMES) as (url, process):
        for fields in ({'protocol': 2}, {'game': 'counter-v999'}):
            with connect(url, proxy=None) as old:
                old.send(json.dumps({'type': 'create', 'protocol': 1, 'game': GAME, **fields}))
                rejection = receive(old, 'reject')
                assert rejection['reason'] == 'incompatible' and 'Update' in rejection['error']
        with connect(url, proxy=None) as stranger:
            stranger.send(json.dumps({'type': 'join', 'protocol': 1, 'game': GAME, 'room': 'nowhere'}))
            assert 'reason' not in receive(stranger, 'reject')


def test_campaigns_wait_for_a_late_partner_and_report_their_retention():
    """A lone campaign seat is not expired like a match room; both games learn their retention."""
    with running_server(COUNTER_GAMES, arguments=('--room-ttl', '.15', '--campaign-ttl', '5')) as (url, process):
        with connect(url, proxy=None) as host, connect(url, proxy=None) as match_host:
            campaign = handshake(host, game='counter-campaign-v1')
            assert campaign['retention'] == 5
            receive(host)
            assert handshake(match_host, game=GAME)['retention'] == .15
            receive(match_host)
            time.sleep(.3)
            assert 'expired' in receive(match_host, 'reject')['error']
            with connect(url, proxy=None) as guest:
                handshake(guest, 'join', game='counter-campaign-v1', room=campaign['room'])
                assert receive(host, predicate=lambda message: message['ready'])['ready']


def test_suspended_campaigns_leave_memory_and_resume_days_later_even_after_restart(tmp_path):
    """Storage, not the room limit, holds an absent campaign; it returns for either seat."""
    campaign = 'counter-campaign-v1'
    arguments = ('--state-dir', tmp_path, '--room-ttl', '.15', '--campaign-ttl', '1.5', '--max-rooms', '1')
    with running_server(COUNTER_GAMES, arguments=arguments) as (url, process):
        with connect(url, proxy=None) as host:
            seat = handshake(host, game=campaign, options={'seed': 11})
            before = receive(host)['state']
        time.sleep(.3)  # Both seats absent beyond the match TTL: the campaign is suspended.
        with connect(url, proxy=None) as other:
            handshake(other, game=GAME)  # The single room slot is free again.
            receive(other)
    time.sleep(.3)  # The abandoned match expires in storage; the campaign is retained.
    with running_server(COUNTER_GAMES, arguments=arguments) as (url, process):
        with connect(url, proxy=None) as other:
            handshake(other, game=GAME)  # Suspended campaigns stay unloaded.
            receive(other)
        time.sleep(.3)  # The abandoned match expires, freeing the slot for the campaign.
        with connect(url, proxy=None) as returned, connect(url, proxy=None) as guest:
            resumed = handshake(returned, 'resume', game=campaign, room=seat['room'], resume_token=seat['resume_token'])
            assert resumed['player'] == 0 and resumed['retention'] == 1.5
            assert receive(returned)['state'] == before
            handshake(guest, 'join', game=campaign, room=seat['room'])
            assert receive(guest)['ready']
        time.sleep(1.7)  # Longer than the campaign retention since the last visit.
        with connect(url, proxy=None) as late:
            late.send(json.dumps({'type': 'resume', 'protocol': 1, 'game': campaign,
                                  'room': seat['room'], 'resume_token': seat['resume_token']}))
            assert 'not found' in receive(late, 'reject')['error']
