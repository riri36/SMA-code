"""IMU placeholder (no IMU stack in this repository)."""

from __future__ import annotations

from typing import Any

import pygame

from LabelitStyle_Code.shell import draw_card
from LabelitStyle_Code.theme import labelit_theme


def draw_imu_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fonts: dict[str, pygame.font.Font],
    ctx: dict[str, Any],
) -> None:
    theme = ctx.get("theme") or labelit_theme()
    surface.fill(theme.content_bg)
    margin = 12
    card = pygame.Rect(rect.x + margin, rect.y + margin, rect.width - 2 * margin, rect.height - 2 * margin)
    draw_card(surface, theme, card)
    t = fonts["title"].render("IMU", True, theme.text)
    surface.blit(t, (card.x + 14, card.y + 12))
    lines = [
        "No IMU fusion module ships with VerticalJumpPython.",
        "This tab preserves navigation parity with the Flutter shell.",
    ]
    y = card.y + 48
    for line in lines:
        r = fonts["body"].render(line, True, theme.subtext)
        surface.blit(r, (card.x + 14, y))
        y += r.get_height() + 6
