"""Authoritative online rooms for any registered game.

The public interface is the versioned WebSocket protocol, served by ``run``
with a ``{game id: GameSpec}`` registry (see ``saga2d.server.games``).
Game rules and room membership run serially on one event loop. Per-player
writers coalesce snapshots so a slow connection never delays another player.
"""
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import hmac
from http import HTTPStatus
import json
import ipaddress
import logging
import math
import secrets
import string
import time
from urllib.parse import parse_qs, unquote
import uuid

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from saga2d.network import CommandError
from saga2d.server.games import GameSpec, load_games, option_choice, option_int, option_keys, option_seed
from saga2d.server.storage import RoomStore

__all__ = ['ELO_K', 'GameSpec', 'IncompatibleClient', 'MAX_MESSAGE', 'MAX_OBSERVERS', 'PROTOCOL', 'Peer',
           'RATED_SEATS', 'Room', 'RoomServer', 'STARTING_RATING', 'decode', 'load_games', 'option_choice',
           'option_int', 'option_keys', 'option_seed', 'player_name', 'run', 'settle_ratings']

PROTOCOL = 1
MAX_MESSAGE = 16_384
#: How many watchers one room admits; seats never compete for these slots.
MAX_OBSERVERS = 8
MAX_SNAPSHOT = 8 * 1024 * 1024
LOG = logging.getLogger(__name__)

STARTING_RATING = 1500.0
ELO_K = 32.0
RATED_SEATS = [2, 3, 4]
DEFAULT_PLAYER_NAME = 'Commander'
MAX_NAME_LENGTH = 32


def _token_hash(token):
    """A private account token never rests as itself, only as its hash."""
    return 'sha256$' + hashlib.sha256(token.encode()).hexdigest()


def _token_matches(token, stored):
    try:
        return hmac.compare_digest(_token_hash(token), stored)
    except (ValueError, TypeError):
        return False


def player_name(value):
    """Display data, never identity: trimmed, at most 32 characters, printable and nonempty.

    Control characters are refused anywhere in the supplied text: padded
    newlines do not sneak through trimming, and long names are an error rather
    than a silent truncation.
    """
    if value is None:
        return DEFAULT_PLAYER_NAME
    if not isinstance(value, str):
        raise CommandError('player_name must be text.')
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CommandError('player_name must not contain control characters.')
    name = value.strip()
    if not name:
        raise CommandError('player_name must not be empty.')
    if len(name) > MAX_NAME_LENGTH:
        raise CommandError('player_name must be at most 32 characters.')
    if not all(character.isprintable() for character in name):
        raise CommandError('player_name must be printable text.')
    return name


def settle_ratings(entries, winner):
    """Elo with K=32: the winner beats each loser, all losers tie each other.

    ``entries`` are the participants' current profiles, ``winner`` the winning
    seat index. Every pre-match rating is read before any update, so the
    exchanged points sum to zero. Returns the result's per-player records.
    """
    before = [float(entry['rating']) for entry in entries]
    count = len(entries)
    records = []
    for seat, entry in enumerate(entries):
        if seat == winner:
            delta = sum(ELO_K * (1 - 1 / (1 + 10 ** ((before[loser] - before[winner]) / 400))) / (count - 1)
                        for loser in range(count) if loser != winner)
        else:
            delta = -ELO_K * (1 - 1 / (1 + 10 ** ((before[seat] - before[winner]) / 400))) / (count - 1)
        records.append({'player_id': entry['player_id'], 'name': entry['name'],
                        'before': before[seat], 'after': before[seat] + delta, 'delta': delta,
                        'games': entry['games'] + 1,
                        'wins': entry['wins'] + (1 if seat == winner else 0),
                        'losses': entry['losses'] + (0 if seat == winner else 1)})
    return records


