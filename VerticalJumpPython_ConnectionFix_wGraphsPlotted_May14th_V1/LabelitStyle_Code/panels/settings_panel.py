"""Settings placeholder."""

from __future__ import annotations

from typing import Any

import pygame

from LabelitStyle_Code.shell import draw_card
from LabelitStyle_Code.theme import labelit_theme


def draw_settings_panel(
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
    t = fonts["title"].render("Settings", True, theme.text)
    surface.blit(t, (card.x + 14, card.y + 12))
    b1 = fonts["body"].render("Runtime shell only — legacy ``config.py`` is unchanged.", True, theme.subtext)
    surface.blit(b1, (card.x + 14, card.y + 48))
    b2 = fonts["tiny"].render("Future: expose tuning sliders here without touching emg_jump_game.py.", True, theme.subtext)
    surface.blit(b2, (card.x + 14, card.y + 78))
