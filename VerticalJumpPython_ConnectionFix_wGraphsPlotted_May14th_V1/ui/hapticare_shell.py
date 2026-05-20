"""
Bottom navigation chrome modeled after Flutter `haptic_app.dart` `_buildMobileLayout`.

Icons are approximated with ASCII-safe glyphs (default pygame font has no Material icons).
"""

from __future__ import annotations

import math

import pygame

from ui.theme import HapticTheme

NAV_HEIGHT = 64

# Order matches Flutter PageView / bottomNavigationBar: Insights … Settings.
NAV_LABELS: tuple[str, ...] = (
    "Insights",
    "Graphs",
    "Dashboard",
    "Games",
    "IMU",
    "Settings",
)

# Tiny stand-ins for Material icons (insights, assessment, dashboard, esports, 3d, settings).
NAV_GLYPHS: tuple[str, ...] = ("*", "#", "D", "G", "3", "S")


def content_rect(full_width: int, full_height: int) -> pygame.Rect:
    h = max(1, full_height - NAV_HEIGHT)
    return pygame.Rect(0, 0, full_width, h)


def nav_hit_test(
    pos: tuple[int, int], full_width: int, full_height: int
) -> int | None:
    x, y = pos
    if y < full_height - NAV_HEIGHT:
        return None
    n = len(NAV_LABELS)
    cell = full_width / n
    if x < 0 or x >= full_width:
        return None
    idx = int(x // cell)
    if idx < 0 or idx >= n:
        return None
    return idx


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
    shadow = pygame.Rect(0, nav_y - 3, fw, 3)
    shadow_surf = pygame.Surface((fw, 3), pygame.SRCALPHA)
    for i in range(3):
        a = 35 - i * 10
        shadow_surf.fill((0, 0, 0, max(0, a)), (0, i, fw, 1))
    screen.blit(shadow_surf, shadow.topleft)
    pygame.draw.rect(screen, theme.nav_bar, nav_rect)
    pygame.draw.line(screen, (220, 222, 228), (0, nav_y), (fw, nav_y))

    n = len(NAV_LABELS)
    cell_w = fw / n
    for i, (label, glyph) in enumerate(zip(NAV_LABELS, NAV_GLYPHS)):
        active = i == active_index
        color = theme.accent if active else theme.nav_inactive
        cx = int(i * cell_w + cell_w / 2)
        cell_left = int(i * cell_w)
        cell_w_int = int(math.ceil((i + 1) * cell_w)) - cell_left
        cell_rect = pygame.Rect(cell_left, nav_y, cell_w_int, NAV_HEIGHT)
        if active:
            pill = cell_rect.inflate(-8, -14)
            pill.top += 2
            drop = pygame.Surface((pill.w + 4, pill.h + 4), pygame.SRCALPHA)
            pygame.draw.rect(
                drop,
                (0, 0, 0, 22),
                pygame.Rect(3, 3, pill.w, pill.h),
                border_radius=14,
            )
            screen.blit(drop, (pill.left - 2, pill.top - 2))
            surf = pygame.Surface(pill.size, pygame.SRCALPHA)
            pygame.draw.rect(
                surf,
                (*theme.accent[:3], 38),
                surf.get_rect(),
                border_radius=14,
            )
            pygame.draw.rect(
                surf,
                (*theme.accent[:3], 200),
                surf.get_rect(),
                width=1,
                border_radius=14,
            )
            screen.blit(surf, pill.topleft)
        g = font_small.render(glyph, True, color)
        gr = g.get_rect(center=(cx, nav_y + 22))
        screen.blit(g, gr)
        t = font_tiny.render(label, True, color)
        tr = t.get_rect(center=(cx, nav_y + 46))
        screen.blit(t, tr)


def draw_card_frame(
    surface: pygame.Surface,
    theme: HapticTheme,
    margin: int = 10,
    radius: int = 10,
) -> pygame.Rect:
    """Draw a simple card panel inside surface; returns inner rect for content."""
    w, h = surface.get_size()
    outer = pygame.Rect(margin, margin, w - 2 * margin, h - 2 * margin)
    if outer.width <= 0 or outer.height <= 0:
        return surface.get_rect()
    drop = outer.move(3, 4)
    drop_s = pygame.Surface((drop.w + 2, drop.h + 2), pygame.SRCALPHA)
    pygame.draw.rect(
        drop_s,
        (0, 0, 0, 26),
        pygame.Rect(1, 1, drop.w, drop.h),
        border_radius=radius + 2,
    )
    surface.blit(drop_s, (drop.left - 1, drop.top - 1))
    _rounded_rect(surface, theme.card, outer, radius)
    pygame.draw.rect(surface, (220, 220, 222), outer, width=1, border_radius=radius)
    inner = outer.inflate(-18, -18)
    return inner


def draw_placeholder(
    surface: pygame.Surface,
    theme: HapticTheme,
    title: str,
    lines: list[str],
    font_title: pygame.font.Font,
    font_body: pygame.font.Font,
) -> None:
    surface.fill(theme.content_bg)
    inner = draw_card_frame(surface, theme)
    y = inner.y + 8
    tt = font_title.render(title, True, theme.text)
    surface.blit(tt, (inner.x + 8, y))
    y += tt.get_height() + 12
    for line in lines:
        bt = font_body.render(line, True, theme.subtext)
        surface.blit(bt, (inner.x + 8, y))
        y += bt.get_height() + 6


def _rounded_rect(
    surf: pygame.Surface,
    color: tuple[int, int, int],
    rect: pygame.Rect,
    radius: int,
) -> None:
    pygame.draw.rect(surf, color, rect, border_radius=radius)
