"""Installed build identity and update lookups shared by the packaged games.

Frozen applications carry ``release/build-info.json``; a source checkout has no
release identity and never receives update notices. The release catalog is
published beside the online server, so both share one origin.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from saga2d.online import server_endpoint

CATALOG_VERSION = 1


def build_info():
    """The frozen application's recorded identity, or None for a source checkout."""
    if not getattr(sys, 'frozen', False):
        return None
    return json.loads((Path(sys._MEIPASS) / 'release' / 'build-info.json').read_text(encoding='utf-8'))


def catalog_url():
    """``SAGA2D_CATALOG_URL`` or ``/releases.json`` on the online server's origin."""
    explicit = os.environ.get('SAGA2D_CATALOG_URL')
    if explicit:
        return explicit
    parsed = urlsplit(server_endpoint())
    return urlunsplit(('https' if parsed.scheme == 'wss' else 'http', parsed.netloc, '/releases.json', '', ''))


def home_page(url=None):
    """The website root that lists every game's download page."""
    parsed = urlsplit(url or catalog_url())
    return urlunsplit((parsed.scheme, parsed.netloc, '/', '', ''))


def catalog_entry(catalog, game_id):
    """The catalog game whose online ids include ``game_id``: name, version and page."""
    if catalog.get('catalog_version') != CATALOG_VERSION:
        raise ValueError('Unsupported release catalog version.')
    for slug, game in catalog['games'].items():
        if game_id in game['game_ids']:
            return {'slug': slug, 'name': game['name'], 'version': game['version'],
                    'page': catalog['site'].rstrip('/') + '/' + slug + '/'}
    raise ValueError(f'The release catalog lists no game for {game_id}.')


class UpdateCheck:
    """Compare the running build with the published catalog on a worker thread.

    ``status`` is ``source`` (no installed identity), ``checking``, ``current``,
    ``update`` or ``unavailable``; ``poll`` advances it. ``page`` is the best
    known download page: the game's page once the catalog is read, otherwise
    the site's home page. A failed lookup is reported, never raised: online
    play must not depend on the website.
    """

    def __init__(self, game_id, *, info=None, url=None):
        self.game_id = game_id
        self.info = build_info() if info is None else info
        self.url = url or catalog_url()
        self.page = home_page(self.url)
        self.latest = None
        self.detail = ''
        self._result = None
        self.status = 'source' if self.info is None else 'checking'
        if self.status == 'checking':
            threading.Thread(target=self._fetch, name='saga2d-update-check', daemon=True).start()

    def _fetch(self):
        try:
            with urllib.request.urlopen(self.url, timeout=8) as response:
                catalog = json.loads(response.read().decode('utf-8'))
            latest = catalog_entry(catalog, self.game_id)
            if latest['version'] is None:
                raise ValueError('No published release is listed for this game.')
            status = 'update' if latest['version'] != self.info['version'] else 'current'
            self._result = (status, latest, '')
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self._result = ('unavailable', None, f'{type(exc).__name__}: {exc}')

    def poll(self):
        result, self._result = self._result, None
        if result is not None:
            self.status, self.latest, self.detail = result
            if self.latest is not None:
                self.page = self.latest['page']
        return self.status
