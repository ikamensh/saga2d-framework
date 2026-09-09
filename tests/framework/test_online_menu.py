"""Public multiplayer entry points use room codes online and retain explicit LAN."""
import argparse
import time

import pytest

from saga2d import Game, MatchMenu, Scene
from saga2d.testing.online import COUNTER_GAMES, running_server, server_fixture

server_url = server_fixture(COUNTER_GAMES)


def test_online_menu_needs_only_a_room_code_and_reports_missing_input(tmp_path):
    """The default join path asks friends for a code without requiring an IP address."""
    game = Game('online menu', backend='mock', resolution=(1280, 800), save_dir=tmp_path / 'saves')
    try:
        game.push(MatchMenu('Test multiplayer', 'counter-v1', None, None))
        game.tick(.03)
        text = '\n'.join(item['text'] for item in game.backend.texts)
        assert 'Online' in text
        assert 'Host address' not in text
        assert 'Room code' in text
        game.backend.inject_key('return')
        game.tick(.03)
        assert 'Enter a room code' in game.scene.message
        for key in ('a', 'b', 'c', '1', '2', '3'):
            game.backend.inject_key(key)
            game.tick(.03)
        text = '\n'.join(item['text'] for item in game.backend.texts)
        assert 'ABC123' in text
    finally:
        game.close()


def test_online_creator_waits_for_partner_and_can_rejoin_after_app_restart(server_url, tmp_path, monkeypatch):
    """Creating a room never starts local authority; a private saved seat survives restart."""
    from saga2d.multiplayer_ui import MatchLobby
    from saga2d.online import OnlineClient

    class RemoteScene(Scene):
        def __init__(self, session, match):
            assert match is None, 'Online creators must use the remote authority'
            self.session = session

        def update(self, dt):
            self.session.poll()

        def on_close(self):
            self.session.close()

    def local_match():
        raise AssertionError('Online room creation must not construct a local match')

    def new_menu():
        return MatchMenu('Counter online', 'counter-v1', local_match, RemoteScene,
                         create_options=lambda: {'seed': 41})

    def click_text(text):
        button = next(b for b in game.scene.ui.walk() if str(getattr(b, 'text', '')).startswith(text))
        x, y, w, h = button.bounds
        game.backend.inject_click(x + w / 2, y + h / 2)
        game.tick(.03)

    def wait(until):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            game.tick(.03)
            if guest is not None:
                guest.poll()
            if until():
                return
            time.sleep(.01)
        raise AssertionError('Online menu did not reach the expected state')

    monkeypatch.setenv('SAGA2D_SERVER_URL', server_url)
    game = Game('online menu', backend='mock', resolution=(1280, 800), save_dir=tmp_path / 'saves')
    guest = None
    try:
        game.push(new_menu())
        game.tick(.03)
        assert not game.scene.last_room['resume_token']
        click_text('Create room')
        assert isinstance(game.scene, MatchLobby)
        wait(lambda: bool(game.scene.session.resume_token))
        lobby = game.scene
        room = lobby.session.room
        assert not lobby.session.ready
        assert any(f'Room code: {room}' in t['text'] for t in game.backend.texts)
        click_text('Copy room code')
        assert game.backend.get_clipboard_text() == room
        assert any('Copied' in t['text'] for t in game.backend.texts)
        click_text('Copy invite link')
        site = server_url.replace('ws://', 'http://').removesuffix('/play')
        assert game.backend.get_clipboard_text() == f'{site}/join/counter-v1/{room}'
        assert lobby.session.resume_token not in game.backend.get_clipboard_text()
        assert any('kept for 15 minutes' in t['text'] for t in game.backend.texts)
        click_text('Cancel')
        assert isinstance(game.scene, MatchMenu)
        assert any('Rejoin last room' in t['text'] for t in game.backend.texts)
        # A mistyped server override must leave the real saved seat recoverable.
        from saga2d import add_match_arguments, match_from_arguments
        parser = argparse.ArgumentParser()
        add_match_arguments(parser)
        with running_server(COUNTER_GAMES) as (other_server, _):
            args = parser.parse_args(['--online-resume', '--server', other_server])
            failed = match_from_arguments(args, parser, title='Counter', game_id='counter-v1',
                                          create_match=local_match, create_scene=RemoteScene, game=game)
            game.push(failed)
            wait(lambda: failed.session.closed)
            assert 'Room not found' in failed.session.error
            game.pop()
            game.tick(.03)
        click_text('Rejoin last room')
        wait(lambda: game.scene.session.state is not None)
        guest = OnlineClient('counter-v1', endpoint=server_url, room=room)
        wait(lambda: isinstance(game.scene, RemoteScene) and guest.ready)
        assert game.scene.session.player == 0
        assert game.scene.session.state['seed'] == 41
        game.scene.session.submit({'action': 'add'}, revision=game.scene.session.revision)
        wait(lambda: guest.state['counts'][0] == 1)
        game.close()
        game = Game('online menu', backend='mock', resolution=(1280, 800), save_dir=tmp_path / 'saves')
        game.push(new_menu())
        game.tick(.03)
        wait(lambda: not guest.ready)
        click_text('Rejoin last room')
        wait(lambda: isinstance(game.scene, RemoteScene) and guest.ready)
        assert game.scene.session.player == 0
        assert game.scene.session.room == room
        assert game.scene.session.state['counts'][0] == 1
    finally:
        game.close()
        if guest is not None:
            guest.close()


