"""Rendering primitives: layers, anchors, sprites, camera, particles (Stage 2+)."""

from saga2d.rendering.camera import Camera
from saga2d.rendering.color_swap import ColorSwap, get_palette, register_palette
from saga2d.rendering.layers import RenderLayer, SpriteAnchor
from saga2d.rendering.particles import ParticleEmitter
from saga2d.rendering.sprite import Sprite

__all__ = [
    "Camera",
    "ColorSwap",
    "ParticleEmitter",
    "RenderLayer",
    "Sprite",
    "SpriteAnchor",
    "get_palette",
    "register_palette",
]
