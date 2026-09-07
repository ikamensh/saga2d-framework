"""Frame-friendly clients for an authoritative room server over TLS WebSockets.

DNS, TLS, and socket work run on one sleeping worker; only ``poll`` changes the
state seen by scenes. Reconnection reclaims a private seat and resynchronizes
state. Orders are never replayed after a broken connection.
"""
from __future__ import annotations

import asyncio
from collections import deque
import json
import os
import queue
import threading
import time
from urllib.parse import urlsplit

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from saga2d.network import CommandError

PROTOCOL = 1
MAX_STATE = 8 * 1024 * 1024
MAX_COMMAND = 16 * 1024
DEFAULT_SERVER_URL = 'wss://games.tachyon-ai.eu/play'


def server_endpoint():
    return os.environ.get('SAGA2D_SERVER_URL', DEFAULT_SERVER_URL)


def _endpoint(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ('ws', 'wss') or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment):
        raise ValueError('Use a wss:// server address.')
    if parsed.scheme == 'ws' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Online connections require TLS (wss://).')
    if parsed.port == 0:
        raise ValueError('The server port must be between 1 and 65535.')
    return value


class OnlineClient:
    """Create, join, or resume a room; both players use the same client interface.

    ``ready`` requires both partners, while ``room`` arrives as soon as creation
    succeeds. ``resume_token`` is private: share only the room code. ``close``
    leaves the seat reserved on the server for its reconnect grace period.
    """
    online = True

    def __init__(self, game_id, *, endpoint=None, room=None, options=None, resume_token=None):
        self.game_id = game_id
        self.endpoint = _endpoint(endpoint or server_endpoint())
        self.room = room.strip().lower() if room else ''
        self.resume_token = resume_token or ''
        if self.resume_token and not self.room:
            raise ValueError('A room code is required to resume a seat.')
        self.player = 0 if not room else 1
        self.ready = False
        self.closed = False
        self.error = ''
        self.state = None
        self.revision = 0
        self._hello = {'protocol': PROTOCOL, 'game': game_id,
                       'type': 'resume' if resume_token else 'join' if room else 'create'}
        if room:
            self._hello['room'] = self.room
        if resume_token:
            self._hello['resume_token'] = resume_token
        if not room:
            self._hello['options'] = options or {}
        # Validate synchronously before launching the worker.
        json.dumps(self._hello, allow_nan=False)
        self._outgoing = queue.Queue(maxsize=64)
        self._incoming = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._accept_orders = threading.Event()
        self._loop = None
        self._task = None
        self._thread = threading.Thread(target=self._run, name='saga2d-online', daemon=True)
        self._thread.start()

    def _emit(self, message):
        with self._lock:
            if self._incoming and message['type'] == self._incoming[-1]['type'] == 'state':
                self._incoming[-1] = message
            elif len(self._incoming) >= 64:
                raise ConnectionError('The game cannot keep up with server messages.')
            else:
                self._incoming.append(message)

    def _discard_orders(self):
        while True:
            try:
                self._outgoing.get_nowait()
            except queue.Empty:
                return

    def _pause_orders(self):
        with self._lock:
            self._accept_orders.clear()
            self._discard_orders()

    async def _session(self, hello):
        self._pause_orders()
        async with connect(self.endpoint, open_timeout=10, close_timeout=1,
                           ping_interval=5, ping_timeout=10, max_size=MAX_STATE,
                           max_queue=4, compression=None, proxy=None) as connection:
            await connection.send(json.dumps(hello, allow_nan=False))
            receive = asyncio.create_task(connection.recv())
            try:
                while not self._stop.is_set():
                    done, _ = await asyncio.wait([receive], timeout=.02)
                    if done:
                        message = json.loads(receive.result())
                        if not isinstance(message, dict):
                            raise ValueError('Invalid server message.')
                        kind = message.get('type')
                        if kind == 'welcome':
                            if (not isinstance(message.get('room'), str)
                                    or not isinstance(message.get('resume_token'), str)
                                    or type(message.get('player')) is not int
                                    or message['player'] not in (0, 1)):
                                raise ValueError('Invalid seat assignment from server.')
                            hello = {'type': 'resume', 'protocol': PROTOCOL,
                                     'game': self._hello['game'], 'room': message['room'],
                                     'resume_token': message['resume_token']}
                            self._resume = hello
                            self._retry_deadline = None
                        elif kind == 'state':
                            if (not isinstance(message.get('state'), dict)
                                    or type(message.get('revision')) is not int
                                    or type(message.get('ready')) is not bool):
                                raise ValueError('Invalid match state from server.')
                            if message['ready']:
                                self._accept_orders.set()
                            else:
                                self._pause_orders()
                        elif kind in ('error', 'reject'):
                            if not isinstance(message.get('error'), str):
                                raise ValueError('Invalid server error.')
                        else:
                            raise ValueError('Unexpected server message.')
                        self._emit(message)
                        if kind == 'reject':
                            return
                        receive = asyncio.create_task(connection.recv())
                    for _ in range(64):
                        try:
                            order = self._outgoing.get_nowait()
                        except queue.Empty:
                            break
                        await connection.send(order)
            finally:
                receive.cancel()
                await asyncio.gather(receive, return_exceptions=True)

    async def _work(self):
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        self._resume = None
        self._retry_deadline = None
        while not self._stop.is_set():
            try:
                await self._session(self._resume or self._hello)
                return
            except (OSError, WebSocketException, TimeoutError, ConnectionError) as exc:
                self._pause_orders()
                if not self._resume:
                    self._emit({'type': 'reject', 'error': f'Cannot reach the online server: {exc}'})
                    return
                if self._retry_deadline is None:
                    self._retry_deadline = time.monotonic() + 60
                if time.monotonic() >= self._retry_deadline:
                    self._emit({'type': 'reject', 'error': 'Connection lost. Rejoin your saved room from Multiplayer.'})
                    return
                self._emit({'type': 'disconnected', 'error': 'Connection lost — reconnecting to your room…'})
                await asyncio.sleep(1)
            except (ValueError, UnicodeError, RecursionError) as exc:
                self._emit({'type': 'reject', 'error': f'Invalid response from the online server: {exc}'})
                return

    def _run(self):
        try:
            asyncio.run(self._work())
        except asyncio.CancelledError:
            pass  # Explicit close cancels pending DNS, TLS, receive, or retry.
        except Exception as exc:
            # Implementation errors must reach the main thread, not disappear.
            with self._lock:
                self._incoming.append({'type': 'exception', 'exception': exc})

    def poll(self):
        if self.closed:
            return
        with self._lock:
            messages = list(self._incoming)
            self._incoming.clear()
        for message in messages:
            kind = message['type']
            if kind == 'exception':
                self.close()
                raise RuntimeError('Online connection worker failed.') from message['exception']
            if kind == 'welcome':
                self.room, self.resume_token = message['room'], message['resume_token']
                self.player = message['player']
                self.error = ''
            elif kind == 'state':
                self.state, self.revision = message['state'], message['revision']
                self.ready = message['ready']
            elif kind in ('error', 'reject', 'disconnected'):
                self.error = message['error']
                if kind == 'disconnected':
                    self.ready = False
                elif kind == 'reject':
                    self.close()
                    break

    def submit(self, command, *, revision=None):
        data = json.dumps({'type': 'command', 'command': command, 'revision': revision}, allow_nan=False)
        if len(data.encode()) > MAX_COMMAND:
            raise CommandError('That order exceeds the online message limit.')
        with self._lock:
            if not self.ready or self.closed or not self._accept_orders.is_set():
                raise CommandError(self.error or 'Waiting for your partner to connect.')
            try:
                self._outgoing.put_nowait(data)
            except queue.Full as exc:
                raise CommandError('Too many pending orders. Please wait.') from exc

    def close(self):
        if self.closed:
            return
        self.closed, self.ready = True, False
        self._stop.set()
        self._pause_orders()
        loop, task = self._loop, self._task
        if loop is not None and task is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                if not loop.is_closed():
                    raise