def decode(data):
    """Keep all game inputs within a small, finite JSON object tree."""
    def reject_constant(value):
        raise ValueError(f'Invalid JSON number: {value}')

    try:
        message = json.loads(data, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CommandError('Invalid JSON message.') from exc
    if not isinstance(message, dict):
        raise CommandError('Network messages must be objects.')
    pending, count = [(message, 0)], 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > 12 or count > 2048:
            raise CommandError('Network message is too complex.')
        if isinstance(value, dict):
            for key in value:
                _text(key)  # a key is text the server reads and logs like any other
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
        elif isinstance(value, float) and not math.isfinite(value):
            raise CommandError('Network numbers must be finite.')
        elif isinstance(value, str):
            _text(value)
    return message


def _text(value):
    """Text the server can read and hand back out again.

    A JSON escape may name a lone surrogate, which no encoder will take: ``resume_token`` carrying one made
    ``token.encode()`` raise where a refusal belonged, and the connection died on the catch-all with the wrong
    message and a traceback in the log for anyone who cared to send one.
    """
    if len(value) > 1024:
        raise CommandError('Network text is too long.')
    if not value.isascii():  # the common case costs one C scan; only the rest is encoded
        try:
            value.encode()
        except UnicodeEncodeError as exc:
            raise CommandError('Network text is not text this server can read.') from exc


class IncompatibleClient(CommandError):
    """The client's protocol or game version cannot join any room on this server."""


class Peer:
    """Bounded control messages and one replaceable snapshot per connection."""
    def __init__(self, websocket):
        self.websocket = websocket
        self.controls = deque()
        self.state = None
        self.wake = asyncio.Event()
        self.closing = False
        self.allowance = 40.
        self.last_message = time.monotonic()

    def send(self, message):
        if self.closing:
            return
        encoded = json.dumps(message, separators=(',', ':'), allow_nan=False)
        if len(encoded) > MAX_SNAPSHOT:
            raise RuntimeError('Game snapshot exceeds the network size limit.')
        if message['type'] == 'state':
            self.state = encoded
        elif len(self.controls) < 16:
            self.controls.append(encoded)
        else:
            self.reject('Connection cannot keep up with the match.')
        self.wake.set()

    def reject(self, error, reason=None):
        """End the connection; ``reason`` lets clients react beyond showing the text."""
        self.closing = True
        self.state = None
        self.controls.clear()
        message = {'type': 'reject', 'error': error}
        if reason is not None:
            message['reason'] = reason
        self.controls.append(json.dumps(message))
        self.wake.set()

    def check_rate(self):
        now = time.monotonic()
        self.allowance = min(40., self.allowance + (now - self.last_message) * 20)
        self.last_message = now
        if self.allowance < 1:
            raise CommandError('Too many commands. Reconnect and send orders more slowly.')
        self.allowance -= 1

    async def write(self):
        try:
            while True:
                await self.wake.wait()
                self.wake.clear()
                while self.controls or self.state is not None:
                    if self.controls:
                        data = self.controls.popleft()
                    else:
                        data, self.state = self.state, None
                    await asyncio.wait_for(self.websocket.send(data), timeout=3)
                if self.closing:
                    return
        except (ConnectionClosed, TimeoutError):
            pass
        finally:
            await self.websocket.close()


@dataclass
class Room:
    game: str
    match: object
    code: str
    tokens: list = field(default_factory=lambda: [secrets.token_urlsafe(32), None])  # one per seat
    needed: Callable = lambda match, player: True  # whether a seat must be connected for play to go on
    peers: list = field(default_factory=list)
    revision: int = 0
    disconnected_at: float = field(default_factory=time.monotonic)
    ticks: int = 0
    checkpointed_at: float = 0.
    unpublished: bool = False  # a realtime room took an order since its last state went out
    match_id: str = ''
    rated: bool = False
    identities: list = field(default_factory=list)  # per seat {'player_id', 'name'} or None
    result: dict | None = None
    seat_gone: list = field(default_factory=list)  # per-seat disconnect time, or None while connected
    started: bool = False  # every needed seat was connected at once; rated grace never runs before this
    forfeited: list = field(default_factory=list)  # per-seat whether the abandon hook already ran
    observers: list = field(default_factory=list)  # watcher peers; never seats, never persisted
    seat_states: dict = field(default_factory=dict)  # last published game payload per seat; metadata refresh only

    def __post_init__(self):
        self.peers = [None] * len(self.tokens)
        if not self.identities:
            self.identities = [None] * len(self.tokens)
        if not self.seat_gone:
            self.seat_gone = [None] * len(self.tokens)
        if not self.forfeited:
            self.forfeited = [False] * len(self.tokens)

    @property
    def present(self):
        return sum(peer is not None and not peer.closing for peer in self.peers)

    @property
    def observer_count(self):
        return sum(peer is not None and not peer.closing for peer in self.observers)

    @property
    def ready(self):
        """Every needed seat connected, and somebody in the room: a room of players who are all out still empties."""
        return self.present > 0 and all(peer is not None and not peer.closing
                                        for player, peer in enumerate(self.peers) if self.needed(self.match, player))

    def publish(self, roster=None):
        self.revision += 1
        self.unpublished = False
        ready, present = self.ready, self.present
        if ready:
            self.started = True
        players = roster if roster is not None else [None] * len(self.peers)
        for player, peer in enumerate(self.peers):
            if peer is not None:
                payload = self.match.snapshot(player)
                peer.send({'type': 'state', 'player': player, 'revision': self.revision, 'ready': ready,
                           'seats': len(self.peers), 'present': present, 'state': payload,
                           'players': players, 'rated': self.rated, 'match_id': self.match_id,
                           'result': self.result, 'observer_count': self.observer_count})
                self.seat_states[player] = payload

    def publish_observers(self, message):
        """Send one prebuilt watcher state without moving the revision.

        A watcher that cannot take it is refused alone; the seats never notice.
        """
        for peer in list(self.observers):
            if peer is not None and not peer.closing:
                try:
                    peer.send(message)
                except RuntimeError:
                    peer.reject('The observer view is too large.')
                    if peer in self.observers:
                        self.observers.remove(peer)


@dataclass(frozen=True)
class _StagedIdentity:
    """A validated hello waiting for its seat: committing it inserts the account and profile it earned."""
    player_id: str
    account_token: str
    name: str
    account_hash: str | None  # a fresh account inserts this on commit
    profile: dict | None  # the profile to insert or rename on commit; None changes nothing


class RoomServer:
    """Matches expire after ``room_ttl`` without every needed player; campaigns are retained
    for ``campaign_ttl`` and leave memory after ``room_ttl`` until a seat returns.

    Rated rooms rate one authoritative result per match and forfeit a needed seat
    left absent past ``rated_grace`` once the match began; the lobby never starts
    that clock. Without ``state_dir`` accounts and ratings live in memory only.
    """
    def __init__(self, games, *, max_rooms=64, max_connections=128, room_ttl=900, campaign_ttl=7 * 86400,
                 rated_grace=60, state_dir=None, trusted_proxy=False):
        if not games:
            raise ValueError('The server needs at least one registered game.')
        if max_rooms < 1 or max_connections < 2 or not math.isfinite(room_ttl) or room_ttl <= 0:
            raise ValueError('Room and connection limits must be positive.')
        if not math.isfinite(campaign_ttl) or campaign_ttl < room_ttl:
            raise ValueError('Campaign retention must be at least the match room retention.')
        if not math.isfinite(rated_grace) or rated_grace <= 0:
            raise ValueError('Rated grace must be positive.')
        self.games = dict(games)
        self.rooms = {}
        self.max_rooms, self.max_connections = max_rooms, max_connections
        self.room_ttl, self.campaign_ttl = room_ttl, campaign_ttl
        self.rated_grace = rated_grace
        self.connections = set()
        self.by_ip = {}
        self.creations = {}
        self.trusted_proxy = trusted_proxy
        self.accounts = {}
        self.profiles = {}
        self.matches = {}
        self.store = RoomStore(state_dir) if state_dir is not None else None
        self.last_keep_alive = time.monotonic()
        if self.store is not None:
            self.accounts.update(self.store.load_accounts())
            self.profiles.update(self.store.load_profiles())
            self.matches.update(self.store.load_matches())
            for saved in self.store.load():
                self.rooms[saved['code']] = self.restore(saved)

    def public_profile(self, game, player_id):
        """What anyone may see of an account: never its token."""
        profile = self.profiles.get((game, player_id))
        if profile is None:
            return None
        return {'player_id': player_id, 'name': profile['name'], 'rating': profile['rating'],
                'games': profile['games'], 'wins': profile['wins'], 'losses': profile['losses']}

    def roster(self, room):
        """Every claimed seat's public profile with its seat and connection, in seat order."""
        entries = []
        for seat, identity in enumerate(room.identities):
            if identity is None:
                entries.append(None)
                continue
            profile = self.public_profile(room.game, identity['player_id'])
            peer = room.peers[seat]
            entries.append({**profile, 'seat': seat,
                            'connected': peer is not None and not peer.closing})
        return entries

    def _live_observers(self, room):
        """Watchers still connected; closing ones leave without a sound."""
        room.observers = [peer for peer in room.observers if peer is not None and not peer.closing]
        return room.observers

    def _observer_view(self, room, roster):
        """The shared watcher payload, or None when nobody watches.

        The game's hook is the only source of watcher data. When it fails the
        room plays on: every watcher is refused and watching ends, loudly in
        the log, while the seats never notice.
        """
        if not self._live_observers(room):
            return None
        try:
            message = {'type': 'state', 'observer': True, 'revision': room.revision, 'ready': room.ready,
                       'seats': len(room.tokens), 'present': room.present,
                       'observer_count': len(room.observers),
                       'state': self.games[room.game].observer_snapshot(room.match),
                       'players': roster, 'rated': room.rated, 'match_id': room.match_id,
                       'result': room.result}
            if len(json.dumps(message, separators=(',', ':'), allow_nan=False)) > MAX_SNAPSHOT:
                raise ValueError('Observer view exceeds the network size limit.')
        except Exception:
            LOG.exception('Observer view failed in %s room', room.game)
            for peer in room.observers:
                peer.reject('The observer view failed.')
            room.observers = []
            return None
        return message

    def _publish(self, room):
        """Publish to seats and watchers; one roster and revision for the whole room."""
        roster = self.roster(room)
        room.publish(roster)
        view = self._observer_view(room, roster)
        if view is not None:
            room.publish_observers(view)

    def _refresh_observers(self, room):
        """Send watchers the current view without moving the revision.

        Watcher arrivals and departures are not match events: bumping the
        revision for them would stale every in-flight seat order. Seats learn
        the new watcher count the same way, from their cached payloads.
        """
        view = self._observer_view(room, self.roster(room))
        if view is not None:
            room.publish_observers(view)
        self._refresh_seat_metadata(room)

    def _refresh_seat_metadata(self, room):
        """Re-send each connected seat its last state with fresh watcher counts.

        Same revision, same game data, no game callbacks: a paused room's
        players learn the new count without a new match event. Advisory only —
        a seat that cannot take it keeps its stale count.
        """
        if not room.seat_states:
            return
        count, ready, present = room.observer_count, room.ready, room.present
        players = self.roster(room)
        for player, peer in enumerate(room.peers):
            if peer is None or peer.closing:
                continue
            payload = room.seat_states.get(player)
            if payload is None:
                continue
            try:
                peer.send({'type': 'state', 'player': player, 'revision': room.revision, 'ready': ready,
                           'seats': len(room.peers), 'present': present, 'state': payload,
                           'players': players, 'rated': room.rated, 'match_id': room.match_id,
                           'result': room.result, 'observer_count': count})
            except RuntimeError:
                pass

    def _prepare_identity(self, game, message):
        """Validate this hello against the accounts without changing anything.

        Returns a staged identity with the writes a later commit must apply;
        raises before any account, profile, room or seat changes. ``enter``
        commits only after every room, seat and game precondition succeeds, so
        a refused request leaves valid profiles untouched and mints no orphan.
        """
        raw = message.get('player_token', None)
        # An omitted name changes nothing: reconnects and token resumes carry no
        # name, and must not rename the account back to the default. Only an
        # explicit name renames; a fresh account starts with the default.
        name = player_name(message['player_name']) if 'player_name' in message else None
        if raw is None or raw == '':
            while True:
                player_id = 'p_' + secrets.token_urlsafe(12)
                if player_id not in self.accounts:
                    break
            token = secrets.token_urlsafe(32)
            profile = {'player_id': player_id, 'name': name or DEFAULT_PLAYER_NAME, 'rating': STARTING_RATING,
                       'games': 0, 'wins': 0, 'losses': 0}
            return _StagedIdentity(player_id, token, profile['name'], _token_hash(token), profile)
        if not isinstance(raw, str):
            raise CommandError('player_token must be text.')
        player_id = next((known for known, hashed in self.accounts.items()
                          if _token_matches(raw, hashed)), None)
        if player_id is None:
            raise CommandError('This player token is unknown. Create without one for a new identity.')
        profile = self.profiles.get((game, player_id))
        if profile is None:
            resolved = {'player_id': player_id, 'name': name or DEFAULT_PLAYER_NAME, 'rating': STARTING_RATING,
                        'games': 0, 'wins': 0, 'losses': 0}
            return _StagedIdentity(player_id, raw, resolved['name'], None, resolved)
        if name is not None and profile['name'] != name:
            return _StagedIdentity(player_id, raw, name, None, {**profile, 'name': name})
        return _StagedIdentity(player_id, raw, profile['name'], None, None)

    def _commit_identity(self, game, staged):
        """Apply a prepared identity: insert the account and profile the hello earned."""
        if staged.account_hash is not None:
            self.accounts[staged.player_id] = staged.account_hash
            if self.store is not None:
                self.store.save_account(staged.player_id, staged.account_hash)
        if staged.profile is not None:
            self.profiles[(game, staged.player_id)] = staged.profile
            if self.store is not None:
                self.store.save_profile(game, staged.player_id, staged.profile)
        return staged.player_id, staged.account_token, staged.name

    def require_rated(self, spec, match, seats):
        """Refuse a rated create the game cannot decide, clearly."""
        if spec.result is None or spec.forfeit is None:
            raise CommandError('This game does not support rated play. Choose a casual room.')
        if spec.campaign:
            raise CommandError('Campaigns cannot be rated. Choose a casual room.')
        if seats not in RATED_SEATS:
            raise CommandError('Rated rooms need 2 to 4 seats.')
        if not spec.rated(match):
            raise CommandError('This match is not eligible for rated play.')

    def retention(self, game):
        return self.campaign_ttl if self.games[game].campaign else self.room_ttl

    def restore(self, saved):
        spec = self.games[saved['game']]
        # Every claimed seat restarts absent: its grace runs from startup, so one
        # returning player never forfeits the others instantly after a restart.
        restarted = time.monotonic()
        room = Room(saved['game'], spec.restore(saved['state']), saved['code'], tokens=saved['tokens'],
                    needed=spec.needed, revision=saved['revision'], match_id=saved.get('match_id') or uuid.uuid4().hex,
                    rated=bool(saved.get('rated')), identities=saved.get('identities'),
                    result=saved.get('result'), started=bool(saved.get('started')),
                    forfeited=saved.get('forfeited'),
                    seat_gone=[restarted] * len(saved['tokens']))
        remaining = saved['expires_at'] - time.time()
        room.disconnected_at = time.monotonic() - (self.retention(room.game) - remaining)
        if room.result is not None:
            self.matches[room.match_id] = room.result
        return room

    def checkpoint(self, room, *, force=False):
        if self.store is not None and (force or time.monotonic() - room.checkpointed_at >= 5):
            self.store.save(room, self.retention(room.game), self.games[room.game].checkpoint(room.match))
            room.checkpointed_at = time.monotonic()

    def suspend(self, room):
        """Keep a campaign's seats in storage only, freeing memory and the room limit.

        Watching ends with the in-memory room: detached watchers get an
        explicit refusal and can watch again once a seat restores it. Detaching
        touches no seat state, so the stored retention stands as it was.
        """
        self.store.suspend(room, self.retention(room.game), self.games[room.game].checkpoint(room.match))
        for peer in room.observers:
            if peer is not None:
                peer.reject('The room was suspended while empty. Watch again to reconnect.')
        room.observers = []
        del self.rooms[room.code]

    def maybe_settle(self, room):
        """Rate one authoritative result per match; replays, polls and restarts cannot rerate."""
        spec = self.games[room.game]
        if not room.rated or room.result is not None or spec.result is None:
            return False
        if room.match_id in self.matches:
            room.result = self.matches[room.match_id]
            return False
        winner = spec.result(room.match)
        if winner is None:
            return False
        if type(winner) is not int or winner not in range(len(room.tokens)):
            raise RuntimeError('The game named a winner outside its seats.')
        seats = [seat for seat, identity in enumerate(room.identities) if identity is not None]
        if winner not in seats:
            raise RuntimeError('The game named an empty seat as winner.')
        entries = [self.public_profile(room.game, room.identities[seat]['player_id']) for seat in seats]
        records = settle_ratings(entries, seats.index(winner))
        result = {'match_id': room.match_id, 'winner': winner, 'ratings': records}
        profiles = {}
        for record in records:
            current = self.profiles[(room.game, record['player_id'])]
            profiles[record['player_id']] = {**current, 'rating': record['after'], 'games': record['games'],
                                             'wins': record['wins'], 'losses': record['losses']}
        if self.store is not None:
            # The terminal checkpoint, the receipt and the new profiles land first in
            # ONE transaction: only then do the public in-memory ratings move.
            room.result = result
            try:
                self.store.record_result(room, self.retention(room.game),
                                         self.games[room.game].checkpoint(room.match), profiles, result)
            finally:
                room.result = None
            room.checkpointed_at = time.monotonic()
        room.result = result
        self.matches[room.match_id] = result
        for player_id, profile in profiles.items():
            self.profiles[(room.game, player_id)] = profile
        return True

    def find_room(self, code, game):
        room = self.rooms.get(code) if isinstance(code, str) else None
        if room is None and self.store is not None and isinstance(code, str):
            saved = self.store.suspended(code)
            if saved is not None and saved['game'] == game:
                if len(self.rooms) >= self.max_rooms:
                    raise CommandError('The server is full. Please try again later.')
                room = self.rooms[code] = self.restore(saved)
        if room is None or room.game != game:
            raise CommandError('Room not found for this game. Check the room code.')
        return room

    def client_address(self, websocket):
        address = websocket.remote_address[0]
        if self.trusted_proxy and ipaddress.ip_address(address).is_loopback:
            forwarded = websocket.request.headers.get_all('X-Forwarded-For')
            if forwarded:
                if len(forwarded) != 1:
                    raise CommandError('Invalid proxy address.')
                try:
                    return str(ipaddress.ip_address(forwarded[0].split(',')[-1].strip()))
                except ValueError as exc:
                    raise CommandError('Invalid proxy address.') from exc
        return address

    def enter(self, message, address):
        if type(message.get('protocol')) is not int or message['protocol'] != PROTOCOL:
            raise IncompatibleClient('Incompatible multiplayer protocol. Update your game client.')
        game, kind = message.get('game'), message.get('type')
        if game not in self.games:
            raise IncompatibleClient('Unknown game version. Update your game client.')
        handles = message.get('seats', 2)  # clients from before rooms of more than two seats say nothing
        if type(handles) is not int or handles < 2:
            raise CommandError('Invalid seat capability.')

        def fits(seats):
            if seats > handles:
                raise IncompatibleClient(f'This match has {seats} seats. Update your game client to play it.')

        def player_options():
            options = message.get('player_options', {})
            if not isinstance(options, dict):
                raise CommandError('Player options must be an object.')
            return options
        if kind == 'create':
            if len(self.rooms) >= self.max_rooms:
                raise CommandError('The server is full. Please try again later.')
            recent = self.creations.setdefault(address, deque())
            now = time.monotonic()
            while recent and recent[0] < now - 60:
                recent.popleft()
            if len(recent) >= 4:
                raise CommandError('Too many new rooms. Please wait a minute.')
            recent.append(now)
            spec = self.games[game]
            rated = message.get('rated', False)
            if type(rated) is not bool:
                raise CommandError('rated must be true or false.')
            match = spec.create(message.get('options', {}))
            seats = spec.seats(match)
            fits(seats)
            if rated:
                self.require_rated(spec, match, seats)
            staged = self._prepare_identity(game, message)
            spec.configure_player(match, 0, player_options())
            player_id, account_token, name = self._commit_identity(game, staged)
            while True:
                code = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(12))
                if code not in self.rooms:
                    break
            room = Room(game, match, code, tokens=[secrets.token_urlsafe(32)] + [None] * (seats - 1),
                        needed=spec.needed, match_id=uuid.uuid4().hex, rated=rated,
                        identities=[{'player_id': player_id, 'name': name}] + [None] * (seats - 1))
            self.rooms[code] = room
            return room, 0, account_token
        room = self.find_room(message.get('room'), game)
        fits(len(room.tokens))
        if kind == 'observe':
            for field in ('resume_token', 'player_token', 'player_name',
                          'player_options', 'options', 'rated'):
                if field in message:
                    raise CommandError('Observers join with only a room code.')
            if self.games[game].observer_snapshot is None:
                raise CommandError('This match does not support observing.')
            if sum(peer is not None and not peer.closing for peer in room.observers) >= MAX_OBSERVERS:
                raise CommandError('This room has too many observers.')
            return room, None, None
        if kind == 'join':
            player = next((seat for seat, token in enumerate(room.tokens) if token is None), None)
            if player is None:
                raise CommandError(('Both seats are claimed.' if len(room.tokens) == 2 else 'Every seat is claimed.')
                                   + ' Reconnect using your saved seat.')
            staged = self._prepare_identity(game, message)
            if room.rated and any(identity is not None and identity['player_id'] == staged.player_id
                                  for identity in room.identities):
                raise CommandError('This account already holds a seat in this rated room. '
                                   + 'Reconnect using your saved seat.')
            self.games[game].configure_player(room.match, player, player_options())
            player_id, account_token, name = self._commit_identity(game, staged)
            room.tokens[player] = secrets.token_urlsafe(32)
            room.identities[player] = {'player_id': player_id, 'name': name}
            return room, player, account_token
        if kind == 'resume':
            raw = message.get('player_token', None)
            if raw is None or raw == '':
                # A seat token alone still resumes its seat; the account binds on demand.
                player_name(message.get('player_name', None))
                staged, supplied = None, False
            else:
                staged = self._prepare_identity(game, message)
                supplied = True
            token = message.get('resume_token')
            if isinstance(token, str):
                for player, expected in enumerate(room.tokens):
                    if expected is not None and secrets.compare_digest(token.encode(), expected.encode()):
                        identity = room.identities[player]
                        if identity is None:
                            if not supplied:
                                staged = self._prepare_identity(game, message)
                            player_id, account_token, name = self._commit_identity(game, staged)
                            room.identities[player] = {'player_id': player_id, 'name': name}
                        elif supplied:
                            if identity['player_id'] != staged.player_id:
                                raise CommandError('This saved seat belongs to a different account.')
                            player_id, account_token, name = self._commit_identity(game, staged)
                        else:
                            player_id, account_token = None, ''
                        if room.peers[player] is not None:
                            room.peers[player].reject('Your seat reconnected from another connection.')
                        return room, player, account_token
            raise CommandError('The saved seat does not belong to this room.')
        raise CommandError('Choose create, join or resume.')

    def fail_room(self, room, error):
        self.rooms.pop(room.code, None)
        for peer in room.peers:
            if peer is not None:
                peer.reject(error)
        for peer in room.observers:
            if peer is not None:
                peer.reject(error)
        if self.store is not None:
            self.store.delete(room.code)

    def apply(self, room, player, message):
        if message.get('type') != 'command' or not isinstance(message.get('command'), dict):
            raise CommandError('Expected a game command.')
        if room.result is not None:
            raise CommandError('The match is over.')
        if not room.ready:
            raise CommandError('Waiting for the other player.' if len(room.peers) == 2 else 'Waiting for the other players.')
        revision = message.get('revision')
        if revision is not None and (type(revision) is not int or revision != room.revision):
            raise CommandError('The match changed. Please try that order again.')
        room.match.apply(player, message['command'])
        self.maybe_settle(room)
        if self.games[room.game].realtime:
            # The room's next tick, at most 50 ms away, tells both seats: a state per order would let a seat's
            # twenty orders a second triple what the room costs the server and the other seat's link.
            room.unpublished = True
        else:
            self._publish(room)
        self.checkpoint(room, force=not self.games[room.game].realtime)

    async def handle(self, websocket):
        peer = Peer(websocket)
        try:
            address = self.client_address(websocket)
        except CommandError as exc:
            peer.reject(str(exc))
            await peer.write()
            return
        if len(self.connections) >= self.max_connections or self.by_ip.get(address, 0) >= 16:
            peer.reject('Too many connections. Please try again later.')
            await peer.write()
            return
        self.connections.add(peer)
        self.by_ip[address] = self.by_ip.get(address, 0) + 1
        writer = asyncio.create_task(peer.write())
        room = None
        player = None
        try:
            message = decode(await asyncio.wait_for(websocket.recv(), timeout=10))
            room, player, account_token = self.enter(message, address)
            if player is None:
                try:
                    room.observers.append(peer)
                    peer.send({'type': 'welcome', 'observer': True, 'player': None,
                               'room': room.code, 'game': room.game, 'protocol': PROTOCOL,
                               'seats': len(room.tokens), 'present': room.present,
                               'observer_count': room.observer_count,
                               'rated': room.rated, 'match_id': room.match_id})
                    self._refresh_observers(room)
                    async for data in websocket:
                        if peer not in room.observers or peer.closing:
                            break
                        peer.check_rate()
                        message = decode(data)
                        if message.get('type') == 'command':
                            peer.send({'type': 'error', 'error': 'Observers cannot submit orders.'})
                        else:
                            peer.send({'type': 'error', 'error': 'Observers only watch the match.'})
                except ConnectionClosed:
                    pass
                except CommandError as exc:
                    peer.reject(str(exc))
                    await writer
                except Exception:
                    LOG.exception('Unexpected failure watching %s room', room.game)
                    peer.reject('The server could not stream this match.')
                    await writer
                finally:
                    if peer in room.observers:
                        room.observers.remove(peer)
                    if room.code in self.rooms:
                        try:
                            self._refresh_observers(room)
                        except Exception:
                            LOG.exception('Could not refresh watchers of %s room', room.game)
                return
            identity = room.identities[player]
            peer.send({'type': 'welcome', 'room': room.code, 'resume_token': room.tokens[player],
                       'player': player, 'seats': len(room.tokens), 'protocol': PROTOCOL, 'game': room.game,
                       'retention': self.retention(room.game), 'rated_grace': self.rated_grace,
                       'player_id': identity['player_id'], 'player_token': account_token,
                       'rating': self.public_profile(room.game, identity['player_id']),
                       'rated': room.rated, 'match_id': room.match_id,
                       'capabilities': {'ratings': True, 'player_options': True}})
            room.peers[player] = peer
            room.seat_gone[player] = None
            self._publish(room)
            self.checkpoint(room, force=True)
            async for data in websocket:
                if room.peers[player] is not peer or peer.closing:
                    break
                peer.check_rate()
                message = decode(data)
                try:
                    self.apply(room, player, message)
                except CommandError as exc:
                    peer.send({'type': 'error', 'error': str(exc)})
        except IncompatibleClient as exc:
            peer.reject(str(exc), reason='incompatible')
            await writer
        except CommandError as exc:
            peer.reject(str(exc))
            await writer
        except TimeoutError:
            peer.reject('Timed out waiting for the room request.')
            await writer
        except ConnectionClosed:
            pass
        except Exception:
            LOG.exception('Unexpected failure in %s room', room.game if room else 'unassigned')
            if room is not None:
                self.fail_room(room, 'The match failed on the server. Please create a new room.')
            else:
                peer.reject('The server could not create this match.')
            await writer
        finally:
            self.connections.discard(peer)
            self.by_ip[address] -= 1
            if not self.by_ip[address]:
                del self.by_ip[address]
            if room is not None and player is not None and room.peers[player] is peer:
                room.peers[player] = None
                room.disconnected_at = time.monotonic()
                room.seat_gone[player] = time.monotonic()
                if room.code in self.rooms:
                    try:
                        self._publish(room)
                        self.checkpoint(room, force=True)
                    except Exception:
                        LOG.exception('Could not publish disconnected %s room', room.game)
                        self.fail_room(room, 'The match failed on the server. Please create a new room.')
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)

    def forfeit_absent(self, room, now):
        """Forfeit rated seats left absent past grace once the match began.

        Only a begun match clocks abandonment: the lobby never starts it, and an
        empty room stays paused. Returns whether the match state changed.
        """
        if not room.started or not room.rated or room.result is not None:
            return False
        spec = self.games[room.game]
        needed = [seat for seat in range(len(room.tokens)) if spec.needed(room.match, seat)]
        connected = [seat for seat in needed
                     if room.peers[seat] is not None and not room.peers[seat].closing]
        if not connected:
            # Nobody to play: the outage must not consume anyone's grace, so the
            # first returning seat gives every other absent seat a fresh window.
            for seat in needed:
                if room.identities[seat] is not None:
                    room.seat_gone[seat] = now
            return False
        overdue = [seat for seat in needed if seat not in connected and room.identities[seat] is not None
                   and not room.forfeited[seat] and room.seat_gone[seat] is not None
                   and now - room.seat_gone[seat] >= self.rated_grace]
        if not overdue:
            return False
        for seat in overdue:
            spec.forfeit(room.match, seat)
            room.forfeited[seat] = True
        self.maybe_settle(room)
        self._publish(room)
        self.checkpoint(room, force=True)
        return True

    async def maintain(self):
        """Advance realtime matches once per 50 ms; discard missed time after overload/suspension."""
        while True:
            started = time.monotonic()
            for room in list(self.rooms.values()):
                try:
                    if not room.ready:
                        idle = started - room.disconnected_at
                        if idle >= self.retention(room.game):
                            self.fail_room(room, 'This room expired while waiting for players. Create a new room.')
                        elif (self.store is not None and self.games[room.game].campaign and idle >= self.room_ttl
                                and all(peer is None for peer in room.peers)):
                            self.suspend(room)
                        else:
                            self.forfeit_absent(room, started)
                    elif self.games[room.game].realtime:
                        room.match.step()
                        room.ticks += 1
                        settled = self.maybe_settle(room)
                        if room.ticks % 2 == 0 or room.unpublished or settled:
                            self._publish(room)
                        self.checkpoint(room)
                    else:
                        if self.maybe_settle(room):
                            self._publish(room)
                            self.checkpoint(room, force=True)
                except Exception:
                    LOG.exception('Simulation failed in %s room', room.game)
                    self.fail_room(room, 'The match failed on the server. Please create a new room.')
            if self.store is not None and started - self.last_keep_alive >= min(60, self.room_ttl / 3):
                self.store.keep_alive([(room.code, self.retention(room.game))
                                       for room in self.rooms.values() if room.ready])
                self.store.purge()
                self.last_keep_alive = started
            self.creations = {address: times for address, times in self.creations.items()
                              if times and times[-1] > started - 60}
            await asyncio.sleep(max(0.001, .05 - (time.monotonic() - started)))

    def ratings_info(self):
        """Which games take rated rooms; counts only, nothing about any room or player."""
        return {game_id: ({'enabled': True, 'seats': list(RATED_SEATS), 'starting_rating': STARTING_RATING}
                          if spec.result is not None and spec.forfeit is not None and not spec.campaign
                          else {'enabled': False, 'seats': [], 'starting_rating': STARTING_RATING})
                for game_id, spec in self.games.items()}

    def leaderboard(self, game, limit):
        """Public profiles, best first; ties keep first-seen order and carry no secrets."""
        profiles = [self.public_profile(game, player_id) for (played, player_id) in self.profiles
                    if played == game]
        profiles.sort(key=lambda profile: -profile['rating'])
        return profiles[:limit]

    def json_reply(self, connection, status, payload):
        response = connection.respond(status, json.dumps(payload, separators=(',', ':'),
                                                         allow_nan=False) + '\n')
        # Headers.__setitem__ appends rather than replaces: drop the plain-text
        # default first so JSON is the only content type on the wire.
        del response.headers['Content-Type']
        response.headers['Content-Type'] = 'application/json'
        return response

    def health(self, connection, request):
        """Plain health, public counts and leaderboards; WebSocket paths fall through to the handshake."""
        if request.method != 'GET':
            return connection.respond(HTTPStatus.METHOD_NOT_ALLOWED, 'method not allowed\n')
        path, _, query = request.path.partition('?')
        if path == '/healthz' and not query:
            return connection.respond(HTTPStatus.OK, 'ok\n')
        if path == '/status' and not query:
            rooms = list(self.rooms.values())
            return self.json_reply(connection, HTTPStatus.OK, {
                'protocol': PROTOCOL, 'games': sorted(self.games),
                'rooms': len(rooms), 'ready_rooms': sum(1 for room in rooms if room.ready),
                'players': sum(room.present for room in rooms),
                'observers': sum(room.observer_count for room in rooms),
                'max_rooms': self.max_rooms, 'max_connections': self.max_connections,
                'room_retention': self.room_ttl, 'campaign_retention': self.campaign_ttl,
                'rated_grace': self.rated_grace, 'ratings': self.ratings_info()})
        if path == '/ratings':
            fields = parse_qs(query, keep_blank_values=True)
            game = fields.get('game', [''])[0]
            if game not in self.games:
                return self.json_reply(connection, HTTPStatus.NOT_FOUND, {'error': 'Unknown game.'})
            try:
                limit = int(fields.get('limit', ['20'])[0])
            except ValueError:
                return self.json_reply(connection, HTTPStatus.BAD_REQUEST, {'error': 'limit must be 1 to 100.'})
            if not 1 <= limit <= 100:
                return self.json_reply(connection, HTTPStatus.BAD_REQUEST, {'error': 'limit must be 1 to 100.'})
            return self.json_reply(connection, HTTPStatus.OK,
                                   {'game': game, 'players': self.leaderboard(game, limit)})
        if path.startswith('/players/') and '/' not in path[len('/players/'):]:
            player_id = unquote(path[len('/players/'):])
            fields = parse_qs(query, keep_blank_values=True)
            game = fields.get('game', [''])[0]
            if game not in self.games:
                return self.json_reply(connection, HTTPStatus.NOT_FOUND, {'error': 'Unknown game.'})
            profile = self.public_profile(game, player_id)
            if profile is None:
                return self.json_reply(connection, HTTPStatus.NOT_FOUND, {'error': 'Unknown player.'})
            return self.json_reply(connection, HTTPStatus.OK, profile)
        if path not in ('/', '/ws', '/play'):
            return connection.respond(HTTPStatus.NOT_FOUND, 'not found\n')


async def run(host='127.0.0.1', port=8765, *, games, **limits):
    """Serve ``games`` until cancelled; close every socket, timer and checkpoint on shutdown."""
    rooms = RoomServer(games, **limits)
    try:
        async with serve(rooms.handle, host, port, process_request=rooms.health, origins=[None],
                         max_size=MAX_MESSAGE, max_queue=8, ping_interval=10, ping_timeout=10,
                         close_timeout=2, open_timeout=10, server_header=None, backlog=64) as server:
            address = server.sockets[0].getsockname()
            print(f'LISTENING ws://{address[0]}:{address[1]}', flush=True)
            # Awaiting maintenance also makes a broken persistence store fail the service visibly.
            await rooms.maintain()
    finally:
        if rooms.store is not None:
            for room in rooms.rooms.values():
                rooms.checkpoint(room, force=True)
            rooms.store.close()
