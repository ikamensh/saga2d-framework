"""A game-independent persistent settings example.

    uv run python tools/demo_settings.py /tmp/saga2d-preferences --volume .3
    uv run python tools/demo_settings.py /tmp/saga2d-preferences --muted
    uv run python tools/demo_settings.py /tmp/saga2d-preferences --reset

Re-run to observe persistence. --reset explicitly retains the displaced file
before restoring defaults, including when the old JSON cannot be loaded.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from saga2d import Settings, SettingsError  # noqa: E402


DEFAULTS = {"volume": .6, "muted": False}


def validate(values):
    if not 0 <= values["volume"] <= 1:
        raise ValueError("volume must be between 0 and 1")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--volume", type=float)
    parser.add_argument("--muted", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    settings = Settings(args.directory / "settings.json", DEFAULTS, validator=validate)
    try:
        if args.reset:
            settings.reset()
        elif settings.error is not None:
            raise SettingsError(f"{settings.error}; use --reset to recover and retain the damaged file")
        if args.volume is not None:
            settings["volume"] = args.volume
        if args.muted is not None:
            settings["muted"] = args.muted
        settings.save()
    except SettingsError as exc:
        parser.error(str(exc))
    print(f"Saved {dict(settings)} to {settings.path}")


if __name__ == "__main__":
    main()
