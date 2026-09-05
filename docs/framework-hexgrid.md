# HexGrid: one map for drawing, picking and navigation

`HexGrid` is a finite set of axial `(q, r)` coordinates. It owns pointy-top
hex geometry and cheapest-route search. Your game supplies the cells,
blocked positions and entry costs; it keeps its own units, turns and rules.
Import it from `saga2d`, with no backend setup required.

## Layout and picking

```python
from saga2d import HexGrid

cells = {(q, r) for q in range(5) for r in range(4)}
grid = HexGrid(cells, size=28, origin=(70, 90))

position = grid.center((2, 1))
polygon = grid.corners((2, 1))
assert len(polygon) == 6
assert grid.cell_at(*position) == (2, 1)
assert grid.cell_at(-1000, -1000) is None
assert HexGrid.distance((0, 0), (2, 1)) == 3
```

`size` is the center-to-corner radius in world units; `origin` is the center
of `(0, 0)`. Coordinates follow Saga2D's y-down convention. A grid can have
holes or disconnected regions. `center` and `corners` work outside the map;
`cell_at` returns a cell only if it belongs to the map. Points exactly on a
shared boundary are assigned deterministically to a touching hex.

## Range and weighted routes

```python
from saga2d import HexGrid

grid = HexGrid((q, r) for q in range(5) for r in range(4))
start, destination = (0, 1), (3, 1)
occupied = {start, (2, 1)}
rough = {(1, 1), (1, 2)}

def entry_cost(cell):
    return 3 if cell in rough else 1

costs = grid.reachable(start, 5, blocked=occupied, cost=entry_cost)
route = grid.path(start, destination, blocked=occupied, cost=entry_cost)
assert costs[start] == 0
assert route[0] == start and route[-1] == destination
assert sum(entry_cost(cell) for cell in route[1:]) == costs[destination]
assert not set(route[1:]) & occupied
```

`reachable` returns a dictionary of minimum costs, including the start at
zero. Remove the start if your UI should highlight destinations only. The
start can be in `blocked`, so passing all occupied cells is convenient.
`path` includes both endpoints, returns `[]` for a blocked or disconnected
destination, and has no movement-budget limit. Check the returned cost
against your budget when accepting a command. Neither search alters the
map or moves a game object.

Costs default to one per entry and must be positive and finite. A reachable
budget must be finite and nonnegative. Invalid arguments raise `ValueError`;
an out-of-map start or goal is a caller error. `distance` counts geometric
hex steps and ignores terrain, blockers and holes.

## A complete scene

Save this as `hex_demo.py` in the repository root and run
`uv run python hex_demo.py`. Click a hex to preview a two-step range. This
uses only Saga2D; there are no campaign or combat rules in the example.

```python
from saga2d import Camera, Game, HexGrid, RenderLayer, Scene

class HexDemo(Scene):
    background_color = (18, 24, 32, 255)

    def on_enter(self):
        self.camera = Camera(self.game.resolution)
        self.grid = HexGrid(
            ((q, r) for q in range(5) for r in range(4)),
            size=28, origin=(70, 90),
        )
        self.selected = (0, 0)

    def handle_input(self, event):
        if event.type == "click" and event.button == "left":
            cell = self.grid.cell_at(event.world_x, event.world_y)
            if cell is not None:
                self.selected = cell
                return True
        return False

    def draw(self):
        costs = self.grid.reachable(self.selected, 2)
        for cell in sorted(self.grid.cells):
            color = (48, 114, 138, 255) if cell in costs else (42, 53, 68, 255)
            corners = self.grid.corners(cell)
            self.draw_polygon(corners, color, space="world", layer=RenderLayer.BACKGROUND)
            for a, b in zip(corners, corners[1:] + corners[:1]):
                self.draw_line(*a, *b, (18, 24, 32, 255), space="world", layer=RenderLayer.OBJECTS)
            x, y = self.grid.center(cell)
            label = str(int(costs[cell])) if cell in costs else "·"
            self.draw_text(label, x, y, anchor_x="center", space="world")
        self.draw_text("Click a hex to preview two-step movement", 20, 30, font_size=16)

if __name__ == "__main__":
    Game("Hex demo", resolution=(480, 340)).run(HexDemo())
```

Drawing in `world` space and picking `event.world_x/world_y` keeps the two
operations consistent when the camera pans or zooms. For a screen-space
board, draw in `screen` space and use `event.x/y` instead.
Tiles use the background layer, grid edges use the objects layer, and
labels use the default world-UI layer so their centers stay above tile fills.

The primitive removes repeated hex math and search bookkeeping without
prescribing a particular game. It can serve a puzzle board, a route planner,
or a tactical field. Unit selection, whether a destination is legal, and
what happens on arrival belong to the caller. See
[the architecture](../DESIGN.md) and [the Eador client](../eador/README.md).
