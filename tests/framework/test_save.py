"""Durable save slots through the public manager and real filesystem failures."""

import json
import errno
import os
from pathlib import Path

import pytest

from saga2d import SaveError, SaveManager


@pytest.mark.parametrize('version', [999, 0, True, '1', None])
def test_unsupported_save_envelopes_are_refused_with_explicit_errors(tmp_path, version):
    """A future or malformed envelope cannot reach game reconstruction unchecked."""
    manager = SaveManager(tmp_path)
    manager.save(1, {'turn': 3}, 'Campaign')
    path = tmp_path / 'save_1.json'
    payload = json.loads(path.read_text())
    payload['version'] = version
    path.write_text(json.dumps(payload))
    with pytest.raises(SaveError, match='version'):
        manager.load(1)


@pytest.mark.parametrize(('field', 'value'), [('timestamp', None), ('timestamp', 'not a date'),
                                           ('scene_class', None), ('scene_class', ''), ('state', []), ('state', None)])
def test_malformed_save_metadata_is_rejected_before_it_reaches_a_scene(tmp_path, field, value):
    """An envelope contains usable metadata and a game-state object, not arbitrary JSON."""
    manager = SaveManager(tmp_path)
    manager.save(1, {'turn': 3}, 'Campaign')
    path = tmp_path / 'save_1.json'
    payload = json.loads(path.read_text())
    payload[field] = value
    path.write_text(json.dumps(payload))
    with pytest.raises(SaveError, match=field):
        manager.load(1)


def test_each_successful_save_retains_the_previous_valid_envelope_for_explicit_recovery(tmp_path):
    """Current and backup advance independently, and loading a backup changes no files."""
    manager = SaveManager(tmp_path)
    assert manager.load(1) is None
    assert manager.load_backup(1) is None
    previous = None
    for turn in range(1, 4):
        manager.save(1, {'turn': turn, 'army': ['militia', 'archer']}, 'Campaign')
        assert manager.load_backup(1) == previous
        previous = manager.load(1)
        assert previous['state']['turn'] == turn
    current_path = tmp_path / 'save_1.json'
    current_path.write_text('{broken')
    with pytest.raises(SaveError):
        manager.load(1)
    assert manager.load_backup(1)['state']['turn'] == 2
    assert current_path.read_text() == '{broken'
    manager.save(2, manager.load_backup(1)['state'], 'Campaign')
    assert manager.load(2)['state']['turn'] == 2


@pytest.mark.parametrize('content', ['{', '[]', '{}', 'null', '\ufeff{}'])
def test_malformed_json_never_silently_loads_a_backup(tmp_path, content):
    """Corrupt or wrong-shaped JSON reports its file while preserving recovery data."""
    manager = SaveManager(tmp_path)
    manager.save(1, {'turn': 1}, 'Campaign')
    manager.save(1, {'turn': 2}, 'Campaign')
    (tmp_path / 'save_1.json').write_text(content)
    with pytest.raises(SaveError, match='save_1.json'):
        manager.load(1)
    assert manager.load_backup(1)['state']['turn'] == 1


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity', '1e999', '-1e999'])
def test_nonfinite_numbers_are_not_accepted_as_json_save_data(tmp_path, token):
    """The envelope accepts standard JSON, so invalid numbers cannot escape into a game."""
    manager = SaveManager(tmp_path)
    manager.save(1, {'turn': 1}, 'Campaign')
    payload = manager.load(1)
    payload['state']['value'] = 'raw-number'
    (tmp_path / 'save_1.json').write_text(json.dumps(payload).replace('"raw-number"', token))
    with pytest.raises(SaveError, match='number'):
        manager.load(1)


@pytest.mark.parametrize('invalid_state', [{'not_json': {1, 2}}, {'number': float('nan')}, [], None])
def test_invalid_new_state_cannot_damage_current_save_or_backup(tmp_path, invalid_state):
    """Serialization and state-shape errors happen before existing progress changes."""
    manager = SaveManager(tmp_path)
    manager.save(1, {'turn': 1}, 'Campaign')
    manager.save(1, {'turn': 2}, 'Campaign')
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(SaveError):
        manager.save(1, invalid_state, 'Campaign')
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_saving_over_corruption_preserves_the_bad_file_and_last_valid_backup(tmp_path):
    """Overwriting damaged evidence requires an explicit caller decision."""
    manager = SaveManager(tmp_path)
    manager.save(1, {'turn': 1}, 'Campaign')
    manager.save(1, {'turn': 2}, 'Campaign')
    (tmp_path / 'save_1.json').write_bytes(b'\xffinvalid utf-8')
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(SaveError):
        manager.save(1, {'turn': 3}, 'Campaign')
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    assert manager.load_backup(1)['state']['turn'] == 1


def test_a_real_backup_path_conflict_preserves_current_progress_and_cleans_staging(tmp_path):
    """A filesystem failure during replacement cannot destroy the active save."""
    manager = SaveManager(tmp_path)
    manager.save(1, {'turn': 1}, 'Campaign')
    before = manager.load(1)
    (tmp_path / 'save_1.backup.json').mkdir()
    with pytest.raises(SaveError):
        manager.save(1, {'turn': 2}, 'Campaign')
    assert manager.load(1) == before
    assert sorted(path.name for path in tmp_path.iterdir()) == ['save_1.backup.json', 'save_1.json']


@pytest.mark.parametrize('operation', ['fsync', 'replace'])
def test_os_write_failures_keep_a_valid_current_save_and_recovery_copy(tmp_path, monkeypatch, operation):
    """Inject an OS boundary failure while staging and reading remain real I/O."""
    manager = SaveManager(tmp_path)
    manager.save(1, {'turn': 1}, 'Campaign')
    manager.save(1, {'turn': 2}, 'Campaign')
    before = manager.load(1)
    original_replace = os.replace

    def fail_sync(descriptor):
        raise OSError(errno.ENOSPC, 'injected full disk during sync')

    def fail_current_replace(source, destination):
        if Path(destination) == tmp_path / 'save_1.json':
            raise OSError(errno.ENOSPC, 'injected full disk during replacement')
        return original_replace(source, destination)

    monkeypatch.setattr(os, operation, fail_sync if operation == 'fsync' else fail_current_replace)
    with pytest.raises(SaveError, match='injected full disk'):
        manager.save(1, {'turn': 3}, 'Campaign')
    assert manager.load(1) == before
    assert manager.load_backup(1)['state']['turn'] in (1, 2)
    assert sorted(path.name for path in tmp_path.iterdir()) == ['save_1.backup.json', 'save_1.json']


def test_invalid_backup_is_refused_and_clearing_current_preserves_recovery(tmp_path):
    """Backups use the same validator and remain available after clearing a bad current file."""
    manager = SaveManager(tmp_path)
    manager.save(1, {'turn': 1}, 'Campaign')
    manager.save(1, {'turn': 2}, 'Campaign')
    manager.delete(1)
    assert manager.load(1) is None
    assert manager.load_backup(1)['state']['turn'] == 1
    (tmp_path / 'save_1.backup.json').write_text('{broken')
    with pytest.raises(SaveError, match='save_1.backup.json'):
        manager.load_backup(1)
