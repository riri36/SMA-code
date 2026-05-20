"""Games tab placeholder when user is away from live gameplay workflow."""

from __future__ import annotations

from typing import Any

import pygame

from LabelitStyle_Code.shell import NAV_LABELS, draw_card
from LabelitStyle_Code.theme import labelit_theme


def draw_games_panel(
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
    wf = ctx.get("workflow_tab", 3)
    title = fonts["title"].render("Games", True, theme.text)
    surface.blit(title, (card.x + 14, card.y + 12))
    body = fonts["body"].render(
        f"Live EMG jump flow is on tab: {NAV_LABELS[int(wf)]}.",
        True,
        theme.subtext,
    )
    surface.blit(body, (card.x + 14, card.y + 48))
    hint = fonts["tiny"].render(
        "Keyboard: SPACE to start / jump, ESC game over, R/Q as on legacy screens.",
        True,
        theme.subtext,
    )
    surface.blit(hint, (card.x + 14, card.y + 78))
