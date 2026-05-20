"""Sessions tab: cards from scanned ``GameData`` session folders."""

from __future__ import annotations

from typing import Any

import pygame

from LabelitStyle_Code.session_browser import load_calibration_peaks
from LabelitStyle_Code.shell import draw_card
from LabelitStyle_Code.theme import labelit_theme


def _mini_timeline(area: pygame.Rect, target: pygame.Surface, jumps: int) -> None:
    """Simple horizontal tick marks for 'activity' (jump count scaled)."""
    n = min(24, max(4, jumps + 2))
    for i in range(n):
        x = area.x + 8 + i * (area.width - 16) // max(1, n - 1)
        h = 6 + (i * 7) % 18
        pygame.draw.line(
            target, (120, 130, 150), (x, area.bottom - 8), (x, area.bottom - 8 - h), 2
        )


def draw_sessions_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fonts: dict[str, pygame.font.Font],
    ctx: dict[str, Any],
) -> None:
    theme = ctx.get("theme") or labelit_theme()
    surface.fill(theme.content_bg)
    margin = 8
    title = fonts["title"].render("Sessions", True, theme.text)
    surface.blit(title, (rect.x + margin, rect.y + margin))

    sessions = ctx.get("sessions") or []
    y = rect.y + margin + title.get_height() + 10
    card_w = rect.width - 2 * margin
    for rec in sessions[:4]:
        h = 118
        if y + h > rect.bottom - margin:
            break
        card_r = pygame.Rect(rect.x + margin, y, card_w, h)
        draw_card(surface, theme, card_r)
        line1 = fonts["body"].render(f"{rec.user_id} / {rec.session_id}", True, theme.text)
        surface.blit(line1, (card_r.x + 14, card_r.y + 10))
        dur = rec.summary.get("duration")
        dur_s = f"{float(dur):.0f}s" if isinstance(dur, (int, float)) else "—"
        line2 = fonts["tiny"].render(
            f"Jumps (est.): {rec.jump_count_estimate}   Duration: {dur_s}",
            True,
            theme.subtext,
        )
        surface.blit(line2, (card_r.x + 14, card_r.y + 36))
        peaks = load_calibration_peaks(rec.path)
        mvc_l = peaks.get("mvc_left_peak", peaks.get("mvc_left"))
        mvc_r = peaks.get("mvc_right_peak", peaks.get("mvc_right"))
        ext_line = fonts["tiny"].render(
            f"Finger extension proxy: L={mvc_l or '—'}  R={mvc_r or '—'} (calibration peaks)",
            True,
            theme.subtext,
        )
        surface.blit(ext_line, (card_r.x + 14, card_r.y + 56))
        max_grip = peaks.get("mvc_force_peak")
        g_line = fonts["tiny"].render(
            f"Max grip (ball peak): {max_grip if max_grip is not None else '—'}",
            True,
            theme.subtext,
        )
        surface.blit(g_line, (card_r.x + 14, card_r.y + 74))
        tl = pygame.Rect(card_r.x + 12, card_r.y + 92, card_r.width - 24, 18)
        pygame.draw.rect(surface, (236, 238, 242), tl, border_radius=6)
        _mini_timeline(tl, surface, rec.jump_count_estimate)
        y += h + margin

    if not sessions:
        empty = fonts["body"].render("No sessions found under GameData yet.", True, theme.subtext)
        surface.blit(empty, (rect.x + margin, y))
