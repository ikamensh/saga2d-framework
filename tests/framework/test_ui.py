"""UI tree: layout, reactive labels, buttons, event consumption."""

from saga2d import Anchor, Button, Column, Game, Label, Panel, ProgressBar, Row, Scene


def texts(backend) -> list[str]:
    return [t["text"] for t in backend.texts]


def test_reactive_label_tracks_scene_state(game: Game, backend) -> None:
    class S(Scene):
        def __init__(self) -> None:
            self.gold = 3

        def on_enter(self) -> None:
            self.ui.add(Label(lambda: f"Gold {self.gold}"))

    scene = S()
    game.push(scene)
    game.tick(0.016)
    assert "Gold 3" in texts(backend)
    scene.gold = 7
    game.tick(0.016)
    assert "Gold 7" in texts(backend) and "Gold 3" not in texts(backend)


def test_anchored_component_sits_inside_the_screen(game: Game, backend) -> None:
    class S(Scene):
        def on_enter(self) -> None:
            self.label = Label("hi", anchor=Anchor.BOTTOM_RIGHT, margin=10)
            self.ui.add(self.label)

    scene = S()
    game.push(scene)
    game.tick(0.016)
    x, y, w, h = scene.label.bounds
    assert x + w == game.width - 10
    assert y + h == game.height - 10


def test_column_stacks_children_and_panel_fits_content(game: Game) -> None:
    class S(Scene):
        def on_enter(self) -> None:
            self.a = Label("first")
            self.b = Label("second line")
            self.panel = Panel(anchor=Anchor.CENTER, layout=__import__("saga2d").Layout.VERTICAL, spacing=4,
                               children=[self.a, self.b])
            self.ui.add(self.panel)

    scene = S()
    game.push(scene)
    game.tick(0.016)
    ax, ay, aw, ah = scene.a.bounds
    bx, by, bw, bh = scene.b.bounds
    assert by == ay + ah + 4
    px, py, pw, ph = scene.panel.bounds
    assert px <= ax and py <= ay and px + pw >= bx + bw and py + ph >= by + bh
    assert abs((px + pw / 2) - game.width / 2) <= 1


def test_button_click_fires_callback_and_consumes_the_event(game: Game, backend) -> None:
    clicks: list[str] = []
    passed: list[str] = []

    class S(Scene):
        def on_enter(self) -> None:
            self.button = Button("Go", on_click=lambda: clicks.append("go"), anchor=Anchor.CENTER)
            self.ui.add(self.button)

        def handle_input(self, event) -> bool:
            passed.append(event.type)
            return True

    scene = S()
    game.push(scene)
    game.tick(0.016)
    x, y, w, h = scene.button.bounds
    backend.inject_click(x + w // 2, y + h // 2)
    backend.inject_click(5, 5)
    game.tick(0.016)
    assert clicks == ["go"]
    assert passed == ["click"]


def test_hidden_components_neither_draw_nor_take_input(game: Game, backend) -> None:
    clicks: list[str] = []

    class S(Scene):
        def on_enter(self) -> None:
            self.button = Button("Go", on_click=lambda: clicks.append("go"), anchor=Anchor.CENTER)
            self.button.visible = False
            self.ui.add(self.button)

    scene = S()
    game.push(scene)
    game.tick(0.016)
    assert texts(backend) == []
    backend.inject_click(game.width // 2, game.height // 2)
    game.tick(0.016)
    assert clicks == []


def test_progress_bar_fill_follows_reactive_value(game: Game, backend) -> None:
    class S(Scene):
        def __init__(self) -> None:
            self.hp = 5

        def on_enter(self) -> None:
            self.bar = ProgressBar(value=lambda: self.hp, max_value=10, width=100, height=10, rounded=False)
            self.ui.add(self.bar)

    scene = S()
    game.push(scene)
    game.tick(0.016)
    assert scene.bar.fraction == 0.5
    assert [r["width"] for r in backend.rects] == [100, 50]
    scene.hp = 10
    game.tick(0.016)
    assert [r["width"] for r in backend.rects] == [100, 100]


def test_row_lays_children_left_to_right_in_insertion_order(game: Game) -> None:
    class S(Scene):
        def on_enter(self) -> None:
            self.a, self.b, self.c = Label("a"), Label("bb"), Label("ccc")
            self.ui.add(Row(self.a, self.b, self.c, spacing=6, anchor=Anchor.TOP_LEFT))

    scene = S()
    game.push(scene)
    game.tick(0.016)
    xs = [scene.a.bounds[0], scene.b.bounds[0], scene.c.bounds[0]]
    assert xs == sorted(xs)
    assert scene.b.bounds[0] == scene.a.bounds[0] + scene.a.bounds[2] + 6


def test_hiding_a_child_reflows_its_siblings(game: Game) -> None:
    class S(Scene):
        def on_enter(self) -> None:
            self.a, self.b = Label("a"), Label("b")
            self.ui.add(Column(self.a, self.b, spacing=0, anchor=Anchor.TOP_LEFT))

    scene = S()
    game.push(scene)
    game.tick(0.016)
    y_before = scene.b.bounds[1]
    scene.a.visible = False
    game.tick(0.016)
    assert scene.b.bounds[1] < y_before


def test_clicks_inside_an_opaque_panel_do_not_reach_the_scene(game: Game, backend) -> None:
    clicks: list[str] = []

    class S(Scene):
        def on_enter(self) -> None:
            self.panel = Panel(anchor=Anchor.CENTER, width=200, height=100)
            self.ui.add(self.panel)
            self.ui.add(Row(Label("ghost"), anchor=Anchor.TOP_LEFT))

        def handle_input(self, event) -> bool:
            clicks.append(event.type)
            return True

    scene = S()
    game.push(scene)
    game.tick(0.016)
    x, y, w, h = scene.panel.bounds
    backend.inject_click(x + w // 2, y + h // 2)  # opaque panel: swallowed
    backend.inject_click(5, 5)  # transparent Row: passes through
    game.tick(0.016)
    assert clicks == ["click"]
