"""Player input shares focus and pointer ownership across standard and custom controls."""

from saga2d import Anchor, Button, Column, Component, Panel, Scene


def test_opt_in_focus_skips_unavailable_controls_and_preserves_gameplay_keys(game, backend):
    """Menus can use arrows and Enter without taking Space from a game command."""
    calls = []

    class Menu(Scene):
        controls = {"space": "end_turn"}

        def on_enter(self):
            self.first = Button("First", on_click=lambda: calls.append("first"))
            self.disabled = Button("Unavailable", enabled=False)
            self.hidden = Button("Hidden", visible=False)
            self.last = Button("Last", on_click=lambda: calls.append("last"))
            self.ui.add(Column(self.first, self.disabled, self.hidden, self.last))
            self.ui.enable_focus(navigation="vertical", activate=("return",))

        def end_turn(self):
            calls.append("turn")

    menu = Menu()
    game.push(menu)
    backend.inject_key("tab")
    game.tick(0)
    assert menu.ui.focused is menu.first and menu.first.focused
    backend.inject_key("down")
    backend.inject_key("return")
    backend.inject_key("space")
    game.tick(0)
    assert menu.ui.focused is menu.last
    assert calls == ["last", "turn"]
    backend.inject_key("tab", shift=True)
    game.tick(0)
    assert menu.ui.focused is menu.first


def test_pointer_focuses_row_and_disabled_hud_blocks_world_clicks(game, backend):
    """The focus owner may wrap pointer buttons, and unavailable UI is still not the world."""
    calls = []

    class Menu(Scene):
        def on_enter(self):
            self.row = Panel(width=240, height=80, focusable=True, blocks_pointer=True,
                             anchor=Anchor.TOP_LEFT, margin=20)
            self.button = Button("Increase", width=100, height=40, focusable=False,
                                 on_click=lambda: calls.append("increase"))
            self.row.add(self.button)
            self.ui.add(self.row)
            self.ui.enable_focus()

        def handle_input(self, event):
            if event.type == "click":
                calls.append("world")

    menu = Menu()
    game.push(menu)
    backend.inject_click(40, 40)
    game.tick(0)
    assert calls == ["increase"] and menu.ui.focused is menu.row
    assert menu.button.hovered and game.mouse_position == (40, 40)
    menu.row.enabled = False
    backend.inject_click(40, 40)
    game.tick(0)
    assert calls == ["increase"] and menu.ui.focused is None
    assert menu.ui.pointer_target(40, 40) is menu.button
    menu.row.visible = False
    backend.inject_click(40, 40)
    game.tick(0)
    assert calls == ["increase", "world"]
    assert menu.ui.pointer_target(40, 40) is None


def test_custom_drag_control_owns_pointer_until_release_and_loses_capture_on_cover(game, backend):
    """Dragging over another control stays with its owner; a modal cannot leave stale capture."""
    events = []

    class DragControl(Component):
        def on_event(self, event):
            if event.type == "click" and self.hit_test(event.x, event.y):
                self.capture_pointer()
                return True
            if self.has_pointer_capture and event.type in ("drag", "release"):
                events.append(event.type)
                if event.type == "release":
                    self.release_pointer()
                return True
            return False

        def on_pointer_cancel(self):
            events.append("cancel")

    class World(Scene):
        def on_enter(self):
            self.drag = DragControl(width=80, height=40, blocks_pointer=True, anchor=Anchor.TOP_LEFT)
            self.ui.add(self.drag)
            self.ui.add(Button("Other", width=100, height=40, margin=(100, 0), anchor=Anchor.TOP_LEFT,
                               on_click=lambda: events.append("other")))

    world = World()
    game.push(world)
    backend.inject_click(20, 20)
    backend.inject_drag(120, 20, 100, 0)
    backend.inject_release(120, 20)
    game.tick(0)
    assert events == ["drag", "release"] and not world.drag.has_pointer_capture
    backend.inject_click(20, 20)
    game.tick(0)
    game.push(Scene())
    assert events[-1] == "cancel" and not world.drag.has_pointer_capture
    game.pop()
    backend.inject_click(120, 20)
    game.tick(0)
    assert events[-1] == "other"


