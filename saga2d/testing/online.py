"""Test support for online play: a tiny hosted game and helpers that drive a real server process.

``GAMES`` registers flavours of a counter with ``saga2d.server`` (plain,
realtime and campaign with two seats, and one of two to four seats whose players
can drop out), enough to exercise every server policy without a reference game.  ``running_server`` starts the production entry point on an
OS-assigned loopback port; ``handshake``/``receive``/``command`` speak the
protocol over a ``websockets`` sync connection.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

from saga2d.network import CommandError
from saga2d.server.games import GameSpec, option_int, option_keys, option_seed


class Counter:
    """A valid order adds one to the sender's count; realtime rooms also count server ticks.  In the seated
    flavour a player may also ``drop``: out of the count, no longer needed in the room."""

    def __init__(self, seed=0, start=0, seats=2):
        self.seed = seed
        self.counts = [start] * seats
        self.out = [False] * seats
        self.ticks = 0

    def apply(self, player, command):
        if command == {'action': 'drop'} and len(self.counts) > 2:
            self.out[player] = True
            return
        if command != {'action': 'add'} or self.out[player]:
            raise CommandError('Choose add.')
        self.counts[player] += 1

    def snapshot(self, player):
        return {'seed': self.seed, 'counts': list(self.counts), 'ticks': self.ticks}

    def step(self):
        self.ticks += 1


def _create(options):
    option_keys(options, {'seed', 'start'})
    return Counter(option_seed(options, 0), option_int(options, 'start', 0, 0, 1000))


def _create_seated(options):
    option_keys(options, {'seed', 'seats'})
    return Counter(option_seed(options, 0), seats=option_int(options, 'seats', 3, 2, 4))


class RatedCounter:
    """A counter with an authoritative finish, for ratings tests: ``add`` scores,
    ``finish`` crowns the highest count (ties go to the lowest seat), ``resign``
    concedes the seat and crowns the last seat standing. Orders after the
    decision are refused. Each seat also carries a configurable race."""

    RACES = ('human', 'orc')

    def __init__(self, seed=0, seats=2):
        self.seed = seed
        self.counts = [0] * seats
        self.resigned = [False] * seats
        self.winner = None
        self.races = ['human'] * seats

    def _crown(self):
        candidates = [seat for seat, out in enumerate(self.resigned) if not out]
        if len(candidates) == 1:
            self.winner = candidates[0]
        elif candidates:
            best = max(self.counts[seat] for seat in candidates)
            self.winner = min(seat for seat in candidates if self.counts[seat] == best)

    def apply(self, player, command):
        if self.winner is not None:
            raise CommandError('The match is over.')
        if command == {'action': 'add'}:
            if self.resigned[player]:
                raise CommandError('You have resigned this match.')
            self.counts[player] += 1
        elif command == {'action': 'resign'}:
            self.resigned[player] = True
            self._crown()
        elif command == {'action': 'finish'}:
            self._crown()
        else:
            raise CommandError('Choose add, resign or finish.')

    def snapshot(self, player):
        return {'seed': self.seed, 'counts': list(self.counts), 'winner': self.winner,
                'races': list(self.races)}


def _create_rated(options):
    option_keys(options, {'seed', 'seats'})
    return RatedCounter(option_seed(options, 0), option_int(options, 'seats', 2, 2, 4))


def _checkpoint_rated(match):
    return {'seed': match.seed, 'counts': list(match.counts), 'resigned': list(match.resigned),
            'winner': match.winner, 'races': list(match.races)}


def _restore_rated(snapshot):
    match = RatedCounter(snapshot['seed'], len(snapshot['counts']))
    match.counts, match.resigned, match.winner, match.races = (
        list(snapshot['counts']), list(snapshot['resigned']), snapshot['winner'], list(snapshot['races']))
    return match


def _forfeit_rated(match, seat):
    """An absent rated seat resigns; the last seat standing takes the match."""
    if match.winner is None and not match.resigned[seat]:
        match.resigned[seat] = True
        match._crown()


def _configure_race(match, seat, options):
    """Accept a race selection for a seat; anything else is a malformed choice."""
    if not isinstance(options, dict):
        raise CommandError('Player options must be an object.')
    if set(options) - {'race'}:
        raise CommandError('Unknown player option.')
    race = options.get('race', 'human')
    if race not in RatedCounter.RACES:
        raise CommandError('Unknown race.')
    match.races[seat] = race


def _checkpoint(match):
    return {'seed': match.seed, 'counts': list(match.counts), 'out': list(match.out), 'ticks': match.ticks}


def _restore(snapshot):
    match = Counter(snapshot['seed'], seats=len(snapshot['counts']))
    match.counts, match.out, match.ticks = list(snapshot['counts']), list(snapshot['out']), snapshot['ticks']
    return match


def _observer_view(match):
    """What watchers see of a counter: totals only, never per-seat details."""
    return {'seed': match.seed, 'total': sum(match.counts), 'ticks': match.ticks, 'watching': True}


def _observer_view_rated(match):
    """What watchers see of a rated counter: the score without the seat options."""
    return {'seed': match.seed, 'counts': list(match.counts), 'winner': match.winner}


class GrowCounter(Counter):
    """A counter whose watcher view grows one mebibyte per ``grow`` order.

    Seat snapshots stay tiny no matter how much the watcher view bulks up, so
    an overgrown view can only ever end watching, never the match.
    """
    CHUNK = 1024 * 1024

    def __init__(self, seed=0, start=0, seats=2):
        super().__init__(seed, start, seats)
        self.grows = 0

    def apply(self, player, command):
        if command == {'action': 'grow'}:
            self.grows += 1
            return
        super().apply(player, command)


def _create_grow(options):
    option_keys(options, {'seed'})
    return GrowCounter(option_seed(options, 0))


def _checkpoint_grow(match):
    record = _checkpoint(match)
    record['grows'] = match.grows
    return record


def _restore_grow(snapshot):
    match = GrowCounter(snapshot['seed'], seats=len(snapshot['counts']))
    match.counts, match.out, match.ticks = list(snapshot['counts']), list(snapshot['out']), snapshot['ticks']
    match.grows = snapshot['grows']
    return match


def _observer_view_grow(match):
    return {'seed': match.seed, 'total': sum(match.counts), 'ticks': match.ticks,
            'watching': True, 'bulk': 'g' * (match.grows * GrowCounter.CHUNK)}


GAMES = {
    'counter-v1': GameSpec(_create, _checkpoint, _restore),
    'counter-realtime-v1': GameSpec(_create, _checkpoint, _restore, realtime=True),
    'counter-campaign-v1': GameSpec(_create, _checkpoint, _restore, campaign=True),
    'counter-campaign-observer-v1': GameSpec(_create, _checkpoint, _restore, campaign=True,
                                             observer_snapshot=_observer_view),
    'counter-seats-v1': GameSpec(_create_seated, _checkpoint, _restore, realtime=True,
                                 seats=lambda match: len(match.counts), needed=lambda match, player: not match.out[player]),
    'counter-rated-v1': GameSpec(_create_rated, _checkpoint_rated, _restore_rated,
                                 seats=lambda match: len(match.counts),
                                 result=lambda match: match.winner, rated=lambda match: True,
                                 forfeit=_forfeit_rated, configure_player=_configure_race,
                                 observer_snapshot=_observer_view_rated),
    'counter-observer-v1': GameSpec(_create, _checkpoint, _restore, observer_snapshot=_observer_view),
    'counter-grow-v1': GameSpec(_create_grow, _checkpoint_grow, _restore_grow,
                                observer_snapshot=_observer_view_grow),
}
COUNTER_GAMES = 'saga2d.testing.online:GAMES'


def first_stdout_line(process, timeout=15):
    """Wait for subprocess readiness on every platform; kill a timed-out child."""
    lines = queue.Queue(maxsize=1)
    reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        return lines.get(timeout=timeout)
    except queue.Empty:
        process.kill()
        raise AssertionError('subprocess startup timed out') from None
    finally:
        reader.join(timeout=5)


@contextmanager
def running_server(*games, arguments=(), cwd=None):
    """Run ``python -m saga2d.server`` hosting ``games`` (``module:ATTRIBUTE`` names) on a free port."""
    process = subprocess.Popen(
        [sys.executable, '-m', 'saga2d.server', '--port', '0', '--games', *games, *map(str, arguments)],
        cwd=cwd or Path.cwd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, 'PYTHONUNBUFFERED': '1'},
    )
    try:
        endpoint = first_stdout_line(process).strip()
        assert endpoint.startswith('LISTENING ws://'), endpoint
        yield endpoint.removeprefix('LISTENING '), process
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            _, errors = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            _, errors = process.communicate(timeout=5)
        assert 'Traceback (most recent call last)' not in errors, errors


def server_fixture(*games, arguments=()):
    """A pytest fixture named by its assignment, yielding a fresh server's endpoint per test."""
    import pytest

    @pytest.fixture
    def server_url():
        with running_server(*games, arguments=arguments) as (url, process):
            yield url

    return server_url


def receive(socket, kind='state', predicate=lambda message: True):
    for _ in range(100):
        message = json.loads(socket.recv(timeout=5))
        if message['type'] == kind and predicate(message):
            return message
        if message['type'] in ('error', 'reject'):
            raise AssertionError(message)
    raise AssertionError('expected message never arrived')


def handshake(socket, kind='create', *, game, **fields):
    socket.send(json.dumps({'type': kind, 'protocol': 1, 'game': game, **fields}))
    return receive(socket, 'welcome')


def command(socket, data, revision=None):
    socket.send(json.dumps({'type': 'command', 'command': data, 'revision': revision}))
