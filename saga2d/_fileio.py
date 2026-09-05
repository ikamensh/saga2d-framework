"""Private durable file replacement shared by save slots and preferences.

Callers serialize and validate their data before entering this module. They
also own backup/recovery policy; this module only stages, syncs and replaces.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from collections.abc import Iterator


def durable_write(path: Path, data: bytes, *, backup: tuple[Path, bytes] | None = None) -> None:
    """Replace a file after syncing its bytes, optionally retaining prior data.

    Before the current replacement, a failure leaves the current file intact.
    A directory-sync failure after replacement is reported even though the
    replacement may already be visible. A supplied backup remains recoverable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with _staged_file(path, data) as staged:
        if backup is not None:
            backup_path, previous = backup
            with _staged_file(backup_path, previous) as staged_backup:
                staged_backup.replace(backup_path)
                _sync_directory(backup_path.parent)
        staged.replace(path)
        _sync_directory(path.parent)


@contextmanager
def _staged_file(path: Path, data: bytes) -> Iterator[Path]:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        yield staged
    finally:
        staged.unlink(missing_ok=True)


def _sync_directory(directory: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
