"""Button shortcuts keep visible controls and public keyboard input together."""

import pytest

from saga2d import Anchor, Button, Camera, Component, Game, Panel, Scene


def test_button_shortcut_draws_its_keycap_and_activates_like_a_click(game: Game, backend) -> None:
    """A button needs one declaration for both keyboard and pointer activation."""
    calls = []

    class Menu(Scene):
        def on_enter(self):
            self.button = Button("Add", shortcut="E", on_click=lambda: calls.append("add"), anchor=Anchor.CENTER)
            self.ui.add(self.button)

    scene = Menu()
    game.push(scene)
    game.tick(0)
    assert "E" in [text["text"] for text in backend.texts]
    backend.inject_key("e")
    backend.inject_key("e", type="key_release")
    game.tick(0)
    assert calls == ["add"]
    x, y, width, height = scene.button.bounds
    backend.inject_click(x + width / 2, y + height / 2)
    game.tick(0)
    assert calls == ["add", "add"]


@pytest.mark.parametrize("disable_parent", [False, True])
def test_disabled_shortcut_cannot_fall_through_to_scene_controls(game: Game, backend, disable_parent) -> None:
    """Disabled visible controls reserve their key without performing the action."""
    calls = []

    class Menu(Scene):
        controls = {"e": "fallback"}

        def fallback(self):
            calls.append("fallback")

        def on_enter(self):
            self.button = Button("Add", shortcut="E", on_click=lambda: calls.append("button"))
            self.panel = Panel(children=[self.button])
            self.ui.add(self.panel)

    scene = Menu()
    game.push(scene)
    target = scene.panel if disable_parent else scene.button
    target.enabled = False
    backend.inject_key("e")
    game.tick(0)
    assert calls == []
    target.enabled = True
    backend.inject_key("e")
    game.tick(0)
    assert calls == ["button"]


@pytest.mark.parametrize("shortcut, error", [("", ValueError), ((), ValueError), ("ctrl+", ValueError),
                                            ("hyper+e", ValueError), (("E", 1), TypeError), (["E"], TypeError)])
def test_invalid_shortcuts_fail_at_button_construction(shortcut, error) -> None:
    """Malformed declarations fail before a player reaches an unusable keycap."""
    with pytest.raises(error):
        Button("Add", shortcut=shortcut)


def test_button_cannot_show_a_different_hint_from_its_bound_shortcut() -> None:
    """Display-only contextual hints and button-owned shortcuts are alternatives."""
    with pytest.raises(ValueError, match="hotkey.*shortcut"):
        Button("Add", hotkey="A", shortcut="E")


def test_shortcut_aliases_and_modifiers_match_exactly(game: Game, backend) -> None:
    """Shift+1 cannot activate 1, and scene chords remain available independently."""
    calls = []

    class Menu(Scene):
        controls = {"ctrl+1": "global_action"}

        def global_action(self):
            calls.append("global")

        def on_enter(self):
            for label, shortcut in (("accept", ("Enter", "Space")), ("cancel", "Esc"),
                                    ("one", "1"), ("backup", "Shift+1"), ("save", "Shift+Ctrl+S")):
                self.ui.add(Button(label, shortcut=shortcut, on_click=lambda label=label: calls.append(label)))

        def handle_input(self, event):
            if event.type == "key_press":
                calls.append("unhandled:" + event.combo)
            return True

    game.push(Menu())
    for key in ("return", "space", "escape", "1"):
        backend.inject_key(key)
    backend.inject_key("1", shift=True)
    backend.inject_key("1", ctrl=True)
    backend.inject_key("s", ctrl=True, shift=True)
    backend.inject_key("1", alt=True)
    game.tick(0)
    assert calls == ["accept", "accept", "cancel", "one", "backup", "global", "save", "unhandled:alt+1"]
    assert "Enter" in [text["text"] for text in backend.texts]
    assert "Space" not in [text["text"] for text in backend.texts]


