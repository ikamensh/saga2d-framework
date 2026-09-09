"""Private, atomic JSON checkpoints; SQLite owns the write/replace transaction."""
import json
from pathlib import Path
import sqlite3
import time

COLUMNS = 'code, game, tokens, state, revision, expires_at'


class RoomStore:
    """``rooms`` holds every retained room; ``suspended`` lists the codes kept out of memory.

    The separate table is additive: an earlier server release reads the same
    database unchanged, so a code rollback never needs a schema rollback.
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
            self.db.execute('PRAGMA user_version=1')

    def _record(self, row):
        code, game, tokens, state, revision, expires_at = row
        return dict(code=code, game=game, tokens=json.loads(tokens), state=json.loads(state),
                    revision=revision, expires_at=expires_at)

    def purge(self):
        """Expired rooms stay expired through restarts; suspended ones expire the same way."""
        with self.db:
            self.db.execute('DELETE FROM rooms WHERE expires_at <= ?', (time.time(),))
            self.db.execute('DELETE FROM suspended WHERE code NOT IN (SELECT code FROM rooms)')

    def load(self):
        """The rooms to hold in memory at startup; corruption fails startup clearly."""
        self.purge()
        return [self._record(row) for row in self.db.execute(
            f'SELECT {COLUMNS} FROM rooms WHERE code NOT IN (SELECT code FROM suspended)')]

    def suspended(self, code):
        """A retained room that is not in memory, or None."""
        row = self.db.execute(f'SELECT {COLUMNS} FROM rooms WHERE code = ? AND expires_at > ? '
                              'AND code IN (SELECT code FROM suspended)', (code, time.time())).fetchone()
        return None if row is None else self._record(row)

    def _write(self, room, ttl, state):
        remaining = ttl if room.ready else max(0, ttl - (time.monotonic() - room.disconnected_at))
        self.db.execute(f'INSERT OR REPLACE INTO rooms ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)',
                        (room.code, room.game, json.dumps(room.tokens),
                         json.dumps(state, separators=(',', ':'), allow_nan=False),
                         room.revision, time.time() + remaining))

    def save(self, room, ttl, state):
        """Retain ``state``, the game's checkpoint of the room's match, for ``ttl`` seconds."""
        with self.db:
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

    def close(self):
        self.db.close()
