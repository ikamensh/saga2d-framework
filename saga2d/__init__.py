"""Saga2D — a small Python framework for 2D games.

Game code imports from here::

    from saga2d import Game, Scene, Sprite, Camera, Label, Button, Anchor
"""

__version__ = "0.2.0"

import pyglet

# pyglet wraps every GL call in an error check by default; a busy frame makes
# thousands of them.  The option is read when pyglet.gl loads, so it is set
# here, before any backend or font module imports it.
pyglet.options["debug_gl"] = False

from saga2d.actions import Action, Delay, Do, FadeIn, FadeOut, MoveTo, Parallel, PlayAnim, Remove, Repeat, Sequence
from saga2d.animation import AnimationDef
from saga2d.assets import AssetManager, AssetNotFoundError
from saga2d.audio import AudioManager
from saga2d.backends.base import Event, KeyEvent, MouseEvent, WindowEvent
from saga2d.game import Game
from saga2d.hexgrid import HexGrid
from saga2d.input import InputEvent, InputManager
from saga2d.rendering import Camera, ParticleEmitter, RenderLayer, Sprite, SpriteAnchor
from saga2d.save import SaveError, SaveManager
from saga2d.scene import Scene
from saga2d.ui import Anchor, Button, Column, Component, KeyHints, Label, Layout, Minimap, Panel, ProgressBar, Row, Style, TextStyle, Theme
from saga2d.util.collision import Rect, aabb_overlap
from saga2d.util.reactive import ReactiveValue
from saga2d.util.tween import Ease, tween

__all__ = [
    "Action", "Anchor", "AnimationDef", "AssetManager", "AssetNotFoundError", "AudioManager", "Button", "Camera",
    "Column", "Component", "Delay", "Do", "Ease", "Event", "FadeIn", "FadeOut", "Game", "HexGrid", "InputEvent", "InputManager",
    "KeyEvent", "KeyHints", "Label", "Layout", "Minimap", "MouseEvent", "MoveTo", "Panel", "Parallel", "ParticleEmitter", "PlayAnim",
    "ProgressBar", "ReactiveValue", "Rect", "Remove", "RenderLayer", "Repeat", "Row", "SaveError", "SaveManager",
    "Scene", "Sequence", "Sprite", "SpriteAnchor", "Style", "TextStyle", "Theme", "WindowEvent", "aabb_overlap", "tween",
]
