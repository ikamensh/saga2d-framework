# One button declaration for pointer and keyboard

Use `shortcut` when a key should activate the button itself:

```python
self.ui.add(Button("Equip", shortcut="1", on_click=lambda: self.equip(relic),
                   enabled=not equipped))
```

The button draws the keycap, calls its ordinary `on_click` callback on a key
press, and respects its enabled state. Do not also register that key with
`Scene.controls` or `bind_key`. The live UI tree owns the shortcut: replacing
a page, clearing a panel or removing a button also removes its shortcut.
Nothing needs to be unbound.

For several keys that perform the same button action, pass a tuple:

```python
Button("Continue", shortcut=("Enter", "Space"), on_click=self.continue_game)
Button("Recover backup", shortcut="Shift+1", on_click=self.recover)
```

The first alias is displayed. Key names are case insensitive, with
`Enter`/`Return` and `Esc`/`Escape` accepted interchangeably. Other keys use
Saga2D's ordinary names, such as `Space`, `Tab`, `Left`, `F5`, `1` and `plus`.
Chords accept `Ctrl`, `Alt`, `Shift` and `Meta` in any order and match modifiers
exactly. `Shift+1` does not activate `1`; a bare button shortcut also does not
capture an unrelated scene chord such as `Ctrl+1`. Empty shortcuts/alias
tuples, missing key names and unknown modifiers are errors.

## Ownership and input order

- Normal UI event handlers retain first refusal. Button shortcuts run next,
  before camera scrolling, scene `controls`/`bind_key`, `handle_input`, and
  `pop_on_cancel`. Only key presses activate them; releases still propagate.
- A visible disabled button consumes its matching shortcut without invoking
  its callback or a scene fallback. Disabling an ancestor has the same effect.
  Hidden buttons or ancestors contribute no shortcuts.
- Only the top scene participates. A transparent overlay may reuse a key
  from the scene it covers. Removing the overlay restores the underlying UI.
- Two visible buttons in the same scene claiming the same normalized shortcut
  raise `ValueError` when that key reaches shortcut dispatch, before either
  callback runs. The error identifies the key and buttons. Disabled buttons
  still reserve their keys; hide or remove an inactive alternative.

`hotkey` remains a **display-only hint** for contextual scene actions. For
example, a map may show “Enter” beside Harvest while its scene's Enter command
chooses between moving, attacking and harvesting according to the cursor.
Use `hotkey="Enter"` for that hint and keep the contextual command in the
scene. Supplying both `hotkey` and `shortcut` is an error. Existing callers
that use only `hotkey` retain their behavior.

This distinction keeps game rules in the game. Buttons know whether they are
enabled; they do not compute prices, legal moves or disabled-action reasons.
The game remains responsible for valid model commands and explanations.

## Run the independent example

```sh
uv run python tools/demo_button_shortcuts.py
```

The [counter demo](../tools/demo_button_shortcuts.py) imports neither game.
Enter/Space increments to a limit; Tab replaces three presets with a one-item
page; Help opens a real scene overlay that temporarily owns Enter. It uses no
`controls`, `bind_key` or `unbind_key` declarations.

Public behavior tests in `tests/framework/test_button_shortcuts.py` exercise
the same input path with the mock backend. Native pyglet verification checks
Enter, Esc, number keys, modifier chords, disabled controls, page replacement,
overlay closure and the resulting rendered keycaps.
