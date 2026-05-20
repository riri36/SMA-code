"""
Visual tokens for the Labelit-style shell.

Window chrome aligns with Flutter reference (~#F5F5F7). Finger bar colors follow
the requested thumb / index / middle / ring / pinky palette (distinct hues).
"""

from __future__ import annotations

from dataclasses import dataclass

from ui.theme import HapticTheme, default_light_theme


@dataclass(frozen=True)
class FingerColors:
    thumb: tuple[int, int, int] = (46, 204, 113)
    index: tuple[int, int, int] = (52, 152, 219)
    middle: tuple[int, int, int] = (230, 126, 34)
    ring: tuple[int, int, int] = (231, 76, 60)
    pinky: tuple[int, int, int] = (26, 188, 156)


FINGER_COLORS = FingerColors()

# Soft card shadow (RGBA blit)
CARD_SHADOW_RGBA = (0, 0, 0, 28)

# Stim mode chips (visual only unless future config wires them)
MODE_CHIP_LABELS: tuple[str, ...] = ("Constant", "Dynamic", "Burst", "Pulse")


def labelit_theme() -> HapticTheme:
    """Light chrome compatible with legacy ``HapticTheme`` consumers."""
    return default_light_theme()
