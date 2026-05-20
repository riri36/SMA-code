"""
Bottom navigation, cards, and layout helpers (Sessions-first naming).

Geometry matches ``ui.hapticare_shell`` (56px bar) so legacy ``nav_hit_test`` stays valid.
"""

from __future__ import annotations

import pygame

from ui.hapticare_shell import NAV_HEIGHT, content_rect, nav_hit_test
from ui.theme import HapticTheme

# Order matches user spec: Sessions, Graphs, Dashboard, Games, IMU, Settings.
NAV_LABELS: tuple[str, ...] = (
    "Sessions",
    "Graphs",
    "Dashboard",
    "Games",
    "IMU",
    "Settings",
)

NAV_GLYPHS: tuple[str, ...] = ("S", "#", "D", "G", "3", "i")


def draw_soft_shadow(
    target: pygame.Surface, rect: pygame.Rect, radius: int, spread: int = 3
) -> None:
    """Subtle drop shadow under a rounded card."""
    for i in range(spread):
        alpha = max(8, 40 - i * 10)
        inset = i
        r = pygame.Rect(rect.x, rect.y + 2 + i, rect.width, rect.height)
        surf = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(surf, (0, 0, 0, alpha), surf.get_rect(), border_radius=max(2, radius - inset))
        target.blit(surf, r.topleft)


def draw_card(
    target: pygame.Surface,
    theme: HapticTheme,
    rect: pygame.Rect,
    *,
    radius: int = 14,
    border: tuple[int, int, int] | None = None,
) -> pygame.Rect:
    """White rounded card with light border; returns the same rect for convenience."""
    draw_soft_shadow(target, rect, radius)
    pygame.draw.rect(target, theme.card, rect, border_radius=radius)
    b = border or (230, 230, 232)
    pygame.draw.rect(target, b, rect, width=1, border_radius=radius)
    return rect


def draw_bottom_nav(
    screen: pygame.Surface,
    theme: HapticTheme,
    active_index: int,
    font_small: pygame.font.Font,
    font_tiny: pygame.font.Font,
) -> None:
    fw, fh = screen.get_size()
    nav_y = fh - NAV_HEIGHT
    nav_rect = pygame.Rect(0, nav_y, fw, NAV_HEIGHT)
    shadow_surf = pygame.Surface((fw, 2), pygame.SRCALPHA)
    shadow_surf.fill((0, 0, 0, 20))
    screen.blit(shadow_surf, (0, nav_y - 2))
    pygame.draw.rect(screen, theme.nav_bar, nav_rect)
    pygame.draw.line(screen, (230, 230, 230), (0, nav_y), (fw, nav_y))

    n = len(NAV_LABELS)
    cell_w = fw / n
    for i, (label, glyph) in enumerate(zip(NAV_LABELS, NAV_GLYPHS)):
        active = i == active_index
        color = theme.accent if active else theme.nav_inactive
        cx = int(i * cell_w + cell_w / 2)
        g = font_small.render(glyph, True, color)
        gr = g.get_rect(center=(cx, nav_y + 16))
        screen.blit(g, gr)
        t = font_tiny.render(label, True, color)
        tr = t.get_rect(center=(cx, nav_y + 38))
        screen.blit(t, tr)


__all__ = [
    "NAV_HEIGHT",
    "NAV_LABELS",
    "NAV_GLYPHS",
    "content_rect",
    "nav_hit_test",
    "draw_bottom_nav",
    "draw_card",
    "draw_soft_shadow",
]