def test_explicit_shortcuts_precede_navigation_and_focus_belongs_to_each_scene(game, backend):
    """An explicit key keeps its meaning, while a modal owns activation and leaves focus behind it."""
    calls = []

    class Menu(Scene):
        def on_enter(self):
            self.first = Button("First", on_click=lambda: calls.append("first"))
            self.next = Button("Next page", shortcut="Tab", on_click=lambda: calls.append("page"))
            self.ui.add(Column(self.first, self.next))
            self.ui.enable_focus()
            self.ui.focus(self.first)

    class Modal(Scene):
        transparent = True

        def on_enter(self):
            self.close = Button("Close", on_click=self.game.pop)
            self.ui.add(self.close)
            self.ui.enable_focus()
            self.ui.focus(self.close)

    menu = Menu()
    game.push(menu)
    backend.inject_key("tab")
    game.tick(0)
    assert calls == ["page"] and menu.ui.focused is menu.first
    game.push(Modal())
    backend.inject_key("return")
    backend.inject_key("return")
    game.tick(0)
    assert game.scene is menu and calls == ["page"]
    backend.inject_key("return")
    game.tick(0)
    assert calls == ["page", "first"]
    menu.first.visible = False
    menu.first.visible = True
    assert menu.ui.focused is None
    menu.ui.focus(menu.first)
    menu.ui.remove(menu.first.parent)
    assert menu.ui.focused is None and not menu.first.activate()


def test_directional_navigation_uses_custom_control_geometry_and_candidate_policy(game, backend):
    """A tech tree can supply eligible nodes without reimplementing geometric or cyclic navigation."""
    class Node(Component):
        def on_activate(self):
            self.activated = True

    scene = Scene()
    game.push(scene)
    nodes = [Node(width=40, height=40, focusable=True, blocks_pointer=True,
                  anchor=Anchor.TOP_LEFT, margin=position)
             for position in ((100, 100), (200, 100), (100, 200), (0, 100))]
    for node in nodes:
        scene.ui.add(node)
    scene.ui.enable_focus(navigation="spatial")
    scene.ui.focus(nodes[0])
    backend.inject_key("right")
    game.tick(0)
    assert scene.ui.focused is nodes[1]
    scene.ui.focus_direction("left")
    assert scene.ui.focused is nodes[0]
    scene.ui.focus_next(candidates=(nodes[2], nodes[3]))
    assert scene.ui.focused is nodes[2]
    backend.inject_key("return")
    game.tick(0)
    assert nodes[2].activated


def test_button_press_is_cancelled_when_its_callback_opens_a_modal(game, backend):
    """Releasing over a covering scene must not leave the original button visually pressed."""
    class Modal(Scene):
        pop_on_cancel = True

    class Menu(Scene):
        def on_enter(self):
            self.button = self.ui.add(Button("Open", width=100, height=40, anchor=Anchor.TOP_LEFT,
                                            on_click=lambda: self.game.push(Modal())))

    menu = Menu()
    game.push(menu)
    backend.inject_click(20, 20)
    game.tick(0)
    backend.inject_release(20, 20)
    backend.inject_key("escape")
    game.tick(0)
    backend.inject_mouse_move(300, 300)
    game.tick(0)
    assert game.scene is menu and menu.button.state == "normal"
    game.pop()
    assert not menu.button.activate(), "A retained reference cannot activate a removed scene's UI"


def test_window_focus_loss_cancels_a_press_from_the_same_input_batch(game, backend):
    """An OS focus event queued beside a click must not leave a pressed control behind."""
    cancellations = []

    class Control(Button):
        def on_pointer_cancel(self):
            cancellations.append("cancel")
            super().on_pointer_cancel()

    scene = Scene()
    game.push(scene)
    button = scene.ui.add(Control("Press", width=100, height=40, anchor=Anchor.TOP_LEFT))
    scene.ui.enable_focus()
    backend.inject_click(20, 20)
    backend.inject_focus(False)
    game.tick(0)
    assert not button.has_pointer_capture and button.state != "pressed"
    assert cancellations == ["cancel"] and scene.ui.focused is button
    backend.inject_focus(False)
    game.tick(0)
    assert cancellations == ["cancel"] and scene.ui.focused is button


def test_hiding_the_window_cancels_a_held_press(game, backend):
    """Minimizing (or switching away from fullscreen) must not leave a pressed control behind."""
    scene = Scene()
    game.push(scene)
    button = scene.ui.add(Button("Press", width=100, height=40, anchor=Anchor.TOP_LEFT))
    backend.inject_click(20, 20)
    game.tick(0)
    assert button.has_pointer_capture
    backend.inject_visibility(False)
    game.tick(0)
    assert not button.has_pointer_capture and button.state != "pressed"


def test_first_click_after_reactivate_fires(game, backend):
    """Returning from an alt-tab, the first button press must work, not be eaten by stale state."""
    calls = []
    scene = Scene()
    game.push(scene)
    scene.ui.add(Button("Press", width=100, height=40, anchor=Anchor.TOP_LEFT, on_click=lambda: calls.append("press")))
    backend.inject_focus(False)
    game.tick(0)
    backend.inject_focus(True)
    game.tick(0)
    backend.inject_click(20, 20)
    backend.inject_release(20, 20)
    game.tick(0)
    assert calls == ["press"]
