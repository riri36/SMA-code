"""Vector pygame helpers for the calibration screen (card, progress, sensor glyphs)."""

from __future__ import annotations

import math
import pygame


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_rounded_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fill: tuple[int, int, int],
    border: tuple[int, int, int],
    radius: int = 14,
) -> None:
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    pygame.draw.rect(surface, border, rect, width=1, border_radius=radius)


def draw_title_card(
    surface: pygame.Surface,
    center_x: int,
    top: int,
    title_surf: pygame.Surface,
    subtitle_surf: pygame.Surface | None,
    *,
    card_fill: tuple[int, int, int] = (52, 58, 70),
    card_border: tuple[int, int, int] = (78, 86, 102),
    padding_x: int = 22,
    padding_y: int = 14,
) -> pygame.Rect:
    tw = title_surf.get_width()
    th = title_surf.get_height()
    sh = subtitle_surf.get_height() if subtitle_surf else 0
    sw = subtitle_surf.get_width() if subtitle_surf else 0
    inner_w = max(tw, sw)
    inner_h = th + (8 + sh if subtitle_surf else 0)
    rect = pygame.Rect(0, 0, inner_w + 2 * padding_x, inner_h + 2 * padding_y)
    rect.centerx = center_x
    rect.top = top
    draw_rounded_panel(surface, rect, card_fill, card_border, radius=16)
    surface.blit(title_surf, (rect.x + padding_x, rect.y + padding_y))
    if subtitle_surf:
        surface.blit(
            subtitle_surf,
            (rect.x + padding_x, rect.y + padding_y + th + 8),
        )
    return rect


def draw_smooth_progress(
    surface: pygame.Surface,
    rect: pygame.Rect,
    progress: float,
    *,
    track: tuple[int, int, int] = (38, 42, 50),
    fill_lo: tuple[int, int, int] = (46, 160, 67),
    fill_hi: tuple[int, int, int] = (120, 220, 140),
    radius: int = 10,
) -> None:
    pygame.draw.rect(surface, track, rect, border_radius=radius)
    p = max(0.0, min(1.0, float(progress)))
    if p <= 0.0:
        return
    fill_w = max(6, int(rect.width * p))
    inner = pygame.Rect(rect.left, rect.top, min(fill_w, rect.width), rect.height)
    stripes = min(24, max(6, inner.width // 8))
    stripe_w = max(1, inner.width // stripes)
    clip_prev = surface.get_clip()
    surface.set_clip(inner)
    for i in range(stripes):
        t = i / max(1, stripes - 1)
        col = _blend(fill_lo, fill_hi, t)
        x0 = inner.left + i * stripe_w
        seg = pygame.Rect(x0, inner.top, min(stripe_w + 1, inner.right - x0), inner.height)
        pygame.draw.rect(surface, col, seg)
    surface.set_clip(clip_prev)
    pygame.draw.rect(surface, (24, 100, 45), inner, width=1, border_radius=radius)


def _ring(surface: pygame.Surface, center: tuple[int, int], r_outer: int, r_inner: int, color: tuple[int, int, int, int]) -> None:
    w = r_outer * 2 + 2
    ring = pygame.Surface((w, w), pygame.SRCALPHA)
    pygame.draw.circle(ring, color, (w // 2, w // 2), r_outer)
    pygame.draw.circle(ring, (0, 0, 0, 0), (w // 2, w // 2), r_inner)
    surface.blit(ring, (center[0] - w // 2, center[1] - w // 2))


def draw_emg_glyph(
    surface: pygame.Surface,
    center: tuple[int, int],
    radius: int,
    active: bool,
) -> None:
    base = (70, 150, 255, 220)
    glow = (255, 230, 120, 110) if active else (120, 180, 255, 70)
    _ring(surface, center, radius + 5, radius + 1, glow)
    _ring(surface, center, radius + 1, radius - 2, (*base[:3], 180))
    pygame.draw.circle(surface, base[:3], center, max(4, radius - 4))
    # Waveform stroke inside
    cx, cy = center
    pts: list[tuple[int, int]] = []
    for i in range(-radius + 2, radius - 1, 3):
        x = cx + i
        y = cy + int(math.sin(i * 0.18) * (radius * 0.35))
        pts.append((x, y))
    if len(pts) > 1:
        pygame.draw.lines(surface, (240, 248, 255), False, pts, 2)


def draw_ball_glyph(
    surface: pygame.Surface,
    center: tuple[int, int],
    radius: int,
    active: bool,
) -> None:
    outer_glow = (255, 170, 90, 120) if active else (255, 140, 60, 75)
    _ring(surface, center, radius + 6, radius + 2, outer_glow)
    pygame.draw.circle(surface, (255, 120, 50), center, radius)
    pygame.draw.circle(surface, (255, 200, 160), center, radius, width=2)
    pygame.draw.circle(surface, (40, 40, 45), center, max(3, radius // 3))


def draw_sensor_node(
    surface: pygame.Surface,
    label: str,
    center: tuple[int, int],
    radius: int,
    active: bool,
    font: pygame.font.Font,
    *,
    kind: str,
) -> None:
    if kind.lower() == "ball":
        draw_ball_glyph(surface, center, radius, active)
    else:
        draw_emg_glyph(surface, center, radius, active)
    label_surf = font.render(label, True, (230, 232, 238))
    lr = label_surf.get_rect(center=(center[0], center[1] + radius + 16))
    surface.blit(label_surf, lr)
