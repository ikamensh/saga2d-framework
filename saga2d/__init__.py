"""Saga2D — a Python framework for 2D sprite-based games.

Public API re-exports.  Game code imports from here::

    from saga2d import Game, Scene, RenderLayer, SpriteAnchor, AssetManager
    from saga2d import Panel, Label, Button, Anchor, Layout, Style, Theme

Internal modules (backends, rendering internals) are **not** re-exported.
"""

__version__ = "0.1.0"

from saga2d.actions import (
    Action,
    Delay,
    Do,
    FadeIn,
    FadeOut,
    MoveTo,
    Parallel,
    PlayAnim,
    Remove,
    Repeat,
    Sequence,
)
from saga2d.animation import AnimationDef
from saga2d.assets import AssetManager, AssetNotFoundError
from saga2d.audio import AudioManager
from saga2d.backends.base import (
    Event,
    KeyEvent,
    MouseEvent,
    WindowEvent,
)
from saga2d.cursor import CursorManager
from saga2d.game import Game
from saga2d.input import InputEvent, InputManager
from saga2d.rendering import Camera, ColorSwap, get_palette, register_palette
from saga2d.rendering.layers import RenderLayer, SpriteAnchor
from saga2d.rendering.particles import ParticleEmitter
from saga2d.rendering.sprite import Sprite
from saga2d.save import SaveError, SaveManager
from saga2d.scene import Scene
from saga2d.ui import (
    HUD,
    Anchor,
    Button,
    ChoiceScreen,
    Component,
    ConfirmDialog,
    DataTable,
    DragManager,
    Grid,
    ImageBox,
    Label,
    Layout,
    List,
    MessageScreen,
    Panel,
    ProgressBar,
    SaveLoadScreen,
    Style,
    TabGroup,
    TextBox,
    Theme,
    Tooltip,
    compute_anchor_position,
    compute_content_size,
    compute_flow_layout,
)
from saga2d.util.fsm import StateMachine
from saga2d.util.timer import TimerHandle
from saga2d.util.tween import Ease, tween

__all__ = [
    "HUD",
    "Action",
    "Anchor",
    "AnimationDef",
    "AssetManager",
    "AssetNotFoundError",
    "AudioManager",
    "Button",
    "Camera",
    "ChoiceScreen",
    "ColorSwap",
    "Component",
    "ConfirmDialog",
    "CursorManager",
    "DataTable",
    "Delay",
    "Do",
    "DragManager",
    "Ease",
    "Event",
    "FadeIn",
    "FadeOut",
    "Game",
    "Grid",
    "ImageBox",
    "InputEvent",
    "InputManager",
    "KeyEvent",
    "Label",
    "Layout",
    "List",
    "MessageScreen",
    "MouseEvent",
    "MoveTo",
    "Panel",
    "Parallel",
    "ParticleEmitter",
    "PlayAnim",
    "ProgressBar",
    "Remove",
    "RenderLayer",
    "Repeat",
    "SaveError",
    "SaveLoadScreen",
    "SaveManager",
    "Scene",
    "Sequence",
    "Sprite",
    "SpriteAnchor",
    "StateMachine",
    "Style",
    "TabGroup",
    "TextBox",
    "Theme",
    "TimerHandle",
    "Tooltip",
    "WindowEvent",
    "compute_anchor_position",
    "compute_content_size",
    "compute_flow_layout",
    "get_palette",
    "register_palette",
    "tween",
]
