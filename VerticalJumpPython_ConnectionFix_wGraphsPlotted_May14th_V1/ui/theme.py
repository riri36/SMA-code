"""
Approximate Flutter `haptic_app.dart` light-theme colors for pygame.

Reference: _bgColor 0xFFF5F5F7, _cardColor white, active nav blue.shade600.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HapticTheme:
    window_bg: tuple[int, int, int]
    content_bg: tuple[int, int, int]
    card: tuple[int, int, int]
    text: tuple[int, int, int]
    subtext: tuple[int, int, int]
    accent: tuple[int, int, int]
    nav_bar: tuple[int, int, int]
    nav_inactive: tuple[int, int, int]
    game_sky: tuple[int, int, int]
    shadow: tuple[int, int, int]


def default_light_theme() -> HapticTheme:
    return HapticTheme(
        window_bg=(245, 245, 247),
        content_bg=(245, 245, 247),
        card=(255, 255, 255),
        text=(34, 34, 34),
        subtext=(115, 115, 115),
        accent=(30, 136, 229),
        nav_bar=(255, 255, 255),
        nav_inactive=(189, 189, 189),
        game_sky=(135, 206, 235),
        shadow=(0, 0, 0),
    )


def fill_for_gameplay(theme: HapticTheme) -> tuple[int, int, int]:
    return theme.game_sky


def fill_for_shell_screen(theme: HapticTheme) -> tuple[int, int, int]:
    # Legacy EMG Jump screens assume light text; use a dark slate panel inside the light chrome.
    return (43, 48, 58)
