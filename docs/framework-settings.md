# Persistent preferences

`Settings` stores preferences separately from campaign progress. It adapts
Warband's committed defaults/mapping interface for Tribes and Shardbound too.
The framework owns JSON validation, durable writes and retained recovery;
the game owns option names, ranges, menus and application to audio/display.

```python
from saga2d import Game, SettingsError

DEFAULTS = {"volume": .6, "muted": False, "reduced_motion": False}

def validate(values):
    if not 0 <= values["volume"] <= 1:
        raise ValueError("volume must be between 0 and 1")

game = Game("Example")
settings = game.settings(DEFAULTS, validator=validate)
if settings.error is not None:
    # Show this error and offer explicit recovery; no file has changed.
    print(settings.error)

settings["volume"] = .4
try:
    settings.save()
except SettingsError as error:
    print(error)  # Keep the settings screen open; do not announce success.
```

`game.settings` returns one shared object, using defaults and validator from
its first call. `game.data_dir` is the parent of an explicitly configured
`save_dir`, or the title-derived `~/.<title>` directory. Reading absent
preferences creates no files. `Settings(path, defaults, validator=...)` also
works independently of `Game`; import it from `saga2d`.

Missing keys receive their defaults, and unknown keys survive reload/save.
Known keys keep the default's JSON kind. Integers and floats share a numeric
kind; booleans never count as numbers. Nested containers are ordinary JSON
data, not an inferred schema. Keys must be strings, numbers finite, and
nesting at most 64 levels. A validator inspects the complete candidate mapping
and raises `ValueError` for game-owned ranges or enums; it must not mutate the
mapping. Invalid defaults or assignments raise `SettingsError`. Nested mutable
values are checked again at save time.

A load failure sets `settings.error` and leaves defaults in memory. It never
silently loads the backup or replaces the file. Ordinary `save()` rechecks
current disk data and refuses invalid content, even if the file changed after
the initial load. Successful overwrites retain the exact previous file at
`settings.backup.json`.

For an explicit “Restore defaults” action:

```python
settings.reset()  # Memory only; still possible to cancel with settings.load().
settings.save()   # Retains the old bytes, then replaces the current file.
```

Reset preserves the displaced file at `settings.recovery-<unique id>.json`,
including malformed JSON and invalid UTF-8. Existing recoveries and the normal
backup remain intact. A failed save keeps reset pending for retry; a successful
save clears `error`. A failed directory sync after replacement can leave the
new file visible, but the retained copy still holds the prior data. Games
should display write errors and offer retry, rather than claiming success.
To inspect a valid backup, construct a separate `Settings` with its path; there
is no implicit fallback or automatic recovery selection.

Try the independent CLI example against a disposable directory:

```bash
uv run python tools/demo_settings.py /tmp/example-preferences --volume .3
uv run python tools/demo_settings.py /tmp/example-preferences --muted
uv run python tools/demo_settings.py /tmp/example-preferences --reset
```

Public integration tests exercise actual file restart, malformed input,
finite/type validation, game validation, reset retention, disk-full failures
and conflicting backup paths. SaveManager's existing durability tests also
cover the shared private writer.
