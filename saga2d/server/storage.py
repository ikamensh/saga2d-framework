"""Private, atomic JSON checkpoints; SQLite owns the write/replace transaction."""
import json
from pathlib import Path
import sqlite3
import time

COLUMNS = 'code, game, tokens, state, revision, expires_at'
ROOM_EXTRA = 'match_id, rated, identities, result, started, forfeited'


class RoomStore:
    """``rooms`` holds every retained room; ``suspended`` lists the codes kept out of memory.

    The separate table is additive: an earlier server release reads the same
    database unchanged, so a code rollback never needs a schema rollback. The
    identity, rating and match tables are new tables for the same reason, and
    the room columns arrive through ``ADD COLUMN``, which an earlier release
    never selects.
    """
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'rooms.sqlite3'
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        self.db = sqlite3.connect(self.path)
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            raise ValueError(f'Unsupported room checkpoint version: {version}')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS rooms (
                code TEXT PRIMARY KEY, game TEXT NOT NULL, tokens TEXT NOT NULL,
                state TEXT NOT NULL, revision INTEGER NOT NULL, expires_at REAL NOT NULL
            )''')
            self.db.execute('CREATE TABLE IF NOT EXISTS suspended (code TEXT PRIMARY KEY)')
            for column, kind in (('match_id', 'TEXT'), ('rated', 'INTEGER'), ('identities', 'TEXT'),
                                 ('result', 'TEXT'), ('started', 'INTEGER'), ('forfeited', 'TEXT')):
                try:
                    self.db.execute(f'ALTER TABLE rooms ADD COLUMN {column} {kind}')
                except sqlite3.OperationalError as exc:
                    if 'duplicate column name' not in str(exc):
                        raise  # a previous launch already widened the table; anything else is real
            self.db.execute('''CREATE TABLE IF NOT EXISTS accounts (
                player_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL
            )''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS ratings (
                game TEXT NOT NULL, player_id TEXT NOT NULL, name TEXT NOT NULL,
                rating REAL NOT NULL, games INTEGER NOT NULL, wins INTEGER NOT NULL,
                losses INTEGER NOT NULL, PRIMARY KEY (game, player_id)
            )''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS matches (
                match_id TEXT PRIMARY KEY, game TEXT NOT NULL, result TEXT NOT NULL
            )''')
            self.db.execute('PRAGMA user_version=1')

    def _record(self, row):
        code, game, tokens, state, revision, expires_at, match_id, rated, identities, result, started, forfeited = row
        return dict(code=code, game=game, tokens=json.loads(tokens), state=json.loads(state),
                    revision=revision, expires_at=expires_at, match_id=match_id,
                    rated=bool(rated) if rated is not None else False,
                    identities=json.loads(identities) if identities is not None else None,
                    result=json.loads(result) if result is not None else None,
                    started=bool(started) if started is not None else False,
                    forfeited=json.loads(forfeited) if forfeited is not None else None)

    def _select(self):
        return f'SELECT {COLUMNS}, {ROOM_EXTRA} FROM rooms'

    def purge(self):
        """Expired rooms stay expired through restarts; suspended ones expire the same way."""
        with self.db:
            self.db.execute('DELETE FROM rooms WHERE expires_at <= ?', (time.time(),))
            self.db.execute('DELETE FROM suspended WHERE code NOT IN (SELECT code FROM rooms)')

    def load(self):
        """The rooms to hold in memory at startup; corruption fails startup clearly."""
        self.purge()
        return [self._record(row) for row in self.db.execute(
            f'{self._select()} WHERE code NOT IN (SELECT code FROM suspended)')]

    def suspended(self, code):
        """A retained room that is not in memory, or None."""
        row = self.db.execute(f'{self._select()} WHERE code = ? AND expires_at > ? '
                              'AND code IN (SELECT code FROM suspended)', (code, time.time())).fetchone()
        return None if row is None else self._record(row)

    def _write(self, room, ttl, state):
        remaining = ttl if room.ready else max(0, ttl - (time.monotonic() - room.disconnected_at))
        self.db.execute(f'INSERT OR REPLACE INTO rooms ({COLUMNS}, {ROOM_EXTRA}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        (room.code, room.game, json.dumps(room.tokens),
                         json.dumps(state, separators=(',', ':'), allow_nan=False),
                         room.revision, time.time() + remaining, room.match_id or None, int(room.rated),
                         json.dumps(room.identities), json.dumps(room.result), int(room.started),
                         json.dumps(room.forfeited)))

    def save(self, room, ttl, state):
        """Retain ``state``, the game's checkpoint of the room's match, for ``ttl`` seconds."""
        with self.db:
            self._write(room, ttl, state)
            self.db.execute('DELETE FROM suspended WHERE code = ?', (room.code,))

    def record_result(self, room, ttl, state, profiles, result):
        """Settle a rated match once: the terminal checkpoint, the new ratings and the
        recorded result land in ONE transaction, so a crash can never restore an
        unfinished match after its result was already told."""
        with self.db:
            for player_id, profile in profiles.items():
                self.db.execute('INSERT OR REPLACE INTO ratings '
                                '(game, player_id, name, rating, games, wins, losses) VALUES (?, ?, ?, ?, ?, ?, ?)',
                                (room.game, player_id, profile['name'], profile['rating'],
                                 profile['games'], profile['wins'], profile['losses']))
            self.db.execute('INSERT INTO matches (match_id, game, result) VALUES (?, ?, ?)',
                            (room.match_id, room.game, json.dumps(result, separators=(',', ':'))))
            self._write(room, ttl, state)
            self.db.execute('DELETE FROM suspended WHERE code = ?', (room.code,))

    def suspend(self, room, ttl, state):
        with self.db:
            self._write(room, ttl, state)
            self.db.execute('INSERT OR REPLACE INTO suspended VALUES (?)', (room.code,))

    def keep_alive(self, retained):
        """Thinking time keeps active matches alive without rewriting their worlds."""
        with self.db:
            self.db.executemany('UPDATE rooms SET expires_at = ? WHERE code = ?',
                                [(time.time() + ttl, code) for code, ttl in retained])

    def delete(self, code):
        with self.db:
            self.db.execute('DELETE FROM rooms WHERE code = ?', (code,))
            self.db.execute('DELETE FROM suspended WHERE code = ?', (code,))

    def save_account(self, player_id, token_hash):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO accounts (player_id, token_hash) VALUES (?, ?)',
                            (player_id, token_hash))

    def save_profile(self, game, player_id, profile):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO ratings '
                            '(game, player_id, name, rating, games, wins, losses) VALUES (?, ?, ?, ?, ?, ?, ?)',
                            (game, player_id, profile['name'], profile['rating'],
                             profile['games'], profile['wins'], profile['losses']))

    def load_accounts(self):
        return {player_id: token_hash for player_id, token_hash in
                self.db.execute('SELECT player_id, token_hash FROM accounts')}

    def load_profiles(self):
        return {(game, player_id): {'player_id': player_id, 'name': name, 'rating': rating,
                                    'games': games, 'wins': wins, 'losses': losses}
                for game, player_id, name, rating, games, wins, losses in
                self.db.execute('SELECT game, player_id, name, rating, games, wins, losses FROM ratings')}

    def load_matches(self):
        return {match_id: json.loads(result) for match_id, result in
                self.db.execute('SELECT match_id, result FROM matches')}

    def close(self):
        self.db.close()