@pytest.mark.parametrize("remove", ["hide_button", "hide_parent", "remove", "clear"])
def test_shortcuts_follow_visible_tree_after_removal_and_replacement(game: Game, backend, remove) -> None:
    """A short inventory page cannot retain callbacks from the previous page."""
    calls = []

    class Menu(Scene):
        def on_enter(self):
            self.button = Button("Old", shortcut="1", on_click=lambda: calls.append("old"))
            self.panel = Panel(children=[self.button])
            self.ui.add(self.panel)

        def handle_input(self, event):
            calls.append("unhandled")
            return True

    scene = Menu()
    game.push(scene)
    backend.inject_key("1")
    game.tick(0)
    if remove == "hide_button":
        scene.button.visible = False
    elif remove == "hide_parent":
        scene.panel.visible = False
    elif remove == "remove":
        scene.panel.remove(scene.button)
    else:
        scene.panel.clear()
    backend.inject_key("1")
    game.tick(0)
    assert calls == ["old", "unhandled"]
    scene.ui.add(Button("New", shortcut="1", on_click=lambda: calls.append("new")))
    backend.inject_key("1")
    game.tick(0)
    assert calls == ["old", "unhandled", "new"]


def test_two_visible_buttons_cannot_silently_claim_the_same_shortcut(game: Game, backend) -> None:
    """An ambiguous key reports both controls before either callback runs."""
    calls = []
    scene = Scene()
    game.push(scene)
    scene.ui.add(Button("First", shortcut="Enter", on_click=lambda: calls.append("first")))
    scene.ui.add(Button("Second", shortcut="return", on_click=lambda: calls.append("second")))
    backend.inject_key("return")
    with pytest.raises(ValueError, match="(?i)duplicate.*return.*First.*Second"):
        game.tick(0)
    assert calls == []


def test_display_only_hotkey_leaves_contextual_scene_action_intact(game: Game, backend) -> None:
    """Existing hints may describe a contextual action different from a click."""
    calls = []

    class Menu(Scene):
        controls = {"return": "context_action"}

        def context_action(self):
            calls.append("context")

    scene = Menu()
    game.push(scene)
    scene.ui.add(Button("Act", hotkey="Enter", on_click=lambda: calls.append("button")))
    backend.inject_key("return")
    game.tick(0)
    assert calls == ["context"]
    assert "Enter" in [text["text"] for text in backend.texts]


def test_custom_ui_can_consume_keyboard_before_button_shortcuts(game: Game, backend) -> None:
    """UI modules such as an editor keep their existing first refusal on keys."""
    calls = []

    class Editor(Component):
        def on_event(self, event):
            if event.type == "key_press":
                calls.append("editor")
                return True
            return False

    scene = Scene()
    game.push(scene)
    editor = Editor()
    scene.ui.add(editor)
    scene.ui.add(Button("Add", shortcut="E", on_click=lambda: calls.append("button")))
    backend.inject_key("e")
    game.tick(0)
    assert calls == ["editor"]
    editor.visible = False
    backend.inject_key("e")
    game.tick(0)
    assert calls == ["editor", "button"]


def test_overlay_shortcuts_are_scoped_and_transition_discards_queued_repeats(game: Game, backend) -> None:
    """A result-like button cannot also activate a covered scene with the same key."""
    calls = []
    base = Scene()
    game.push(base)
    base.ui.add(Button("Base", shortcut="Esc", on_click=lambda: calls.append("base")))

    class Overlay(Scene):
        transparent = True

        def on_enter(self):
            self.ui.add(Button("Close", shortcut="Esc", on_click=self.close))

        def close(self):
            calls.append("close")
            self.game.pop()

    game.push(Overlay())
    backend.inject_key("escape")
    backend.inject_key("escape")
    backend.inject_key("escape", type="key_release")
    game.tick(0)
    assert game.scene is base and calls == ["close"]
    assert not game.input.is_pressed("escape")
    backend.inject_key("escape")
    game.tick(0)
    assert calls == ["close", "base"]


def test_appearing_shortcut_does_not_swallow_a_camera_key_release(game: Game, backend) -> None:
    """A key previously held by the camera must stop scrolling when released."""
    calls = []

    class Menu(Scene):
        def on_enter(self):
            self.camera = Camera(self.game.resolution)
            self.camera.enable_key_scroll(bindings={"right": ("e",)})
            self.button = Button("Add", shortcut="E", visible=False, on_click=lambda: calls.append("button"))
            self.ui.add(self.button)

    scene = Menu()
    game.push(scene)
    backend.inject_key("e")
    game.tick(.1)
    moved = scene.camera.offset
    assert moved[0] > 0
    scene.button.visible = True
    backend.inject_key("e", type="key_release")
    game.tick(.1)
    assert scene.camera.offset == moved and not game.input.is_pressed("e")
    backend.inject_key("e")
    game.tick(.1)
    assert calls == ["button"] and scene.camera.offset == moved
