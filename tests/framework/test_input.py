"""Keyboard/mouse dispatch: controls, bind_key, modifiers, handle_input, held keys."""

from saga2d import Game, InputEvent, Scene


class Hotkeys(Scene):
    controls = {
        "e": "end_turn",
        ("n", "tab"): "next_unit",
        "shift+tab": "prev_unit",
        "ctrl+s": "save",
    }

    def __init__(self) -> None:
        self.calls: list[str] = []

    def end_turn(self) -> None:
        self.calls.append("end_turn")

    def next_unit(self, event: InputEvent) -> None:
        self.calls.append(f"next:{event.key}")

    def prev_unit(self) -> None:
        self.calls.append("prev")

    def save(self) -> None:
        self.calls.append("save")


def test_controls_dispatch_on_key_press_with_aliases_and_chords(game: Game, backend) -> None:
    scene = Hotkeys()
    game.push(scene)
    backend.inject_key("e")
    backend.inject_key("n")
    backend.inject_key("tab")
    backend.inject_key("tab", shift=True)
    backend.inject_key("s", ctrl=True)
    backend.inject_key("e", type="key_release")
    game.tick(0.016)
    assert scene.calls == ["end_turn", "next:n", "next:tab", "prev", "save"]


def test_handlers_with_defaulted_parameters_are_called_bare(game: Game, backend) -> None:
    seen: list[object] = []

    class S(Scene):
        controls = {"n": "step", "m": "with_event"}

        def step(self, amount: int = 1) -> None:
            seen.append(amount)

        def with_event(self, event: InputEvent) -> None:
            seen.append(event.key)

    game.push(S())
    backend.inject_key("n")
    backend.inject_key("m")
    game.tick(0.016)
    assert seen == [1, "m"]


def test_unbound_modifier_chord_falls_back_to_bare_key(game: Game, backend) -> None:
    scene = Hotkeys()
    game.push(scene)
    backend.inject_key("e", shift=True)
    game.tick(0.016)
    assert scene.calls == ["end_turn"]


def test_controls_with_missing_method_fail_at_class_definition() -> None:
    import pytest

    with pytest.raises(AttributeError, match="typo"):

        class Bad(Scene):
            controls = {"x": "typo"}


def test_bind_key_overrides_controls_and_unhandled_keys_reach_handle_input(game: Game, backend) -> None:
    seen: list[str] = []

    class S(Hotkeys):
        def handle_input(self, event: InputEvent) -> bool:
            seen.append(event.key or event.type)
            return True

    scene = S()
    game.push(scene)
    scene.bind_key("e", lambda: scene.calls.append("bound"))
    backend.inject_key("e")
    backend.inject_key("z")
    game.tick(0.016)
    assert scene.calls == ["bound"]
    assert seen == ["z"]


def test_mouse_events_carry_world_coordinates_from_the_camera(game: Game, backend) -> None:
    from saga2d import Camera

    events: list[InputEvent] = []

    class World(Scene):
        def on_enter(self) -> None:
            self.camera = Camera(self.game.resolution, zoom=2.0)
            self.camera.scroll(100, 50)

        def handle_input(self, event: InputEvent) -> bool:
            events.append(event)
            return True

    game.push(World())
    backend.inject_click(40, 20)
    game.tick(0.016)
    assert (events[0].world_x, events[0].world_y) == (120.0, 60.0)


def test_held_keys_are_queryable_between_press_and_release(game: Game, backend) -> None:
    game.push(Scene())
    backend.inject_key("w")
    game.tick(0.016)
    assert game.input.is_pressed("w")
    backend.inject_key("w", type="key_release")
    game.tick(0.016)
    assert not game.input.is_pressed("w")


def test_window_close_stops_the_game(game: Game, backend) -> None:
    game.push(Scene())
    backend.inject_window_event("close")
    game.tick(0.016)
    assert game.running is False


def test_scroll_and_drag_deltas_keep_their_fractions(game: Game, backend) -> None:
    events: list[InputEvent] = []

    class Catch(Scene):
        def handle_input(self, event: InputEvent) -> bool:
            events.append(event)
            return True

    game.push(Catch())
    backend.inject_scroll(10, 10, 0.0, 0.3)
    backend.inject_drag(12, 14, 1.5, -0.25, button="right")
    game.tick(0.016)
    assert (events[0].type, events[0].dy) == ("scroll", 0.3)
    assert (events[1].type, events[1].dx, events[1].dy) == ("drag", 1.5, -0.25)
