"""Test support for online play: a tiny hosted game and helpers that drive a real server process.

``GAMES`` registers three flavours of a two-seat counter with ``saga2d.server``
(plain, realtime and campaign), enough to exercise every server policy without
a reference game.  ``running_server`` starts the production entry point on an
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
    """A valid order adds one to the sender's count; realtime rooms also count server ticks."""

    def __init__(self, seed=0, start=0):
        self.seed = seed
        self.counts = [start, start]
        self.ticks = 0

    def apply(self, player, command):
        if command != {'action': 'add'}:
            raise CommandError('Choose add.')
        self.counts[player] += 1

    def snapshot(self, player):
        return {'seed': self.seed, 'counts': list(self.counts), 'ticks': self.ticks}

    def step(self):
        self.ticks += 1


def _create(options):
    option_keys(options, {'seed', 'start'})
    return Counter(option_seed(options, 0), option_int(options, 'start', 0, 0, 1000))


def _checkpoint(match):
    return {'seed': match.seed, 'counts': list(match.counts), 'ticks': match.ticks}


def _restore(snapshot):
    match = Counter(snapshot['seed'])
    match.counts, match.ticks = list(snapshot['counts']), snapshot['ticks']
    return match


GAMES = {
    'counter-v1': GameSpec(_create, _checkpoint, _restore),
    'counter-realtime-v1': GameSpec(_create, _checkpoint, _restore, realtime=True),
    'counter-campaign-v1': GameSpec(_create, _checkpoint, _restore, campaign=True),
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
