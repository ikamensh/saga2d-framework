"""Preferences through Game/Settings and real files, independent of campaigns."""

from pathlib import Path

import pytest

from saga2d import Game, Settings, SettingsError


def test_preferences_survive_game_restart_and_new_defaults(tmp_path):
    """The same data directory restores preferences and fills newly added keys."""
    defaults = {"volume": .8, "muted": False}
    game = Game("Preferences test", backend="mock", save_dir=tmp_path / "saves")
    try:
        settings = game.settings(defaults)
        assert isinstance(settings, Settings)
        assert game.data_dir == tmp_path
        assert settings is game.settings(defaults)
        settings["volume"] = .3
        settings["mod_name"] = "custom"
        settings.save()
        game.save_manager.save(1, {"turn": 7}, "Map")
    finally:
        game._teardown()
    restarted = Game("Preferences test", backend="mock", save_dir=tmp_path / "saves")
    try:
        settings = restarted.settings({**defaults, "reduced_motion": False})
        assert dict(settings) == {"volume": .3, "muted": False, "mod_name": "custom", "reduced_motion": False}
        assert settings.error is None
        assert restarted.save_manager.load(1)["state"] == {"turn": 7}
    finally:
        restarted._teardown()


@pytest.mark.parametrize("content", [
    '{"volume": true}', '{"muted": 1}', '{"volume": "loud"}',
    '{"volume": NaN}', '{"volume": Infinity}', '{"volume": 1e999}',
    '{"unknown": [NaN]}', '[]', '{', b'\xff',
    '{"volume": NaN, "volume": 0.5}', '{"volume": 1e999, "volume": 0.5}',
    '{"nested":' + '[' * 100 + '0' + ']' * 100 + '}',
    '{"nested":' + '[' * 10000 + '0' + ']' * 10000 + '}',
    '{"huge":' + '1' * 5001 + '}',
], ids=["bool-as-number", "number-as-bool", "wrong-type", "nan", "infinity", "overflow",
        "nested-nan", "array", "syntax", "encoding", "shadowed-nan", "shadowed-overflow",
        "depth-limit", "decoder-depth", "huge-integer"])
def test_invalid_files_report_error_without_partially_loading_preferences(tmp_path, content):
    """Unsafe disk values never masquerade as usable settings or replace defaults."""
    path = tmp_path / "settings.json"
    path.write_bytes(content.encode() if isinstance(content, str) else content)
    settings = Settings(path, {"volume": .8, "muted": False})
    assert settings.error is not None
    assert str(path) in settings.error
    assert dict(settings) == {"volume": .8, "muted": False}


def test_ordinary_save_preserves_current_corruption_even_if_file_changed_after_load(tmp_path):
    """Saving edits never silently overwrites a damaged on-disk preferences file."""
    path = tmp_path / "settings.json"
    settings = Settings(path, {"volume": .8})
    settings.save()
    settings["volume"] = .3
    path.write_bytes(b"\xffdamaged preferences")
    with pytest.raises(SettingsError):
        settings.save()
    assert path.read_bytes() == b"\xffdamaged preferences"
    assert sorted(tmp_path.iterdir()) == [path]


def test_explicit_reset_retains_displaced_bytes_and_preserves_prior_recoveries(tmp_path):
    """Reset changes memory first; saving it retains every displaced file exactly."""
    path = tmp_path / "settings.json"
    settings = Settings(path, {"volume": .8})
    settings.save()
    settings["volume"] = .3
    settings.save()
    backup = path.with_suffix(".backup.json").read_bytes()
    for damaged in (b"\xffbroken", b'{"volume": true}'):
        path.write_bytes(damaged)
        settings.load()
        assert settings.error is not None
        settings.reset()
        assert path.read_bytes() == damaged
        assert settings.error is not None
        settings.save()
        assert settings.error is None
        assert dict(Settings(path, settings.defaults)) == {"volume": .8}
        assert damaged in [item.read_bytes() for item in tmp_path.glob("settings.recovery-*.json")]
    assert len(list(tmp_path.glob("settings.recovery-*.json"))) == 2
    assert path.with_suffix(".backup.json").read_bytes() == backup


