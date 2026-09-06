"""Local screen compositions stay ordered without escaping their scene."""

import pytest
from PIL import Image

from saga2d import Anchor, Button, Label, Panel, RenderLayer, Scene, Style


def test_a_feedback_panel_covers_earlier_text_through_ordinary_draw_helpers(game, backend):
    """A game wrapper can draw a pill and paragraph above an existing health label."""
    class Feedback(Scene):
        def pill(self):
            self.draw_rect(10, 20, 120, 50, (20, 30, 40, 255))
            self.draw_paragraph('Restored 8', 15, 25, 110)

        def draw(self):
            self.draw_text('Health 12/20', 10, 20)
            with self.screen_layer(1):
                self.pill()
            self.draw_text('Base after scope', 10, 90)

    game.push(Feedback())
    game.tick(1 / 60)
    text = {record['text']: record['order'] for record in backend.texts}
    assert text['Health 12/20'] == text['Base after scope']
    assert text['Health 12/20'] < backend.rects[0]['order'] == text['Restored 8']


def test_local_feedback_stays_below_ui_and_the_next_scene(game, backend):
    """Even the highest local layer cannot cover a control or escape a modal overlay."""
    class Base(Scene):
        def on_enter(self):
            self.ui.add(Label('Base control'))

        def draw(self):
            with self.screen_layer(999):
                self.draw_text('Feedback', 0, 0)

    class Overlay(Scene):
        transparent = True

        def on_enter(self):
            self.ui.add(Label('Overlay control'))

        def draw(self):
            self.draw_rect(0, 0, 100, 100, (20, 30, 40, 255))

    game.push(Base())
    game.push(Overlay())
    game.tick(1 / 60)
    text = {record['text']: record['order'] for record in backend.texts}
    assert text['Feedback'] < text['Base control'] < backend.rects[0]['order'] < text['Overlay control']


def test_overlapping_ui_paints_the_same_frontmost_control_that_receives_clicks(game, backend):
    """Later siblings cover earlier text, including after hiding and tree reordering."""
    pressed = []
    red, green, blue = (180, 20, 30, 255), (20, 180, 30, 255), (20, 30, 180, 255)

    class Controls(Scene):
        def on_enter(self):
            self.back = self.ui.add(Button('BACK', on_click=lambda: pressed.append('back'),
                                          width=100, height=50, anchor=Anchor.TOP_LEFT,
                                          style=Style(background_color=red, hover_color=red, radius=0, border_width=0)))
            self.front = self.ui.add(Panel(width=100, height=50, anchor=Anchor.TOP_LEFT,
                                           style=Style(background_color=green, radius=0, padding=0, border_width=0)))
            self.front.add(Button('FRONT', on_click=lambda: pressed.append('front'), width=100, height=50,
                                  style=Style(background_color=blue, radius=0, border_width=0)))

    scene = Controls()
    game.push(scene)
    game.tick(1 / 60)
    text = {record['text']: record['order'] for record in backend.texts}
    shapes = {record['color']: record['order'] for record in backend.rects}
    assert text['BACK'] < shapes[green] < shapes[blue] == text['FRONT']

    def click():
        backend.inject_click(30, 25)
        backend.inject_release(30, 25)
        game.tick(1 / 60)

    click()
    assert pressed == ['front']
    scene.front.visible = False
    click()
    assert pressed == ['front', 'back'] and not any(record['text'] == 'FRONT' for record in backend.texts)
    scene.front.visible = True
    scene.ui.add(scene.back)
    click()
    assert pressed == ['front', 'back', 'back']
    front_text = next(record for record in backend.texts if record['text'] == 'FRONT')
    back_shape = next(record for record in backend.rects if record['color'] == red)
    assert front_text['order'] < back_shape['order']


def test_nested_scopes_restore_after_errors_and_leave_world_layers_unchanged(game, backend):
    """Every immediate helper shares the scope; nesting never offsets world geometry."""
    game.assets.image_from_pil('tile', Image.new('RGBA', (8, 8), 'white'))
    color = (80, 120, 160, 255)

    class Composition(Scene):
        def draw(self):
            self.draw_rect(0, 0, 20, 20, color, space='world', layer=RenderLayer.EFFECTS)
            with self.screen_layer(2):
                self.draw_rect(0, 0, 20, 20, color, space='world', layer=RenderLayer.EFFECTS)
                self.draw_image('tile', 10, 10, 20, 20)
                self.draw_circle(20, 20, 10, color)
                self.draw_line(0, 0, 20, 20, color)
                self.draw_polygon([(0, 0), (20, 0), (0, 20)], color)
                with self.screen_layer(1):
                    self.draw_text('Nested lower', 0, 0)
                try:
                    with self.screen_layer(3):
                        raise RuntimeError('Drawing failed')
                except RuntimeError:
                    pass
                self.draw_text('Outer restored', 0, 0)
            self.draw_text('Base restored', 0, 0)

    game.push(Composition())
    for _ in range(2):
        game.tick(1 / 60)
        text = {record['text']: record['order'] for record in backend.texts}
        assert text['Base restored'] < text['Nested lower'] < text['Outer restored']
        assert all(record['order'] == text['Outer restored']
                   for record in backend.images + backend.circles + backend.lines + backend.polygons)
        assert backend.rects[0]['order'] == backend.rects[1]['order'] < text['Base restored']


@pytest.mark.parametrize('invalid', [-1, 1000, True, False, 1.0, float('nan'), float('inf'), '1', None])
def test_invalid_screen_layers_fail_without_affecting_following_drawing(game, backend, invalid):
    """Invalid values cannot escape their scene or silently alter a later frame."""
    class InvalidLayer(Scene):
        def draw(self):
            self.draw_text('Before', 0, 0)
            with pytest.raises(ValueError, match='Screen layer'):
                with self.screen_layer(invalid):
                    pytest.fail('An invalid layer entered its body')
            self.draw_text('After', 0, 0)

    game.push(InvalidLayer())
    game.tick(1 / 60)
    assert backend.texts[0]['order'] == backend.texts[1]['order']
