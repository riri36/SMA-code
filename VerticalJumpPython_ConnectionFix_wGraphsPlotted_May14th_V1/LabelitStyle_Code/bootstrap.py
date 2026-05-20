"""
Runtime wiring for the Labelit-style shell.

``REPO_ROOT`` is the VerticalJumpPython directory (parent of this package). We insert it
on ``sys.path`` first. Heavy imports (``pygame``, ``emg_jump_game``) are deferred until
``run()`` so ``import LabelitStyle_Code.bootstrap`` stays lightweight in headless checks.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root = parent of ``LabelitStyle_Code/``
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def data_base_dir() -> Path:
    from config import DATA_LOGGING

    p = Path(DATA_LOGGING["base_directory"])
    return p if p.is_absolute() else (REPO_ROOT / p)


def _install_labelit_subclass(ejg_module) -> None:
    import pygame
    from emg_jump_game import GameState
    from ui.hapticare_shell import nav_hit_test
    from ui.theme import fill_for_gameplay, fill_for_shell_screen

    from LabelitStyle_Code.panels import (
        dashboard_panel,
        games_panel,
        graphs_panel,
        imu_panel,
        sessions_panel,
        settings_panel,
    )
    from LabelitStyle_Code.session_browser import list_sessions
    from LabelitStyle_Code.shell import draw_bottom_nav
    from LabelitStyle_Code.theme import labelit_theme

    class LabelitIntegratedEMGGame(ejg_module.IntegratedEMGGame):
        """Preserves legacy FSM / ``EMGGameController``; overrides chrome + off-tab views."""

        def __init__(self) -> None:
            super().__init__()
            self.haptic_theme = labelit_theme()

        def handle_events(self) -> None:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.VIDEORESIZE:
                    size = getattr(event, "size", None)
                    if size is None:
                        width, height = event.w, event.h
                    else:
                        width, height = size
                    self._handle_window_resize(width, height)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    idx = nav_hit_test(event.pos, self._full_width, self._full_height)
                    if idx is not None:
                        self.haptic_nav_index = idx
                    if self.haptic_nav_index == 1:
                        off = self.content_surface.get_offset()
                        loc = (event.pos[0] - off[0], event.pos[1] - off[1])
                        btn = getattr(self, "_labelit_graph_stop_btn", None)
                        if btn is not None and btn.collidepoint(loc):
                            print(
                                "[LabelitStyle_Code] STOP RECORDING stub — "
                                "legacy has no explicit record/stop toggle to call."
                            )

                if self.state == GameState.USER_INPUT:
                    self.handle_user_input_events(event)
                elif self.state == GameState.CONNECTION_VERIFY:
                    self.handle_connection_verify_events(event)
                elif self.state == GameState.USER_CHOICE:
                    self.handle_user_choice_events(event)
                elif self.state == GameState.CALIBRATION:
                    self.handle_calibration_events(event)
                elif self.state == GameState.THRESHOLD_ADJUST:
                    self.handle_threshold_adjust_events(event)
                elif self.state == GameState.TRIGGER_MODE_SELECT:
                    self.handle_trigger_mode_events(event)
                elif self.state == GameState.MENU:
                    self.handle_menu_events(event)
                elif self.state == GameState.PLAYING:
                    self.handle_game_events(event)
                elif self.state == GameState.GAME_OVER:
                    self.handle_game_over_events(event)

        def _labelit_build_context(self) -> dict:
            return {
                "game": self,
                "controller": self.emg_controller,
                "theme": self.haptic_theme,
                "workflow_tab": self._workflow_nav_tab(),
                "sessions": list_sessions(data_base_dir()),
                "graphs_header_percent": getattr(self, "threshold_percent_value", None),
            }

        def _labelit_draw_off_tab(self) -> None:
            rect = self.content_surface.get_rect()
            fonts = {"title": self.font, "body": self.small_font, "tiny": self.tiny_font}
            ctx = self._labelit_build_context()
            idx = self.haptic_nav_index
            if idx == 0:
                sessions_panel.draw_sessions_panel(self.content_surface, rect, fonts, ctx)
            elif idx == 1:
                graphs_panel.draw_graphs_panel(self.content_surface, rect, fonts, ctx)
            elif idx == 2:
                dashboard_panel.draw_dashboard_panel(self.content_surface, rect, fonts, ctx)
            elif idx == 3:
                games_panel.draw_games_panel(self.content_surface, rect, fonts, ctx)
            elif idx == 4:
                imu_panel.draw_imu_panel(self.content_surface, rect, fonts, ctx)
            else:
                settings_panel.draw_settings_panel(self.content_surface, rect, fonts, ctx)

        def draw(self) -> None:
            setattr(self, "_labelit_graph_stop_btn", None)
            theme = self.haptic_theme
            self._draw_canvas = self.content_surface
            workflow_tab = self._workflow_nav_tab()
            show_legacy = self.haptic_nav_index == workflow_tab

            self.screen.fill(theme.window_bg)

            if show_legacy:
                if self.state == GameState.PLAYING:
                    self._draw_canvas.fill(fill_for_gameplay(theme))
                else:
                    self._draw_canvas.fill(fill_for_shell_screen(theme))

                if self.state == GameState.INITIALIZATION:
                    self.draw_initialization()
                elif self.state == GameState.USER_INPUT:
                    self.draw_user_input()
                elif self.state == GameState.CONNECTION_VERIFY:
                    self.draw_connection_verify()
                elif self.state == GameState.USER_CHOICE:
                    self.draw_user_choice()
                elif self.state == GameState.CALIBRATION:
                    self.draw_calibration()
                elif self.state == GameState.THRESHOLD_ADJUST:
                    self.draw_threshold_adjust()
                elif self.state == GameState.TRIGGER_MODE_SELECT:
                    self.draw_trigger_mode_select()
                elif self.state == GameState.MENU:
                    self.draw_menu()
                elif self.state == GameState.PLAYING:
                    self.draw_gameplay()
                elif self.state == GameState.GAME_OVER:
                    self.draw_game_over()
                elif self.state == GameState.SESSION_END:
                    self.draw_session_end()
            else:
                self._labelit_draw_off_tab()

            draw_bottom_nav(
                self.screen,
                theme,
                self.haptic_nav_index,
                self.small_font,
                self.tiny_font,
            )
            pygame.display.flip()

    ejg_module.IntegratedEMGGame = LabelitIntegratedEMGGame


def apply_patches() -> None:
    """Swap the concrete game class before ``main()`` instantiates it."""
    import emg_jump_game as ejg

    _install_labelit_subclass(ejg)


def run() -> int:
    import emg_jump_game as ejg

    _install_labelit_subclass(ejg)
    return int(ejg.main())
