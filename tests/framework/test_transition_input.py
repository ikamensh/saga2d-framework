"""Queued input must not repeat actions across a deferred scene transition."""

import pytest

from saga2d import Anchor, Button, Scene


@pytest.mark.parametrize('input_kind', ['keyboard', 'mouse'])
def test_transition_discards_remaining_batch_without_repeating_or_clicking_through(game, backend, input_kind):
    """A double activation resolves once, stays deferred, and never hits the next scene."""
    calls = []

    class Destination(Scene):
        controls = {'return': 'activate'}

        def on_enter(self):
            self.ui.add(Button('Next action', width=100, height=40, anchor=Anchor.TOP_LEFT,
                               on_click=self.activate))

        def activate(self):
            calls.append('destination')

    destination = Destination()

    class Result(Scene):
        controls = {'return': 'accept'}

        def on_enter(self):
            self.ui.add(Button('Accept result', width=100, height=40, anchor=Anchor.TOP_LEFT,
                               on_click=self.accept))

        def accept(self):
            calls.append('result')
            self.game.replace(destination)
            assert self.game.scene is self, 'transition must stay deferred until the callback returns'

    game.push(Result())
    game.tick(1 / 60)
    if input_kind == 'keyboard':
        backend.inject_key('return')
        backend.inject_key('return')
        backend.inject_key('return', type='key_release')
    else:
        backend.inject_click(20, 20)
        backend.inject_click(20, 20)
    game.tick(1 / 60)
    assert calls == ['result']
    assert game.scene is destination
    assert not game.input.is_pressed('return')
    backend.inject_key('return')
    game.tick(1 / 60)
    assert calls == ['result', 'destination']


def test_skipped_events_still_release_previously_held_keys_and_track_new_held_keys(game, backend):
    """Ending dispatch cannot strand movement keys or erase a real held state."""
    class Overlay(Scene):
        pass

    class World(Scene):
        controls = {'escape': 'pause'}

        def pause(self):
            self.game.push(Overlay())

    game.push(World())
    backend.inject_key('w')
    game.tick(1 / 60)
    assert game.input.is_pressed('w')
    backend.inject_key('escape')
    backend.inject_key('w', type='key_release')
    backend.inject_key('d')
    backend.inject_key('escape', type='key_release')
    game.tick(1 / 60)
    assert isinstance(game.scene, Overlay)
    assert game.input.pressed_keys() == {'d'}
