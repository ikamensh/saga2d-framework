"""Finite pointy-top hex maps: geometry, picking, and terrain-aware navigation."""

from collections.abc import Callable, Iterable
import heapq
import math


type Cell = tuple[int, int]
type Point = tuple[float, float]

_DIRECTIONS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
_SQRT3 = math.sqrt(3)


class HexGrid:
    """A finite set of axial ``(q, r)`` cells, independent of game rules.

    ``size`` is the center-to-corner radius, and ``origin`` is the center of
    cell ``(0, 0)``. Size must be positive and finite. Coordinates use
    Saga2D's y-down convention. The grid can have holes or disconnected
    regions. Geometry methods also accept cells
    outside the grid; picking and navigation respect its finite cell set.
    """

    def __init__(self, cells: Iterable[Cell], *, size: float = 1.0,
                 origin: Point = (0, 0)) -> None:
        if not math.isfinite(size) or size <= 0:
            raise ValueError("Hex size must be positive and finite")
        self.cells = frozenset(cells)
        self.size = size
        self.origin = origin

    def neighbors(self, cell: Cell) -> tuple[Cell, ...]:
        """Return adjacent cells present in this grid, in a stable order."""
        q, r = cell
        return tuple((q + dq, r + dr) for dq, dr in _DIRECTIONS
                     if (q + dq, r + dr) in self.cells)

    @staticmethod
    def distance(a: Cell, b: Cell) -> int:
        """Return hex steps ignoring map edges, holes, and movement costs."""
        dq, dr = a[0] - b[0], a[1] - b[1]
        return max(abs(dq), abs(dr), abs(dq + dr))

    def center(self, cell: Cell) -> Point:
        """Return the world-space center of an axial cell."""
        q, r = cell
        return (self.origin[0] + self.size * _SQRT3 * (q + r / 2),
                self.origin[1] + self.size * 1.5 * r)

    def corners(self, cell: Cell) -> list[Point]:
        """Return six clockwise polygon vertices, starting at the top right."""
        x, y = self.center(cell)
        return [(x + self.size * math.cos(math.radians(60 * i - 30)),
                 y + self.size * math.sin(math.radians(60 * i - 30)))
                for i in range(6)]

    def cell_at(self, x: float, y: float) -> Cell | None:
        """Pick a cell from world coordinates; return ``None`` outside the map.

        A point exactly on a shared edge or vertex belongs to one of the
        touching hexes, chosen deterministically by cube-coordinate rounding.
        """
        x = (x - self.origin[0]) / self.size
        y = (y - self.origin[1]) / self.size
        q, r = _SQRT3 / 3 * x - y / 3, 2 / 3 * y
        s = -q - r
        rq, rr, rs = round(q), round(r), round(s)
        dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
        if dq > dr and dq > ds:
            rq = -rr - rs
        elif dr > ds:
            rr = -rq - rs
        cell = (rq, rr)
        return cell if cell in self.cells else None

    def reachable(self, start: Cell, budget: float, *,
                  blocked: Iterable[Cell] = (),
                  cost: Callable[[Cell], float] | None = None) -> dict[Cell, float]:
        """Return minimum movement costs for cells within ``budget`` of start.

        ``cost(cell)`` is the positive cost to enter a cell (default: one).
        Blocked cells cannot be entered. Start is always included at zero
        cost, even if blocked, so callers can pass all occupied positions.
        ``budget`` must be finite and nonnegative. Invalid budgets, explored
        costs, or a start outside the grid raise ``ValueError``.
        """
        if not math.isfinite(budget) or budget < 0:
            raise ValueError("Movement budget must be nonnegative and finite")
        distances, _ = self._search(start, budget, blocked, cost)
        return distances

    def path(self, start: Cell, goal: Cell, *, blocked: Iterable[Cell] = (),
             cost: Callable[[Cell], float] | None = None) -> list[Cell]:
        """Return a cheapest route including both endpoints, or ``[]``.

        Terrain costs and blockers work as in :meth:`reachable`. A blocked
        or disconnected goal has no route; ``start == goal`` returns start.
        A start or goal outside the grid raises ``ValueError``.
        """
        _, previous = self._search(start, math.inf, blocked, cost, goal)
        if goal != start and goal not in previous:
            return []
        route = [goal]
        while route[-1] != start:
            route.append(previous[route[-1]])
        route.reverse()
        return route

    def _search(self, start: Cell, budget: float, blocked: Iterable[Cell],
                cost: Callable[[Cell], float] | None,
                goal: Cell | None = None) -> tuple[dict[Cell, float], dict[Cell, Cell]]:
        if start not in self.cells:
            raise ValueError(f"start cell {start} is outside the grid")
        if goal is not None and goal not in self.cells:
            raise ValueError(f"goal cell {goal} is outside the grid")
        blocked = frozenset(blocked)
        distances = {start: 0.0}
        previous: dict[Cell, Cell] = {}
        queue = [(0.0, start)]
        while queue:
            distance, cell = heapq.heappop(queue)
            if distance != distances[cell]:
                continue
            if cell == goal:
                break
            for neighbor in self.neighbors(cell):
                if neighbor in blocked:
                    continue
                step = cost(neighbor) if cost is not None else 1.0
                if not math.isfinite(step) or step <= 0:
                    raise ValueError(f"Movement cost for {neighbor} must be positive and finite, got {step}")
                total = distance + step
                if total <= budget and total < distances.get(neighbor, math.inf):
                    distances[neighbor] = total
                    previous[neighbor] = cell
                    heapq.heappush(queue, (total, neighbor))
        return distances, previous