@pytest.mark.parametrize('shortcut', [None, 'ctrl', 'meta'])
def test_online_code_paste_replaces_input_and_rejects_unrelated_clipboard(tmp_path, shortcut):
    """Friends can paste a copied code; unrelated text never becomes a partial room code."""
    game = Game('paste room', backend='mock', resolution=(1280, 800), save_dir=tmp_path / 'saves')
    try:
        game.push(MatchMenu('Warband multiplayer', 'warband-v1', None, None))
        game.tick(.03)
        game.backend.inject_key('z')
        game.tick(.03)
        game.backend.set_clipboard_text('  ab12Cd34ef56\n')

        def paste():
            if shortcut:
                game.backend.inject_key('v', **{shortcut: True})
            else:
                button = next(b for b in game.scene.ui.walk() if getattr(b, 'text', '') == 'Paste code')
                x, y, w, h = button.bounds
                game.backend.inject_click(x + w / 2, y + h / 2)
            game.tick(.03)

        paste()
        assert game.scene.fields[2] == 'AB12CD34EF56'
        for invalid in ('', 'room: ab12cd34ef56', 'abcdefghijklmnop', 'åbc123'):
            game.backend.set_clipboard_text(invalid)
            paste()
            assert game.scene.fields[2] == 'AB12CD34EF56'
            assert 'Copy just the room code' in game.scene.message
    finally:
        game.close()


def test_installed_games_offer_the_download_page_when_a_newer_release_is_published(tmp_path, monkeypatch):
    """The menu names the update and opens its page; source checkouts show nothing."""
    from tests.framework.test_release import CATALOG, catalog_site

    opened = []
    monkeypatch.setattr('saga2d.multiplayer_ui.open_page', opened.append)
    with catalog_site(CATALOG) as url:
        monkeypatch.setenv('SAGA2D_CATALOG_URL', url)
        monkeypatch.setattr('saga2d.release.build_info', lambda: {'version': '0.1.0'})
        game = Game('update menu', backend='mock', resolution=(1280, 800), save_dir=tmp_path / 'saves')
        try:
            game.push(MatchMenu('Warband multiplayer', 'warband-v1', None, None))
            deadline = time.monotonic() + 10
            while game.scene.update_check.status in ('checking',) and time.monotonic() < deadline:
                game.tick(.03)
            game.tick(.03)
            text = '\n'.join(item['text'] for item in game.backend.texts)
            assert 'Update available: Warband 0.2.0' in text
            button = next(b for b in game.scene.ui.walk() if getattr(b, 'text', '') == 'Open download page')
            x, y, w, h = button.bounds
            game.backend.inject_click(x + w / 2, y + h / 2)
            game.tick(.03)
            assert opened == ['https://games.example.test/warband/']
        finally:
            game.close()
        monkeypatch.setattr('saga2d.release.build_info', lambda: None)
        game = Game('source menu', backend='mock', resolution=(1280, 800), save_dir=tmp_path / 'source-saves')
        try:
            game.push(MatchMenu('Warband multiplayer', 'warband-v1', None, None))
            game.tick(.03)
            assert game.scene.update_check.status == 'source'
            assert 'Update available' not in '\n'.join(item['text'] for item in game.backend.texts)
        finally:
            game.close()


def test_incompatible_clients_are_told_to_update_instead_of_retrying(server_url, tmp_path, monkeypatch):
    """A rejected old client sees an update notice and a button to the download site."""
    from saga2d.multiplayer_ui import MatchLobby

    opened = []
    monkeypatch.setattr('saga2d.multiplayer_ui.open_page', opened.append)
    monkeypatch.setattr('saga2d.online.PROTOCOL', 999)
    monkeypatch.setenv('SAGA2D_SERVER_URL', server_url)
    game = Game('old client', backend='mock', resolution=(1280, 800), save_dir=tmp_path / 'saves')
    try:
        game.push(MatchMenu('Counter multiplayer', 'counter-v1', None, None, create_options=dict))
        game.tick(.03)
        game.scene.host()
        deadline = time.monotonic() + 10
        while not game.scene.session.closed and time.monotonic() < deadline:
            game.tick(.03)
        game.tick(.03)
        assert isinstance(game.scene, MatchLobby) and game.scene.session.incompatible
        text = '\n'.join(item['text'] for item in game.backend.texts)
        assert 'Update required' in text and 'Update your game client' in text
        assert 'Copy room code' not in text
        button = next(b for b in game.scene.ui.walk() if getattr(b, 'text', '') == 'Open download page')
        x, y, w, h = button.bounds
        game.backend.inject_click(x + w / 2, y + h / 2)
        game.tick(.03)
        assert opened == [server_url.replace('ws://', 'http://').removesuffix('/play') + '/']
    finally:
        game.close()
