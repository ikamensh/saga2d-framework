"""Measure prospective UI using its real rendering context without activating it."""

import pytest

from saga2d import Button, Column, Label, Scene, TextStyle


def test_measuring_a_card_matches_rendered_size_without_displaying_or_activating_it(game, backend):
    """A game can budget a complete card before giving it a place or a shortcut."""
    clicks = []
    scene = Scene()
    game.push(scene)
    game.theme.set_text_style('description', TextStyle(23, (255, 255, 255, 255), 'Georgia'))
    card = Column(Label('Read the complete description before choosing a destination.',
                        width=180, wrap=True, text_style='description'),
                  Button('Choose', shortcut='C', on_click=lambda: clicks.append('chosen')), spacing=12)
    size = scene.measure(card)
    assert card.parent is None and scene.ui.children == []
    backend.inject_key('c')
    game.tick(1 / 60)
    assert clicks == [] and backend.texts == []
    scene.ui.add(card)
    game.tick(1 / 60)
    assert card.bounds[2:] == size
    backend.inject_key('c')
    game.tick(1 / 60)
    assert clicks == ['chosen']


def test_measurement_cannot_steal_an_owned_tree_or_detach_its_theme(game, backend):
    """Measuring another scene's live control must leave its owner operational."""
    scene, overlay = Scene(), Scene()
    game.push(scene)
    game.theme.set_text_style('description', TextStyle(25, (255, 255, 255, 255)))
    label = Label('Owned description', text_style='description')
    card = scene.ui.add(Column(label))
    game.tick(1 / 60)
    size = card.get_preferred_size()
    game.push(overlay)
    with pytest.raises(ValueError, match='unattached'):
        overlay.measure(card)
    game.pop()
    game.tick(1 / 60)
    assert card.parent is scene.ui and card.get_preferred_size() == size
    assert next(row for row in backend.texts if row['text'] == 'Owned description')['font_size'] == 25


def test_measurement_uses_current_reactive_text_and_theme_and_cleans_up_after_failure(game):
    """Preview can be retried after a caller error and remeasured after content changes."""
    scene = Scene()
    game.push(scene)
    words = ['Short']

    def description():
        return words[0]

    card = Column(Label(description, width=180, wrap=True, text_style='description'))
    game.theme.set_text_style('description', TextStyle(13, (255, 255, 255, 255)))
    short = scene.measure(card)
    words.clear()
    with pytest.raises(IndexError):
        scene.measure(card)
    words.append('A complete description that changes after the preview was first measured.')
    game.theme.set_text_style('description', TextStyle(23, (255, 255, 255, 255)))
    long = scene.measure(card)
    assert long[1] > short[1]
    scene.ui.add(card)
    game.tick(1 / 60)
    assert card.bounds[2:] == long
