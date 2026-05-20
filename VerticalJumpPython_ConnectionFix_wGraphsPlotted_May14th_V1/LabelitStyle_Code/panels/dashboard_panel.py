"""Dashboard tab: status, mode chips, grip/finger rows, two large metric panels."""

from __future__ import annotations

import math
from typing import Any

import pygame

from LabelitStyle_Code.shell import draw_card
from LabelitStyle_Code.theme import FINGER_COLORS, MODE_CHIP_LABELS, labelit_theme


def _read_fusion_features(ctrl: Any) -> dict[str, float]:
    fusion = getattr(ctrl, "fusion_pipeline", None)
    if not fusion:
        return {}
    lock = getattr(fusion, "_feature_lock", None)
    if lock is None:
        feats = getattr(fusion, "_latest_features", {})
        return dict(feats) if isinstance(feats, dict) else {}
    try:
        with lock:
            feats = getattr(fusion, "_latest_features", {})
            return dict(feats) if isinstance(feats, dict) else {}
    except Exception:
        return {}


def _grip_percent(features: dict[str, float], ctrl: Any) -> float:
    emg_vals = [v for k, v in features.items() if k.startswith("emg.rms.")]
    if emg_vals:
        return max(0.0, min(100.0, max(emg_vals) * 100.0))
    # Fallback: calibration span vs threshold not available live — use getattr noise
    mv = getattr(ctrl, "calibration_values", {}) or {}
    thr = float(mv.get("threshold", 0.3) or 0.3)
    return max(0.0, min(100.0, 100.0 * (1.0 - math.exp(-5.0 * thr))))


def _synthetic_fingers(features: dict[str, float], grip_pct: float) -> list[tuple[str, float, tuple[int, int, int]]]:
    """
    No per-finger hardware in this repo: derive five display channels for UI parity.

    Uses left/right processed RMS keys when present; otherwise spreads ``grip_pct``.
    """
    left = right = grip_pct / 100.0
    for k, v in features.items():
        if "left" in k.lower() or k.endswith("1"):
            left = float(v)
        if "right" in k.lower() or k.endswith("2"):
            right = float(v)
    base = max(0.0, min(1.0, (left + right) / 2.0))
    names = ("Thumb", "Index", "Middle", "Ring", "Pinky")
    colors = (
        FINGER_COLORS.thumb,
        FINGER_COLORS.index,
        FINGER_COLORS.middle,
        FINGER_COLORS.ring,
        FINGER_COLORS.pinky,
    )
    weights = (1.0, 0.95, 1.05, 0.9, 0.85)
    out: list[tuple[str, float, tuple[int, int, int]]] = []
    for i, (nm, w, c) in enumerate(zip(names, weights, colors)):
        v = max(0.0, min(1.0, base * w * (0.85 + 0.05 * i)))
        out.append((nm, v * 100.0, c))
    return out


