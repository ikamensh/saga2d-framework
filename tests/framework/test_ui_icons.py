"""Reusable icon controls keep their names, input and hover explanations."""

from PIL import Image as PILImage

from saga2d import Anchor, Button, Game, Label, Panel, Row, Scene


def test_icon_only_button_keeps_reactive_name_shortcut_and_disabled_tooltip(game, backend):
    """A compact image replaces drawn text, while the live name still explains and identifies it."""
    handle = game.assets.image_from_pil('mark', PILImage.new('RGBA', (32, 24), 'gold'))
    state = {'name': 'Save progress', 'clicks': 0}

    class Menu(Scene):
        def on_enter(self):
            self.button = Button(lambda: state['name'], icon='mark', show_text=False,
                                 shortcut='F5', anchor=Anchor.BOTTOM_RIGHT,
                                 on_click=lambda: state.update(clicks=state['clicks'] + 1))
            self.ui.add(self.button)

    menu = Menu()
    game.push(menu)
    game.tick(0)
    assert menu.button.text == 'Save progress'
    assert menu.button.bounds[2] < 120
    assert [draw['image'] for draw in backend.images] == [handle]
    assert [draw['text'] for draw in backend.texts] == ['F5']
    backend.inject_key('f5')
    game.tick(0)
    assert state['clicks'] == 1
    menu.button.enabled = False
    state['name'] = 'Save is unavailable while moving'
    x, y, w, h = menu.button.bounds
    backend.inject_mouse_move(x + w / 2, y + h / 2)
    backend.inject_click(x + w / 2, y + h / 2)
    backend.inject_key('f5')
    game.tick(0)
    assert state['clicks'] == 1
    assert menu.button.text == state['name']
    tooltip = next(draw for draw in backend.texts if 'Save is unavailable' in draw['text'])
    assert tooltip['order'] > max(draw['order'] for draw in backend.images)
    assert all(0 <= rect['x'] <= rect['x'] + rect['width'] <= game.width and
               0 <= rect['y'] <= rect['y'] + rect['height'] <= game.height for rect in backend.rects)
    menu.ui.remove(menu.button)
    game.tick(0)
    assert not backend.images and not backend.texts
    assert game.assets.image('mark') == handle


def test_resource_image_and_value_share_tooltip_without_surviving_cover_or_removal(game, backend):
    """Ordinary cached images fit a row, whose explanation belongs to both children even when disabled."""
    from saga2d import Image

    handle = game.assets.image_from_pil('resource', PILImage.new('RGBA', (64, 32), 'gold'))
    state = {'explanation': 'Currency available for building'}

    class Menu(Scene):
        def on_enter(self):
            self.icon = Image('resource', width=24, height=24)
            self.value = Label('12')
            self.row = Row(self.icon, self.value, enabled=False, anchor=Anchor.BOTTOM_RIGHT, margin=8,
                           tooltip=lambda: state['explanation'])
            self.ui.add(self.row)

    class Modal(Scene):
        transparent = True

        def on_enter(self):
            self.ui.add(Label('Modal owns hover', anchor=Anchor.BOTTOM_RIGHT))

    menu = Menu()
    game.push(menu)
    game.tick(0)
    for child in (menu.icon, menu.value):
        x, y, w, h = child.bounds
        backend.inject_mouse_move(x + w / 2, y + h / 2)
        game.tick(0)
        tip = next(draw for draw in backend.texts if draw['text'] == state['explanation'])
        assert tip['order'] > max(draw['order'] for draw in backend.images)
    image = backend.images[0]
    assert image['image'] == handle and (image['width'], image['height']) == (24, 12)
    order = tip['order']
    cover = Panel(width=menu.row.bounds[2], height=menu.row.bounds[3], anchor=Anchor.BOTTOM_RIGHT, margin=8)
    menu.ui.add(cover)
    game.tick(0)
    assert state['explanation'] not in [draw['text'] for draw in backend.texts]
    menu.ui.remove(cover)
    game.push(Modal())
    game.tick(0)
    assert state['explanation'] not in [draw['text'] for draw in backend.texts]
    assert next(draw['order'] for draw in backend.texts if draw['text'] == 'Modal owns hover') > order
    game.pop()
    state['explanation'] = 'Changed currency explanation'
    game.tick(0)
    assert state['explanation'] in [draw['text'] for draw in backend.texts]
    backend.inject_mouse_move(0, 0)
    game.tick(0)
    assert state['explanation'] not in [draw['text'] for draw in backend.texts]
    menu.ui.clear()
    game.tick(0)
    assert not backend.images and not backend.texts
    assert game.assets.image('resource') == handle


def test_icon_and_text_fit_together_and_keep_pointer_activation(game, backend):
    """Opting into an icon preserves the ordinary text button, including sizing after a label change."""
    game.assets.image_from_pil('mark', PILImage.new('RGBA', (32, 32), 'cyan'))
    calls = []

    class Menu(Scene):
        def on_enter(self):
            self.button = Button('Open', icon='mark', icon_size=32, shortcut='Ctrl+O',
                                 anchor=Anchor.TOP_LEFT, on_click=lambda: calls.append('open'))
            self.ui.add(self.button)

    menu = Menu()
    game.push(menu)
    game.tick(0)
    image = backend.images[0]
    label = next(draw for draw in backend.texts if draw['text'] == 'Open')
    keycap = next(draw for draw in backend.texts if draw['text'] == 'Ctrl+O')
    assert image['width'] == image['height'] == 32
    assert image['x'] + image['width'] < label['x'] < keycap['x']
    width = menu.button.bounds[2]
    menu.button.text = 'Open another collection'
    game.tick(0)
    assert menu.button.bounds[2] > width
    x, y, w, h = menu.button.bounds
    backend.inject_click(x + w / 2, y + h / 2)
    game.tick(0)
    assert calls == ['open']


def test_long_tooltip_wraps_inside_small_viewport_at_large_text_size():
    """A long explanation at the lower right stays readable inside the canvas and marks truncation."""
    from saga2d import TextStyle

    game = Game('Small tooltip', backend='mock', resolution=(240, 160))
    body_color = (140, 200, 255, 255)
    game.theme.set_text_style('body', TextStyle(20, body_color))
    game.assets.image_from_pil('mark', PILImage.new('RGBA', (24, 24), 'cyan'))

    class Menu(Scene):
        def on_enter(self):
            self.ui.add(Button('Details', icon='mark', show_text=False, anchor=Anchor.BOTTOM_RIGHT,
                               tooltip='A longer explanation with a continuous-identifier-that-needs-wrapping. ' * 8))

    try:
        game.push(Menu())
        game.backend.inject_mouse_move(230, 150)
        game.tick(0)
        backend = game.backend
        tip = [draw for draw in backend.texts if draw['order'] > backend.images[0]['order']]
        assert len(tip) > 1 and tip[-1]['text'].endswith('…')
        for draw in tip:
            assert draw['color'] == body_color
            width, height = backend.measure_text(draw['text'], draw['font_size'], draw['font'])
            assert 0 <= draw['x'] < draw['x'] + width <= game.width
            assert 0 <= draw['y'] < draw['y'] + height <= game.height
        assert all(0 <= x <= game.width and 0 <= y <= game.height
                   for polygon in backend.polygons for x, y in polygon['points'])
    finally:
        game.close()
