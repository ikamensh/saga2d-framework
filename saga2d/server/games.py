"""What the room server needs from a hosted game, and helpers for validating its options."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import importlib
from typing import Any

from saga2d.network import CommandError


@dataclass(frozen=True)
class GameSpec:
    """One hosted game version.

    ``create`` validates untrusted creation options and returns a match with
    ``apply(player, command)`` and ``snapshot(player)``; ``checkpoint`` serialises
    the match's complete authority and ``restore`` rebuilds it from that JSON.
    A ``realtime`` match also has ``step()``, which the server calls every 50 ms
    while both seats are present.  A ``campaign`` keeps its seats for the
    server's campaign retention and is suspended to storage between visits.
    """
    create: Callable[[dict], Any]
    checkpoint: Callable[[Any], dict]
    restore: Callable[[dict], Any]
    realtime: bool = False
    campaign: bool = False


def option_keys(options: Any, allowed: set[str]) -> dict:
    """Reject non-objects and undeclared fields before any option is read."""
    if not isinstance(options, dict):
        raise CommandError('Match options must be an object.')
    if options.keys() - allowed:
        raise CommandError('Unknown match option.')
    return options


def option_int(options: dict, name: str, default: int, low: int, high: int) -> int:
    value = options.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise CommandError(f'{name} must be an integer from {low} to {high}.')
    return value


def option_choice(options: dict, name: str, default: str, values: Iterable[str]) -> str:
    value = options.get(name, default)
    if not isinstance(value, str) or value not in set(values):
        raise CommandError(f'Unknown {name}.')
    return value


def option_seed(options: dict, default: int) -> int:
    return option_int(options, 'seed', default, -(2**31), 2**31 - 1)


def load_games(specs: Iterable[str]) -> dict[str, GameSpec]:
    """Import ``module:ATTRIBUTE`` names, each a ``{game id: GameSpec}`` mapping."""
    games: dict[str, GameSpec] = {}
    for spec in specs:
        module_name, _, attribute = spec.partition(':')
        if not module_name or not attribute:
            raise ValueError(f'Name games as module:ATTRIBUTE, not {spec!r}')
        table = getattr(importlib.import_module(module_name), attribute)
        if not isinstance(table, dict):
            raise TypeError(f'{spec} is {type(table).__name__}, not a mapping of game ids to GameSpec')
        for game_id, game in table.items():
            if not isinstance(game, GameSpec):
                raise TypeError(f'{spec} maps {game_id!r} to {type(game).__name__}, not a GameSpec')
            if game_id in games:
                raise ValueError(f'Game {game_id!r} is registered twice')
            games[game_id] = game
    return games
