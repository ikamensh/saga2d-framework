"""Wrapped text participates in ordinary retained UI flow and input."""

import math

import pytest

from saga2d import Anchor, Button, Column, Label, Scene, TextStyle


def test_wrapped_label_keeps_text_inside_its_column_and_places_the_next_button(game, backend):
    """A caller supplies a width; measured lines and flow height need no manual math."""
    description = 'Gather the army at the northern gate before advancing toward the enemy.'

    class Card(Scene):
        def on_enter(self):
            self.description = Label(description, width=180, wrap=True, font_size=17)
            self.button = Button('Continue', on_click=lambda: setattr(self, 'clicked', True))
            self.clicked = False
            self.ui.add(Column(self.description, self.button, spacing=9, anchor=Anchor.TOP_LEFT, margin=20))

    scene = Card()
    game.push(scene)
    game.tick(1 / 60)
    lines = [line for line in backend.texts if line['text'] != 'Continue']
    assert len(lines) > 1
    assert ' '.join(line['text'] for line in lines) == description
    x, y, width, height = scene.description.bounds
    for line in lines:
        assert line['x'] == x and line['anchor_y'] == 'top'
        assert backend.measure_text(line['text'], line['font_size'], line['font'])[0] <= width
    line_height = backend.measure_text('Mg', 17, game.theme.font)[1]
    assert y + height >= lines[-1]['y'] + line_height
    assert scene.button.bounds[1] == y + height + 9
    bx, by, bw, bh = scene.button.bounds
    backend.inject_click(bx + bw / 2, by + bh / 2)
    game.tick(1 / 60)
    assert scene.clicked


@pytest.mark.parametrize('covered', [False, True])
def test_reactive_wrapping_reflows_in_the_same_frame_even_beneath_a_paused_overlay(game, backend, covered):
    """Displayed text and following controls agree without a second settling tick."""
    class Card(Scene):
        def on_enter(self):
            self.message = 'Ready'
            self.label = Label(lambda: self.message, width=150, wrap=True)
            self.next = Button('Next')
            self.ui.add(Column(self.label, self.next, spacing=10, anchor=Anchor.TOP_LEFT))

    class Overlay(Scene):
        transparent = True

    scene = Card()
    game.push(scene)
    game.tick(1 / 60)
    old_height = scene.label.bounds[3]
    if covered:
        game.push(Overlay())
    scene.message = 'Gather the army at the northern gate before advancing toward the enemy.'
    game.tick(1 / 60)
    x, y, width, height = scene.label.bounds
    assert height > old_height
    assert scene.next.bounds[1] == y + height + 10
    lines = [line for line in backend.texts if line['text'] != 'Next']
    assert ' '.join(line['text'] for line in lines) == scene.message
    assert lines[-1]['y'] + backend.measure_text('Mg', game.theme.font_size, game.theme.font)[1] <= y + height
    scene.message = 'Ready'
    game.tick(1 / 60)
    assert scene.label.bounds[3] == old_height


def test_named_font_change_reflows_before_the_next_input_in_the_same_batch(game, backend):
    """A settings callback cannot leave a following button clickable at its old position."""
    game.theme.set_text_style('description', TextStyle(12, (1, 2, 3, 255), 'First font'))

    class Card(Scene):
        controls = {'f': 'larger'}

        def on_enter(self):
            self.clicks = 0
            self.label = Label('Gather the army before advancing toward the enemy.', width=180,
                               wrap=True, text_style='description')
            self.next = Button('Next', on_click=self.advance)
            self.ui.add(Column(self.label, self.next, spacing=10, anchor=Anchor.TOP_LEFT))

        def larger(self):
            self.game.theme.set_text_style('description', TextStyle(26, (4, 5, 6, 255), 'Second font'))

        def advance(self):
            self.clicks += 1

    scene = Card()
    game.push(scene)
    game.tick(1 / 60)
    bx, by, bw, bh = scene.next.bounds
    backend.inject_key('f')
    backend.inject_click(bx + bw / 2, by + bh / 2)
    game.tick(1 / 60)
    assert scene.clicks == 0
    assert scene.next.bounds[1] > by + bh
    lines = [line for line in backend.texts if line['text'] != 'Next']
    assert all(line['font'] == 'Second font' and line['font_size'] == 26 for line in lines)
    assert all(line['color'] == (4, 5, 6, 255) for line in lines)
    bx, by, bw, bh = scene.next.bounds
    backend.inject_click(bx + bw / 2, by + bh / 2)
    game.tick(1 / 60)
    assert scene.clicks == 1