@pytest.mark.parametrize(("key", "value"), [
    ("volume", True), ("muted", 0), ("volume", "loud"),
    ("volume", float("nan")), ("volume", float("inf")),
    ("unknown", {1: "not a JSON key"}), ("unknown", {1, 2}),
])
def test_invalid_edits_fail_without_changing_live_values_or_disk(tmp_path, key, value):
    """Validation fails at the edit, before unusable values reach game code."""
    settings = Settings(tmp_path / "settings.json", {"volume": .8, "muted": False})
    settings.save()
    before = dict(settings)
    disk = settings.path.read_bytes()
    with pytest.raises(SettingsError):
        settings[key] = value
    assert dict(settings) == before
    assert settings.path.read_bytes() == disk


def test_nested_edits_are_revalidated_before_saving_and_defaults_are_independent(tmp_path):
    """Mutable JSON values cannot corrupt defaults or bypass write validation."""
    defaults = {"bundle": {"values": [1, 2]}}
    settings = Settings(tmp_path / "settings.json", defaults)
    settings.save()
    disk = settings.path.read_bytes()
    settings["bundle"]["values"].append(float("nan"))
    with pytest.raises(SettingsError):
        settings.save()
    assert settings.path.read_bytes() == disk
    assert defaults == {"bundle": {"values": [1, 2]}}
    settings.reset()
    assert settings["bundle"] == defaults["bundle"]


def test_game_validator_owns_ranges_and_runs_on_load_edit_and_save(tmp_path):
    """Games supply their own value rules without declaring a framework options schema."""
    defaults = {"volume": .8, "mode": "calm"}

    def validate(values):
        if not 0 <= values["volume"] <= 1:
            raise ValueError("volume must be between 0 and 1")
        if values["mode"] not in ("calm", "bold"):
            raise ValueError("mode must be calm or bold")

    game = Game("Validated preferences", backend="mock", save_dir=tmp_path / "saves")
    try:
        settings = game.settings(defaults, validator=validate)
        settings["volume"] = 1  # integer JSON numbers remain compatible with float defaults.
        with pytest.raises(SettingsError, match="between"):
            settings["volume"] = 1.1
        settings.save()
        settings.path.write_text('{"mode": "unknown"}')
        settings.load()
        assert "mode" in settings.error
        assert dict(settings) == defaults
        with pytest.raises(SettingsError, match="mode"):
            settings.save()
    finally:
        game._teardown()


@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_failed_writes_preserve_existing_file_and_leave_no_staging_files(tmp_path, monkeypatch, recover, operation):
    """OS faults before replacement preserve the previous bytes, including damaged evidence."""
    import errno
    import os

    settings = Settings(tmp_path / "settings.json", {"volume": .8})
    settings.save()
    if recover:
        settings.path.write_bytes(b"\xffbroken")
        settings.load()
        settings.reset()
    else:
        settings["volume"] = .3
    before = settings.path.read_bytes()
    original_replace = os.replace

    def fail_sync(descriptor):
        raise OSError(errno.ENOSPC, "injected full disk")

    def fail_current_replace(source, destination):
        if Path(destination) == settings.path:
            raise OSError(errno.ENOSPC, "injected full disk")
        return original_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(os, operation, fail_sync if operation == "fsync" else fail_current_replace)
        with pytest.raises(SettingsError, match="injected full disk"):
            settings.save()
    assert settings.path.read_bytes() == before
    assert not list(tmp_path.glob(".*.tmp"))
    settings.save()
    assert Settings(settings.path, settings.defaults)["volume"] == (.8 if recover else .3)
    if recover:
        assert before in [item.read_bytes() for item in tmp_path.glob("settings.recovery-*.json")]


def test_real_backup_path_conflict_refuses_save_without_replacing_current(tmp_path):
    """A blocked recovery destination cannot be treated as a successful save."""
    settings = Settings(tmp_path / "settings.json", {"volume": .8})
    settings.save()
    settings.path.with_suffix(".backup.json").mkdir()
    settings["volume"] = .3
    with pytest.raises(SettingsError):
        settings.save()
    assert Settings(settings.path, settings.defaults)["volume"] == .8
    assert not list(tmp_path.glob(".*.tmp"))


def test_missing_file_uses_title_data_directory_without_creating_files(tmp_path, monkeypatch):
    """Default path discovery is lazy, and reading preferences does not create directories."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    game = Game("Quiet Game!", backend="mock")
    try:
        assert game.data_dir == tmp_path / ".quiet_game"
        settings = game.settings({"muted": True})
        assert settings["muted"] is True
        assert not game.data_dir.exists()
    finally:
        game._teardown()