def draw_dashboard_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fonts: dict[str, pygame.font.Font],
    ctx: dict[str, Any],
) -> None:
    theme = ctx.get("theme") or labelit_theme()
    game = ctx.get("game")
    ctrl = ctx.get("controller")

    surface.fill(theme.content_bg)
    margin = 10
    y = rect.y + margin
    t = fonts["title"].render("Dashboard", True, theme.text)
    surface.blit(t, (rect.x + margin, y))
    y += t.get_height() + 8

    emg_ok = bool(getattr(ctrl, "emg_connection_verified", False)) if ctrl else False
    ball_ok = bool(getattr(ctrl, "ball_connection_verified", False)) if ctrl else False
    row = fonts["body"].render(
        f"EMG: {'Connected' if emg_ok else 'Not verified'}   "
        f"Ball: {'Connected' if ball_ok else 'Not verified'}   "
        f"Battery: unknown (stub)",
        True,
        theme.text,
    )
    surface.blit(row, (rect.x + margin, y))
    y += row.get_height() + 10

    chip_x = rect.x + margin
    for label in MODE_CHIP_LABELS:
        chip = pygame.Rect(chip_x, y, 78, 26)
        pygame.draw.rect(surface, (240, 242, 246), chip, border_radius=8)
        pygame.draw.rect(surface, (210, 214, 220), chip, width=1, border_radius=8)
        ct = fonts["tiny"].render(label, True, theme.subtext)
        surface.blit(ct, ct.get_rect(center=chip.center))
        chip_x += chip.width + 6
    y += 34

    features = _read_fusion_features(ctrl) if ctrl else {}
    grip_pct = _grip_percent(features, ctrl) if ctrl else float(ctx.get("sim_grip_pct", 42.0))
    finger_rows = _synthetic_fingers(features, grip_pct)

    gtxt = fonts["body"].render(f"Grip (fused EMG max): {grip_pct:.0f}%", True, theme.text)
    surface.blit(gtxt, (rect.x + margin, y))
    y += gtxt.get_height() + 6
    ftxt = fonts["tiny"].render(
        "Fingers: synthetic layout (no dedicated finger sensors; see README).",
        True,
        theme.subtext,
    )
    surface.blit(ftxt, (rect.x + margin, y))
    y += ftxt.get_height() + 12

    mid_y = y
    col_gap = 10
    half_w = (rect.width - 2 * margin - col_gap) // 2
    left_card = pygame.Rect(rect.x + margin, mid_y, half_w, rect.bottom - mid_y - margin)
    right_card = pygame.Rect(left_card.right + col_gap, mid_y, half_w, left_card.height)

    draw_card(surface, theme, left_card)
    draw_card(surface, theme, right_card)

    lt = fonts["body"].render("Grip Force", True, theme.text)
    surface.blit(lt, (left_card.x + 12, left_card.y + 10))
    cx, cy = left_card.centerx, left_card.y + left_card.height // 2 + 6
    radius = min(52, left_card.width // 4)
    pygame.draw.circle(surface, (236, 240, 245), (cx, cy), radius)
    pygame.draw.circle(surface, theme.accent, (cx, cy), radius, width=4)
    arc_rect = pygame.Rect(cx - radius + 6, cy - radius + 6, 2 * radius - 12, 2 * radius - 12)
    sweep = int(360 * grip_pct / 100.0)
    if sweep > 0:
        pygame.draw.arc(surface, (46, 204, 113), arc_rect, math.radians(-90), math.radians(-90 + sweep), 6)
    bar = pygame.Rect(left_card.right - 28, left_card.y + 40, 14, left_card.height - 70)
    pygame.draw.rect(surface, (230, 232, 236), bar, border_radius=6)
    fill_h = int(bar.height * grip_pct / 100.0)
    fill = pygame.Rect(bar.x, bar.bottom - fill_h, bar.width, fill_h)
    pygame.draw.rect(surface, (46, 204, 113), fill, border_radius=6)

    rt = fonts["body"].render("Finger Tracking", True, theme.text)
    surface.blit(rt, (right_card.x + 12, right_card.y + 10))

    hand = pygame.Rect(right_card.x + 12, right_card.y + 40, 72, 100)
    pygame.draw.rect(surface, (250, 220, 200), hand, border_radius=10)
    pygame.draw.rect(surface, (200, 180, 160), hand, width=1, border_radius=10)
    hx = hand.right + 14
    bar_left = hx
    bar_w = right_card.right - bar_left - 14
    yy = hand.y + 6
    for name, pct, col in finger_rows:
        lab = fonts["tiny"].render(f"{name}", True, theme.subtext)
        surface.blit(lab, (bar_left, yy))
        track = pygame.Rect(bar_left, yy + 14, bar_w, 10)
        pygame.draw.rect(surface, (236, 238, 242), track, border_radius=5)
        fil = pygame.Rect(track.x, track.y, int(track.width * (pct / 100.0)), track.height)
        pygame.draw.rect(surface, col, fil, border_radius=5)
        val = fonts["tiny"].render(f"{pct:.0f}%", True, theme.text)
        surface.blit(val, (track.right - 36, yy))
        yy += 34
        if yy > right_card.bottom - 20:
            break
