"""Camera zoom: eased towards a target about a fixed screen point."""

import math

from saga2d import Camera


def settle(camera: Camera, seconds: float = 1.0) -> None:
    for _ in range(int(seconds * 60)):
        camera.update(1 / 60)


def test_zoom_toward_eases_to_the_target_and_keeps_the_anchor_point_fixed() -> None:
    camera = Camera((800, 600), zoom=1.0, min_zoom=0.5, max_zoom=3.0)
    camera.center_on(1000, 1000)
    anchor_world = camera.screen_to_world(600, 100)
    camera.zoom_toward(2.0, 600, 100)
    assert camera.zoom == 1.0 and camera.zoom_target == 2.0
    camera.update(1 / 60)
    assert 1.0 < camera.zoom < 2.0
    assert camera.screen_to_world(600, 100) == __import__("pytest").approx(anchor_world)
    settle(camera)
    assert camera.zoom == 2.0
    assert camera.screen_to_world(600, 100) == __import__("pytest").approx(anchor_world)


def test_zoom_target_is_clamped_and_a_stream_of_small_steps_accumulates() -> None:
    camera = Camera((800, 600), zoom=1.0, min_zoom=0.5, max_zoom=2.5)
    for _ in range(40):  # a trackpad delivers many fractional lines
        camera.zoom_toward(camera.zoom_target * 1.06 ** 0.3, 400, 300)
    assert camera.zoom_target == __import__("pytest").approx(1.06 ** 12)
    camera.zoom_toward(100.0, 400, 300)
    assert camera.zoom_target == 2.5
    settle(camera)
    assert camera.zoom == 2.5


def test_setting_zoom_directly_cancels_a_pending_ease() -> None:
    camera = Camera((800, 600), zoom=1.0)
    camera.zoom_toward(3.0, 0, 0)
    camera.zoom = 1.5
    assert camera.zoom_target == 1.5
    settle(camera)
    assert camera.zoom == 1.5


def test_zoom_ease_converges_at_a_fixed_rate_regardless_of_frame_length() -> None:
    fast, slow = Camera((800, 600), zoom=1.0), Camera((800, 600), zoom=1.0)
    for camera in (fast, slow):
        camera.zoom_toward(2.0, 400, 300)
    for _ in range(12):
        fast.update(1 / 120)
    for _ in range(6):
        slow.update(1 / 60)
    assert math.isclose(fast.zoom, slow.zoom, rel_tol=1e-6)


def test_insets_keep_the_world_reachable_behind_hud_panels() -> None:
    """A world edge scrolls into the clear past a HUD inset by that many screen pixels, at any zoom."""
    approx = __import__("pytest").approx
    camera = Camera((800, 600), world_bounds=(0, 0, 2000, 2000), insets=(0, 100, 0, 150), zoom=1.0, min_zoom=0.5, max_zoom=2.0)
    camera.scroll(-1e6, -1e6)
    assert camera.world_to_screen(0, 0) == approx((0, 100))
    camera.scroll(1e6, 1e6)
    assert camera.world_to_screen(2000, 2000) == approx((800, 450))
    camera.zoom = 2.0
    camera.scroll(-1e6, -1e6)
    assert camera.world_to_screen(0, 0) == approx((0, 100))
    camera.zoom = 0.5
    camera.scroll(1e6, 1e6)
    assert camera.world_to_screen(2000, 2000) == approx((800, 450))


def test_a_world_smaller_than_the_clear_area_is_centred_in_it() -> None:
    camera = Camera((800, 600), world_bounds=(0, 0, 800, 200), insets=(0, 100, 0, 100))
    assert camera.world_to_screen(0, 0)[1] == __import__("pytest").approx(200)  # clear band 100..500; the world sits at 200..400
    assert camera.world_to_screen(0, 200)[1] == __import__("pytest").approx(400)
