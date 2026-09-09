"""Frozen entry point of a packaged game, including isolated diagnostics for the shipped executable.

``saga2d.packaging.build`` copies this file into the build snapshot with
``PACKAGE`` set to the game's import name; ``package_check.py`` beside it holds
the game's own smoke checks.
"""
import argparse
import importlib
import json
from pathlib import Path
import sys
import traceback

PACKAGE = "__PACKAGE__"


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--package-smoke", type=Path)
    parser.add_argument("--package-native-smoke", type=Path)
    parser.add_argument("--endpoint")
    args, remaining = parser.parse_known_args()
    if args.package_smoke or args.package_native_smoke:
        from package_check import smoke, native_smoke
        report = args.package_smoke or args.package_native_smoke.with_suffix(".json")
        report.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = smoke(args.endpoint) if args.package_smoke else native_smoke(args.package_native_smoke, args.endpoint)
        except Exception as exc:
            report.write_text(json.dumps({"passed": False, "error_type": type(exc).__name__, "error": str(exc),
                                          "traceback": traceback.format_exc()}, indent=2), encoding="utf-8")
            raise SystemExit(1) from exc
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return
    sys.argv = [sys.argv[0], *remaining]
    importlib.import_module(f"{PACKAGE}.__main__").main()


if __name__ == "__main__":
    main()