@pytest.mark.parametrize('align,fraction', [('left', 0), ('center', 0.5), ('right', 1)])
def test_wrapped_lines_align_inside_explicit_width_and_height(game, backend, align, fraction):
    """Every line shares the requested horizontal anchor; the block centers in a fixed height."""
    class Card(Scene):
        def on_enter(self):
            self.label = self.ui.add(Label('One line\n\nLast', width=200, height=160, wrap=True,
                                            font_size=14, align=align, anchor=Anchor.CENTER))

    scene = Card()
    game.push(scene)
    game.tick(1 / 60)
    x, y, width, height = scene.label.bounds
    first, last = backend.texts
    line_height = backend.measure_text('Mg', 14, game.theme.font)[1]
    text_height = line_height * (1 + 2 * 1.4)
    assert [line['text'] for line in backend.texts] == ['One line', 'Last']
    assert all(line['anchor_x'] == align and line['x'] == x + width * fraction for line in backend.texts)
    assert first['y'] == pytest.approx(y + (height - text_height) / 2)
    assert last['y'] == pytest.approx(first['y'] + line_height * 2 * 1.4)


def test_long_tokens_and_empty_text_keep_flow_without_truncation_or_phantom_height(game, backend):
    """Long resource names fit; clearing an optional description removes its line space."""
    token = 'OneVeryLongUnbrokenResourceName'

    class Card(Scene):
        def on_enter(self):
            self.label = Label(token, width=65, wrap=True, font_size=15)
            self.next = Button('Next')
            self.ui.add(Column(self.label, self.next, spacing=8, anchor=Anchor.TOP_LEFT))

    scene = Card()
    game.push(scene)
    game.tick(1 / 60)
    lines = [line for line in backend.texts if line['text'] != 'Next']
    assert ''.join(line['text'] for line in lines) == token
    assert all(backend.measure_text(line['text'], 15, line['font'])[0] <= 65 for line in lines)
    scene.label.text = ''
    game.tick(1 / 60)
    assert scene.label.bounds[3] == 0
    assert scene.next.bounds[1] == scene.label.bounds[1] + 8
    assert [line['text'] for line in backend.texts] == ['Next']


@pytest.mark.parametrize('width', [None, 0, -1, math.inf, math.nan])
def test_wrapping_requires_an_explicit_usable_width(width):
    """A flow cannot infer a wrapping width from its own content-dependent size."""
    with pytest.raises(ValueError):
        Label('Description', width=width, wrap=True)


def test_impossible_glyph_width_raises_before_drawing(game, backend):
    """Impossible fits remain explicit instead of overflowing the allotted column."""
    class Card(Scene):
        def on_enter(self):
            self.ui.add(Label('Wide', width=1, wrap=True))

    game.push(Card())
    with pytest.raises(ValueError, match='cannot fit character'):
        game.tick(1 / 60)
    assert backend.texts == []


def test_default_label_keeps_its_single_draw_and_existing_center_alignment(game, backend):
    """Existing width means an alignment box; opting out never wraps or clips text."""
    text = 'This intentionally exceeds its old fixed width'

    class Card(Scene):
        def on_enter(self):
            self.label = self.ui.add(Label(text, width=70, align='right', anchor=Anchor.TOP_LEFT))

    scene = Card()
    game.push(scene)
    game.tick(1 / 60)
    x, y, width, height = scene.label.bounds
    assert len(backend.texts) == 1
    line = backend.texts[0]
    assert line['text'] == text and line['anchor_x'] == 'right' and line['anchor_y'] == 'center'
    assert line['x'] == x + width and line['y'] == y + height // 2
