"""Run with ``python -m saga2d.server --games <module:GAMES ...>`` behind a TLS proxy.

Each game package names its hosted versions, for example
``python -m saga2d.server --games warband.multiplayer:ONLINE``.
"""
import argparse
import asyncio
import logging
import signal
import sys

from saga2d.server import load_games, run


def main():
    parser = argparse.ArgumentParser(description='Saga2D authoritative online room server')
    parser.add_argument('--games', nargs='+', required=True, metavar='MODULE:ATTRIBUTE',
                        help='game registries to host, each a {game id: GameSpec} mapping')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--state-dir', help='Private directory for persistent room checkpoints')
    parser.add_argument('--room-ttl', type=float, default=900, help='Disconnected match retention in seconds')
    parser.add_argument('--campaign-ttl', type=float, default=7 * 86400,
                        help='Campaign seat retention in seconds; campaigns leave memory after --room-ttl')
    parser.add_argument('--max-rooms', type=int, default=64)
    parser.add_argument('--max-connections', type=int, default=128)
    parser.add_argument('--trusted-proxy', action='store_true',
                        help='Trust X-Forwarded-For from a loopback reverse proxy only')
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    games = load_games(args.games)

    async def start():
        # Windows event loops don't support add_signal_handler; asyncio.run
        # already cancels the main task on Ctrl-C there. Unix services also
        # need graceful SIGTERM cancellation to flush their room checkpoints.
        if sys.platform != 'win32':
            task = asyncio.current_task()
            for signum in (signal.SIGTERM, signal.SIGINT):
                asyncio.get_running_loop().add_signal_handler(signum, task.cancel)
        await run(args.host, args.port, games=games, state_dir=args.state_dir, room_ttl=args.room_ttl,
                  campaign_ttl=args.campaign_ttl, max_rooms=args.max_rooms,
                  max_connections=args.max_connections, trusted_proxy=args.trusted_proxy)

    try:
        asyncio.run(start())
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass


if __name__ == '__main__':
    main()
