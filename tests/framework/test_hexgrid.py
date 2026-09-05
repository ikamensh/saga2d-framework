"""Public hex-grid behavior shared by tactical maps and their input handling."""

import math

import pytest

from saga2d import HexGrid


def test_hex_geometry_roundtrips_on_translated_scaled_irregular_map():
    """Centers and inset corners pick their source cell at any size and origin."""
    cells = {(q, r) for q in range(-3, 4) for r in range(-2, 3)} - {(0, 0)}
    for size, origin in [(1, (0, 0)), (37.5, (190, -80)), (0.125, (-4, 9))]:
        grid = HexGrid(cells, size=size, origin=origin)
        assert grid.cells == frozenset(cells)
        for cell in cells:
            x, y = grid.center(cell)
            assert grid.cell_at(x, y) == cell
            corners = grid.corners(cell)
            assert len(corners) == 6
            for cx, cy in corners:
                assert math.hypot(cx - x, cy - y) == pytest.approx(size)
                assert grid.cell_at(x + (cx - x) * 0.99, y + (cy - y) * 0.99) == cell
            for neighbor in grid.neighbors(cell):
                assert neighbor in cells
                assert cell in grid.neighbors(neighbor)
                assert HexGrid.distance(cell, neighbor) == 1
                assert math.dist(grid.center(cell), grid.center(neighbor)) == pytest.approx(size * math.sqrt(3))
        assert grid.cell_at(*origin) is None
        assert grid.cell_at(*grid.center((50, 50))) is None


def test_paths_and_ranges_agree_on_minimum_terrain_cost():
    """Movement previews and actual routes share terrain costs and blockers."""
    grid = HexGrid((q, r) for q in range(5) for r in range(4))
    start = (0, 1)
    blocked = {(2, 1), (2, 2), start}
    expensive = {(1, 1), (1, 2), (3, 0)}

    def terrain_cost(cell):
        return 5.0 if cell in expensive else 1.0

    reachable = grid.reachable(start, 5, blocked=blocked, cost=terrain_cost)
    assert reachable[start] == 0
    assert reachable[(2, 0)] == 2
    assert reachable[(2, 3)] == 4
    assert (3, 1) not in reachable
    assert (4, 3) not in reachable
    for goal, movement_cost in reachable.items():
        route = grid.path(start, goal, blocked=blocked, cost=terrain_cost)
        assert route[0] == start
        assert route[-1] == goal
        assert not set(route[1:]) & blocked
        assert all(b in grid.neighbors(a) for a, b in zip(route, route[1:]))
        assert sum(terrain_cost(cell) for cell in route[1:]) == movement_cost
        assert movement_cost <= 5
        assert grid.reachable(start, movement_cost, blocked=blocked, cost=terrain_cost)[goal] == movement_cost
    assert grid.path(start, (2, 1), blocked=blocked) == []
    assert grid.path(start, start, blocked=blocked) == [start]


@pytest.mark.parametrize("size", [0, -1, math.inf, math.nan])
def test_invalid_hex_size_is_rejected(size):
    """A degenerate hex cannot support consistent geometry or picking."""
    with pytest.raises(ValueError, match="size"):
        HexGrid([(0, 0)], size=size)


def test_navigation_rejects_positions_outside_the_map():
    """Missing start/goal cells are caller errors, not disconnected routes."""
    grid = HexGrid([(0, 0), (1, 0)])
    with pytest.raises(ValueError, match="start"):
        grid.reachable((3, 0), 5)
    with pytest.raises(ValueError, match="start"):
        grid.path((3, 0), (0, 0))
    with pytest.raises(ValueError, match="goal"):
        grid.path((0, 0), (3, 0))


@pytest.mark.parametrize("cost", [0, -1, math.inf, math.nan])
def test_navigation_rejects_invalid_terrain_cost(cost):
    """Invalid terrain costs fail clearly instead of creating free movement."""
    grid = HexGrid([(0, 0), (1, 0)])
    with pytest.raises(ValueError, match="cost"):
        grid.reachable((0, 0), 5, cost=lambda cell: cost)
    with pytest.raises(ValueError, match="cost"):
        grid.path((0, 0), (1, 0), cost=lambda cell: cost)


@pytest.mark.parametrize("budget", [-1, math.inf, math.nan])
def test_navigation_rejects_invalid_budget(budget):
    """A movement range needs a finite nonnegative budget."""
    grid = HexGrid([(0, 0), (1, 0)])
    with pytest.raises(ValueError, match="budget"):
        grid.reachable((0, 0), budget)


def test_uniform_cost_routes_match_hex_distance_and_disconnected_cells_stay_unreachable():
    """On an unobstructed convex map, routing agrees with geometric distance."""
    cells = {(q, r) for q in range(-3, 4) for r in range(-3, 4)
             if HexGrid.distance((0, 0), (q, r)) <= 3}
    grid = HexGrid(cells | {(20, 20)})
    for start in cells:
        reached = grid.reachable(start, 20)
        assert set(reached) == cells
        for goal in cells:
            route = grid.path(start, goal)
            assert len(route) - 1 == HexGrid.distance(start, goal) == reached[goal]
        assert grid.path(start, (20, 20)) == []
        assert grid.reachable(start, 0) == {start: 0}
    empty = HexGrid([])
    assert empty.cell_at(0, 0) is None
    assert empty.neighbors((0, 0)) == ()
