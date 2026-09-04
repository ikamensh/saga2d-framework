"""Rounded rectangles: geometry and how components draw them."""

from saga2d import Button, Game, KeyHints, Panel, Scene, Style, Theme
from saga2d.rendering.shapes import rounded_rect, rounded_rect_border
from saga2d.ui import Anchor


def test_rounded_rect_outline_stays_inside_the_box_and_touches_every_side() -> None:
    points = rounded_rect(10, 20, 100, 50, 12)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    assert min(xs) == 10 and max(xs) == 110 and min(ys) == 20 and max(ys) == 70
    assert (10, 20) not in points  # the corner itself is cut off
    assert rounded_rect(0, 0, 40, 30, 0) == [(0, 0), (40, 0), (40, 30), (0, 30)]


def test_radius_is_clamped_to_half_the_shorter_side() -> None:
    pill = rounded_rect(0, 0, 100, 20, 50)
    assert all(0 <= x <= 100 and 0 <= y <= 20 for x, y in pill)


def test_border_quads_ring_the_outline_just_inside_the_edge() -> None:
    quads = rounded_rect_border(0, 0, 100, 60, 10, 2)
    assert quads and all(len(q) == 4 for q in quads)
    for quad in quads:
        assert all(0 <= x <= 100 and 0 <= y <= 60 for x, y in quad)
    inner = [p for quad in quads for p in quad[2:]]
    assert all(2 <= x <= 98 and 2 <= y <= 58 for x, y in inner)


def test_rounded_panels_and_buttons_draw_polygons_and_hotkeys_become_keycaps() -> None:
    game = Game("Shapes", backend="mock", theme=Theme(panel_radius=10, button_radius=6))
    try:
        class UI(Scene):
            def on_enter(self) -> None:
                panel = Panel(anchor=Anchor.CENTER, layout=__import__("saga2d").Layout.VERTICAL, spacing=4)
                panel.add(Button("End turn", hotkey="E"))
                panel.add(KeyHints([("Tab", "next unit"), ("Esc", "menu")]))
                self.ui.add(panel)

        game.push(UI())
        game.tick(0.016)
        assert game.backend.rects == []  # everything rounded
        texts = [t["text"] for t in game.backend.texts]
        assert "End turn" in texts and texts.count("E") == 1
        assert texts.index("End turn") < texts.index("E")
        assert texts[-4:] == ["Tab", "next unit", "Esc", "menu"]
        keycaps = [p for p in game.backend.polygons if len(p["points"]) > 4]
        assert len(keycaps) >= 2 + 2 * 3  # panel, button, and two polygons per keycap
    finally:
        game._teardown()


def test_square_theme_still_draws_plain_rects(game: Game, backend) -> None:
    class UI(Scene):
        def on_enter(self) -> None:
            self.ui.add(Panel(anchor=Anchor.TOP_LEFT, width=50, height=20, style=Style(border_width=0)))

    game.push(UI())
    game.tick(0.016)
    assert [r["width"] for r in backend.rects] == [50] and backend.polygons == []
