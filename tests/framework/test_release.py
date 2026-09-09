"""Installed games learn about newer releases from the catalog beside the online server."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

import pytest

from saga2d.release import UpdateCheck, catalog_entry, catalog_url, home_page

CATALOG = {
    'catalog_version': 1, 'site': 'https://games.example.test',
    'server': {'endpoint': 'wss://games.example.test/play', 'protocol': 1},
    'games': {
        'warband': {'name': 'Warband', 'game_ids': ['warband-v1'], 'version': '0.2.0', 'packages': []},
        'shardbound': {'name': 'Shardbound', 'game_ids': ['shardbound-v1', 'shardbound-pvp-v1'],
                       'version': None, 'packages': []},
    },
}


@contextmanager
def catalog_site(catalog, *, status=200):
    """Serve one catalog document over real HTTP on a loopback port."""
    body = json.dumps(catalog).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status if self.path == '/releases.json' else 404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/releases.json'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def settle(check):
    deadline = time.monotonic() + 10
    while check.poll() == 'checking' and time.monotonic() < deadline:
        time.sleep(.02)
    return check.status


def test_catalog_lives_beside_the_online_server_unless_overridden(monkeypatch):
    monkeypatch.delenv('SAGA2D_CATALOG_URL', raising=False)
    monkeypatch.setenv('SAGA2D_SERVER_URL', 'wss://games.tachyon-ai.eu/play')
    assert catalog_url() == 'https://games.tachyon-ai.eu/releases.json'
    assert home_page() == 'https://games.tachyon-ai.eu/'
    monkeypatch.setenv('SAGA2D_SERVER_URL', 'ws://127.0.0.1:8765/play')
    assert catalog_url() == 'http://127.0.0.1:8765/releases.json'
    monkeypatch.setenv('SAGA2D_CATALOG_URL', 'http://127.0.0.1:9/releases.json')
    assert catalog_url() == 'http://127.0.0.1:9/releases.json'


def test_catalog_entries_are_found_by_online_game_id():
    """Both Shardbound modes share one download page; unknown ids are an error, not a guess."""
    assert catalog_entry(CATALOG, 'shardbound-pvp-v1') == {
        'slug': 'shardbound', 'name': 'Shardbound', 'version': None,
        'page': 'https://games.example.test/shardbound/'}
    with pytest.raises(ValueError, match='tribes-v1'):
        catalog_entry(CATALOG, 'tribes-v1')
    with pytest.raises(ValueError, match='version'):
        catalog_entry({**CATALOG, 'catalog_version': 2}, 'warband-v1')


def test_installed_builds_compare_with_the_published_version():
    with catalog_site(CATALOG) as url:
        outdated = UpdateCheck('warband-v1', info={'version': '0.1.0'}, url=url)
        assert outdated.status == 'checking' and outdated.page == url.removesuffix('releases.json')
        assert settle(outdated) == 'update'
        assert outdated.latest['version'] == '0.2.0'
        assert outdated.page == 'https://games.example.test/warband/'
        current = UpdateCheck('warband-v1', info={'version': '0.2.0'}, url=url)
        assert settle(current) == 'current'
        unpublished = UpdateCheck('shardbound-v1', info={'version': '0.1.0'}, url=url)
        assert settle(unpublished) == 'unavailable' and 'No published release' in unpublished.detail


def test_source_checkouts_and_unreachable_sites_never_block_play(monkeypatch):
    monkeypatch.setattr('sys.frozen', False, raising=False)
    source = UpdateCheck('warband-v1', url='http://127.0.0.1:9/releases.json')
    assert source.status == 'source' and source.poll() == 'source'
    with catalog_site(CATALOG, status=500) as url:
        broken = UpdateCheck('warband-v1', info={'version': '0.1.0'}, url=url)
        assert settle(broken) == 'unavailable' and 'HTTPError' in broken.detail
    offline = UpdateCheck('warband-v1', info={'version': '0.1.0'}, url='http://127.0.0.1:9/releases.json')
    assert settle(offline) == 'unavailable'
    assert offline.page == 'http://127.0.0.1:9/'
