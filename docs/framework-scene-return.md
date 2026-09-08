# Return to a retained scene

Use `game.pop_to(scene)` to dismiss every overlay above a scene that is
already on the stack. The target keeps its identity, UI and owned resources.
Each removed scene closes normally, and only the target receives `on_reveal`.

```python
from saga2d import Scene


class Confirmation(Scene):
    controls = {"enter": "confirm"}

    def __init__(self, editor):
        self.editor = editor

    def confirm(self):
        self.editor.apply_changes()
        self.game.pop_to(self.editor)
```

An editor can have a settings page and confirmation above it. Returning in
one operation avoids revealing settings that the accepted change has already
made obsolete. Repeated `pop()` calls would reveal each intermediate page;
a loop based on `game.scene` would also fail while input defers transitions.

Like `push` and `pop`, a return requested during input, update or a lifecycle
hook takes effect after that phase or hook. The target is matched by identity
when the operation applies. An absent target raises `ValueError` before any
scene is removed; returning to the current top is a no-op. The game chooses
which screen should remain and when its underlying state needs refreshing.
