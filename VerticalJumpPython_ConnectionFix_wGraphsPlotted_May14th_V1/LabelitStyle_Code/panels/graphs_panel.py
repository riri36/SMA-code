"""Graphs tab: stacked mini charts, REC affordance, recording action (stub)."""

from __future__ import annotations

from typing import Any

import pygame

from LabelitStyle_Code.shell import draw_card
from LabelitStyle_Code.theme import labelit_theme


def _series_from_buffer(buf: list[Any], key_candidates: tuple[str, ...], n: int) -> list[float]:
    if not buf:
        return [0.0] * n
    tail = buf[-n:]
    out: list[float] = []
    for row in tail:
        if not isinstance(row, dict):
            continue
        val = None
        for k in key_candidates:
            if k in row and isinstance(row[k], (int, float)):
                val = float(row[k])
                break
        if val is None:
            continue
        out.append(max(0.0, min(1.0, val)))
    if len(out) < n:
        pad_val = out[-1] if out else 0.0
        out = [pad_val] * (n - len(out)) + out
    return out[-n:]


def _draw_sparkline(
    rect: pygame.Rect,
    target: pygame.Surface,
    series: list[float],
    color: tuple[int, int, int],
    fill_a: int = 85,
) -> None:
    if len(series) < 2:
        return
    w, h = rect.width, rect.height
    pts: list[tuple[int, int]] = []
    denom = max(1, len(series) - 1)
    for i, v in enumerate(series):
        x = rect.x + int(i * (w - 1) / denom)
        yy = rect.y + 2 + int((h - 4) * (1.0 - v))
        pts.append((x, yy))
    fill_s = pygame.Surface((w, h), pygame.SRCALPHA)
    rel = [(p[0] - rect.x, p[1] - rect.y) for p in pts]
    poly = [(0, h)] + rel + [(w, h)]
    pygame.draw.polygon(fill_s, (*color[:3], fill_a), poly)
    target.blit(fill_s, rect.topleft)
    pygame.draw.lines(target, color, False, pts, 2)


def draw_graphs_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fonts: dict[str, pygame.font.Font],
    ctx: dict[str, Any],
) -> pygame.Rect | None:
    """
    Stacked mini line-chart regions; REC badge; primary stop button (stub).

    TODO: Legacy exposes continuous CSV logging via ``EMGGameController`` / fusion buffers,
    not a discrete "stop recording" API. Wire this button to an explicit session export
    or pipeline toggle when that exists.
    """
    theme = ctx.get("theme") or labelit_theme()
    surface.fill(theme.content_bg)
    margin = 10
    title = fonts["title"].render("Graphs", True, theme.text)
    surface.blit(title, (rect.x + margin, rect.y + margin))

    ctrl = ctx.get("controller")
    fusion = getattr(ctrl, "fusion_pipeline", None) if ctrl else None
    raw_buf = list(getattr(fusion, "processed_emg_buffer", []) or []) if fusion else []
    force_buf = list(getattr(fusion, "ball_force_buffer", []) or []) if fusion else []

    left_series = _series_from_buffer(
        raw_buf, ("left_processed", "rms1", "emg1"), 48
    )
    right_series = _series_from_buffer(
        raw_buf, ("right_processed", "rms2", "emg2"), 48
    )
    force_series = _series_from_buffer(
        force_buf, ("force_rms", "force_raw"), 48
    )

    y0 = rect.y + margin + title.get_height() + 8
    card = pygame.Rect(
        rect.x + margin, y0, rect.width - 2 * margin, min(240, rect.height - (y0 - rect.y) - margin)
    )
    draw_card(surface, theme, card)

    game = ctx.get("game")
    state = getattr(game, "state", None)
    state_name = getattr(state, "name", str(state))
    rec_active = fusion is not None and state_name == "PLAYING"
    pill = pygame.Rect(card.x + 14, card.y + 12, 54, 22)
    pygame.draw.rect(
        surface, (220, 80, 80) if rec_active else (180, 180, 180), pill, border_radius=11
    )
    rec_t = fonts["tiny"].render("REC" if rec_active else "OFF", True, (255, 255, 255))
    surface.blit(rec_t, rec_t.get_rect(center=pill.center))

    pct = ctx.get("graphs_header_percent")
    if pct is None and game is not None:
        pct = getattr(game, "threshold_percent_value", None)
    if pct is not None:
        hdr = fonts["body"].render(f"{int(pct)}% MVC target", True, theme.subtext)
        surface.blit(hdr, (pill.right + 12, pill.y + 2))

    row_h = 40
    r1 = pygame.Rect(card.x + 12, card.y + 44, card.width - 24, row_h)
    r2 = pygame.Rect(r1.x, r1.bottom + 6, r1.width, row_h)
    r3 = pygame.Rect(r2.x, r2.bottom + 6, r2.width, row_h)
    _draw_sparkline(r1, surface, left_series, (52, 152, 219))
    _draw_sparkline(r2, surface, right_series, (155, 89, 182))
    _draw_sparkline(r3, surface, force_series, (241, 196, 15))

    lbl1 = fonts["tiny"].render("Left processed", True, theme.subtext)
    lbl2 = fonts["tiny"].render("Right processed", True, theme.subtext)
    lbl3 = fonts["tiny"].render("Ball force RMS / raw", True, theme.subtext)
    surface.blit(lbl1, (r1.x + 4, r1.y + 2))
    surface.blit(lbl2, (r2.x + 4, r2.y + 2))
    surface.blit(lbl3, (r3.x + 4, r3.y + 2))

    btn = pygame.Rect(card.x + 12, r3.bottom + 14, card.width - 24, 44)
    pygame.draw.rect(surface, (200, 60, 60), btn, border_radius=10)
    bt = fonts["body"].render("STOP RECORDING (stub)", True, (255, 255, 255))
    surface.blit(bt, bt.get_rect(center=btn.center))

    game = ctx.get("game")
    if game is not None:
        setattr(game, "_labelit_graph_stop_btn", btn)

    hint = fonts["tiny"].render(
        "TODO: no explicit record/stop API on EMGGameController; click is a no-op stub.",
        True,
        theme.subtext,
    )
    surface.blit(hint, (card.x + 12, btn.bottom + 8))

    return btn
