"""Measured paragraph layout through ordinary scene rendering and backend output."""

import math

import pytest

from saga2d import RenderLayer, Scene, TextStyle, Theme


def test_paragraph_wraps_to_measured_width_and_returns_its_occupied_height(game, backend):
    """A following draw can use the returned height without overlapping text."""
    text = 'Build your stronghold and protect the wounded soldiers in your army.'
    width = backend.measure_text('Build your stronghold', 15, 'Verdana')[0]

    class Paragraph(Scene):
        def draw(self):
            self.height = self.draw_paragraph(text, 25, 40, width, font_size=15, font='Verdana')
            self.draw_text('Following content', 25, 40 + self.height, anchor_y='top')

    scene = Paragraph()
    game.push(scene)
    game.tick(1 / 60)
    lines, following = backend.texts[:-1], backend.texts[-1]
    assert len(lines) > 1
    assert ' '.join(line['text'] for line in lines) == text
    line_height = backend.measure_text('Mg', 15, 'Verdana')[1]
    for index, line in enumerate(lines):
        assert backend.measure_text(line['text'], line['font_size'], line['font'])[0] <= width
        assert line['x'] == 25
        assert line['y'] == pytest.approx(40 + index * line_height * 1.4)
        assert line['anchor_x'] == 'left' and line['anchor_y'] == 'top'
    assert following['y'] == pytest.approx(lines[-1]['y'] + line_height)
    assert scene.height == pytest.approx(line_height * (1 + (len(lines) - 1) * 1.4))


def test_explicit_newlines_and_blank_lines_keep_their_vertical_space(game, backend):
    """Authored paragraph breaks and empty lines remain useful layout controls."""
    class Paragraph(Scene):
        def draw(self):
            self.height = self.draw_paragraph('First line\n\nSecond line\n', 10, 20, 300,
                                              font_size=10, line_spacing=1.5)

    scene = Paragraph()
    game.push(scene)
    game.tick(1 / 60)
    lines = [line for line in backend.texts if line['text']]
    height = backend.measure_text('Mg', 10, game.theme.font)[1]
    assert [line['text'] for line in lines] == ['First line', 'Second line']
    assert lines[1]['y'] - lines[0]['y'] == pytest.approx(2 * height * 1.5)
    assert scene.height == pytest.approx(height * (1 + 3 * 1.5))


def test_overlong_words_split_without_losing_characters_or_exceeding_width(game, backend):
    """A long name or URL stays in its column without silently truncating it."""
    token = 'TheVeryLongUnbrokenNameOfAnAncientStronghold'
    width = backend.measure_text('Ancient', 13, game.theme.font)[0]

    class Paragraph(Scene):
        def draw(self):
            self.draw_paragraph(token, 5, 10, width, font_size=13)

    game.push(Paragraph())
    game.tick(1 / 60)
    assert ''.join(line['text'] for line in backend.texts) == token
    assert all(backend.measure_text(line['text'], line['font_size'], line['font'])[0] <= width
               for line in backend.texts)


@pytest.mark.parametrize('options', [{'width': 0}, {'width': -10}, {'width': math.nan}, {'width': math.inf},
                                   {'line_spacing': 0}, {'line_spacing': -1}, {'line_spacing': math.nan},
                                   {'line_spacing': math.inf}])
def test_invalid_paragraph_dimensions_raise_before_drawing(game, backend, options):
    """Impossible layout dimensions fail clearly without emitting partial text."""
    class Paragraph(Scene):
        def draw(self):
            self.draw_paragraph('Bounded text', 0, 0, **{'width': 100, **options})

    game.push(Paragraph())
    with pytest.raises(ValueError):
        game.tick(1 / 60)
    assert backend.texts == []


@pytest.mark.parametrize('options', [{}, {'style': 'custom'},
                                   {'style': TextStyle(17, (3, 4, 5, 255))},
                                   {'style': 'custom', 'font_size': 11, 'font': 'Override', 'color': (1, 2, 3, 255)}])
def test_paragraph_uses_exactly_the_same_text_style_as_draw_text(game, backend, options):
    """Wrapping and rendering must agree on theme defaults and explicit overrides."""
    game.theme = Theme(font='Theme font', font_size=19,
                       text_styles={'custom': TextStyle(23, (40, 50, 60, 255), 'Named font')})

    class Paragraph(Scene):
        def draw(self):
            self.draw_text('A short line', 20, 30, space='world', layer=RenderLayer.EFFECTS, **options)
            self.draw_paragraph('A short line', 20, 30, 500, space='world', layer=RenderLayer.EFFECTS, **options)

    game.push(Paragraph())
    game.tick(1 / 60)
    text, paragraph = backend.texts
    assert paragraph == {**text, 'anchor_y': 'top'}


def test_empty_paragraph_draws_nothing_and_consumes_no_height(game, backend):
    """Optional descriptions can be empty without reserving a phantom line."""
    class Paragraph(Scene):
        def draw(self):
            self.height = self.draw_paragraph('', 0, 0, 100)

    scene = Paragraph()
    game.push(scene)
    game.tick(1 / 60)
    assert scene.height == 0
    assert backend.texts == []


def test_a_character_wider_than_the_column_fails_without_partial_draws(game, backend):
    """The renderer reports an impossible fit instead of overflowing its column."""
    class Paragraph(Scene):
        def draw(self):
            self.draw_paragraph('W', 0, 0, 1, font_size=20)

    game.push(Paragraph())
    with pytest.raises(ValueError, match='cannot fit character'):
        game.tick(1 / 60)
    assert backend.texts == []
