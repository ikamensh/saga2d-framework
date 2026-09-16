"""Measured text is reusable before drawing and agrees with the rendered output."""

import math

import pytest

from saga2d import Anchor, Button, Column, Label, Scene, TextStyle, Theme


def test_layout_reserves_exactly_the_height_that_drawing_occupies(game, backend):
    """A bottom-aligned log can place a paragraph before emitting any text."""
    text = "One ancient fortress\n\nAnUnbrokenResourceName\n"
    style = TextStyle(15, (210, 220, 230, 255), "Verdana")

    class Log(Scene):
        def draw(self):
            self.layout = self.layout_text(text, 120, style=style, line_spacing=1.2)
            assert backend.texts == []
            self.height = self.draw_paragraph(text, 25, 350 - self.layout.height, 120,
                                              style=style, line_spacing=1.2)

    scene = Log()
    game.push(scene)
    game.tick(1 / 60)
    layout = scene.layout
    assert tuple(record["text"] for record in backend.texts) == tuple(line for line in layout.lines if line)
    assert "".join(layout.lines).replace(" ", "") == text.replace(" ", "").replace("\n", "")
    assert "" in layout.lines and layout.lines[-1] == ""
    assert scene.height == layout.height
    assert not layout.truncated
    assert layout.height == pytest.approx(layout.line_height * (1 + (len(layout.lines) - 1) * 1.2))
    for index, line in enumerate(layout.lines):
        if line:
            record = next(record for record in backend.texts if record["text"] == line)
            assert record["y"] == pytest.approx(350 - layout.height + index * layout.line_height * 1.2)
            assert backend.measure_text(line, record["font_size"], record["font"])[0] <= 120


def test_limited_paragraph_uses_the_measured_last_line_and_reports_truncation(game, backend):
    """Card previews keep their line budget and visibly mark omitted text."""
    text = "Build the fortress beside the river and defend the northern bridge."

    class Card(Scene):
        def draw(self):
            self.layout = self.layout_text(text, 130, font_size=16, max_lines=2)
            self.height = self.draw_paragraph(text, 20, 30, 130, font_size=16, max_lines=2)

    scene = Card()
    game.push(scene)
    game.tick(1 / 60)
    assert len(scene.layout.lines) == 2
    assert scene.layout.truncated
    assert scene.layout.lines[-1].endswith("…")
    assert tuple(record["text"] for record in backend.texts) == scene.layout.lines
    assert scene.height == scene.layout.height
    assert all(backend.measure_text(line, 16, game.theme.font)[0] <= 130 for line in scene.layout.lines)
    complete = scene.layout_text("Already complete.", 300, max_lines=2)
    assert complete.lines == ("Already complete.",) and not complete.truncated


def test_limited_reactive_label_agrees_with_immediate_layout_and_reflows(game, backend):
    """Retained cards use the same preview budget and shrink when content clears."""
    class Card(Scene):
        def on_enter(self):
            self.message = "An ancient fortress beside the river shields the northern bridge."
            self.label = Label(lambda: self.message, width=125, wrap=True, max_lines=2, font_size=15)
            self.button = Button("Continue")
            self.ui.add(Column(self.label, self.button, spacing=7, anchor=Anchor.TOP_LEFT))

    scene = Card()
    game.push(scene)
    for message in (scene.message, "Ready", ""):
        scene.message = message
        game.tick(1 / 60)
        layout = scene.layout_text(message, 125, max_lines=2, font_size=15)
        assert [record["text"] for record in backend.texts if record["text"] != "Continue"] == list(layout.lines)
        assert scene.label.bounds[3] == pytest.approx(layout.height, abs=1)
        assert scene.button.bounds[1] == scene.label.bounds[1] + scene.label.bounds[3] + 7


@pytest.mark.parametrize("text", ["", "Short", "A very long name for this tiny card", "AnUnbrokenResourceName"])
def test_fitted_names_keep_as_much_text_as_fits_in_the_drawing_font(game, backend, text):
    """Single-line names retain partial words, unlike wrapping a paragraph."""
    scene = Scene()
    game.push(scene)
    style = TextStyle(17, (200, 210, 220, 255), "Verdana")
    width = backend.measure_text("A very long na…", style.font_size, style.font)[0]
    fitted = scene.fit_text(text, width, style=style)
    scene.draw_text(fitted, 20, 20, style=style, anchor_y="top")
    drawn = backend.texts[-1]
    measure = lambda value: backend.measure_text(value, drawn["font_size"], drawn["font"])[0]
    assert measure(fitted) <= width
    if measure(text) <= width:
        assert fitted == text
    else:
        assert fitted.endswith("…") and text.startswith(fitted[:-1])
        prefix = fitted[:-1]
        next_prefix = text[:len(prefix) + 1]
        while next_prefix.endswith(" "):
            next_prefix = text[:len(next_prefix) + 1]
        assert measure(next_prefix + "…") > width


@pytest.mark.parametrize("limit", [0, -1, 1.5, True])
def test_impossible_line_budgets_raise_for_layout_and_retained_labels(game, limit):
    """Invalid budgets cannot silently change meaning for empty or retained text."""
    scene = Scene()
    game.push(scene)
    with pytest.raises(ValueError, match="max_lines"):
        scene.layout_text("", 100, max_lines=limit)
    with pytest.raises(ValueError, match="max_lines"):
        Label("", width=100, wrap=True, max_lines=limit)


@pytest.mark.parametrize("width", [0, -1, math.nan, math.inf])
def test_fitting_rejects_invalid_width_even_for_empty_text(game, width):
    """A caller's invalid layout remains an explicit error before content arrives."""
    scene = Scene()
    game.push(scene)
    with pytest.raises(ValueError, match="width"):
        scene.fit_text("", width)


def test_single_line_fitting_rejects_newlines_and_an_impossible_ellipsis(game, backend):
    """Fitting never returns text wider than its promised one-line rectangle."""
    scene = Scene()
    game.push(scene)
    with pytest.raises(ValueError, match="single line"):
        scene.fit_text("One\nTwo", 100)
    with pytest.raises(ValueError, match="ellipsis"):
        scene.fit_text("A long name", 1)
    width = backend.measure_text("…", game.theme.font_size, game.theme.font)[0]
    assert scene.fit_text("A long name", width) == "…"
    assert scene.fit_text("", 1) == ""
    with pytest.raises(ValueError, match="wrap=True"):
        Label("Name", width=100, max_lines=1)


def test_theme_font_is_shared_by_named_style_layout_drawing_and_retained_labels(game, backend):
    """A style that only changes size must not substitute the system font in paragraphs."""
    game.theme = Theme(font="Theme family", text_styles={"description": TextStyle(17, (190, 200, 210, 255))})
    text = "The same named style uses the same font in both views."

    class Card(Scene):
        def on_enter(self):
            self.ui.add(Label(text, text_style="description", width=160, wrap=True, max_lines=2,
                              anchor=Anchor.TOP_LEFT, margin=(400, 20)))

        def draw(self):
            self.layout = self.layout_text(text, 160, style="description", max_lines=2)
            self.draw_paragraph(text, 20, 20, 160, style="description", max_lines=2)

    scene = Card()
    game.push(scene)
    game.tick(1 / 60)
    assert all(record["font"] == "Theme family" for record in backend.texts)
    assert [record["text"] for record in backend.texts] == list(scene.layout.lines) * 2
