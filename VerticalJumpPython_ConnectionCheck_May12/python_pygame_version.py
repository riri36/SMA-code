#!/usr/bin/env python3
"""
Vertical Platform Jump Game - Python/Pygame Version
Run: python vertical_jump_game.py
Requirements: pip install pygame
"""

import pygame
import random
import math
from enum import Enum

# Initialize Pygame
pygame.init()

# Constants
SCREEN_WIDTH = 400
SCREEN_HEIGHT = 600
FPS = 60

# Colors
BACKGROUND = (135, 206, 235)  # Sky blue
GROUND_COLOR = (139, 69, 19)  # Brown
GRASS_COLOR = (144, 238, 144)  # Light green
PLAYER_COLOR = (255, 215, 0)  # Gold
PLAYER_ON_PIPE = (255, 165, 0)  # Orange
PIPE_COLOR = (34, 139, 34)  # Green
STATIC_PIPE_COLOR = (31, 95, 31)  # Dark green
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# Physics
GRAVITY = 0.6
JUMP_POWER = -15
GROUND_HEIGHT = 60

# Pipe settings
PIPE_HEIGHT = 20
GAP_SIZE = 100
MIN_PIPE_SPACING = 115
MAX_PIPE_SPACING = 125
FIRST_PIPE_HEIGHT = 160


class GameState(Enum):
    MENU = 1
    PLAYING = 2
    GAME_OVER = 3


class Player:
    def __init__(self):
        self.x = SCREEN_WIDTH // 2 - 15
        self.y = GROUND_HEIGHT
        self.width = 30
        self.height = 30
        self.velocity = 0
        self.is_on_ground = True
        self.is_on_pipe = False
        self.has_jumped_once = False
        self.current_pipe = None
        self.is_alive = True
        
        # Add jump cooldown protection
        self.last_jump_time = 0
        self.jump_cooldown = 0.15  # 150ms cooldown (matching EMG system)
        
    def jump(self):
        current_time = pygame.time.get_ticks() / 1000.0 # Get current time in seconds
        if self.is_alive and (self.is_on_ground or self.is_on_pipe):
            if current_time - self.last_jump_time > self.jump_cooldown:
                self.velocity = JUMP_POWER
                self.is_on_ground = False
                self.is_on_pipe = False
                self.has_jumped_once = True
                self.current_pipe = None
                self.last_jump_time = current_time # Update last jump time
                return True
        return False
    
    def update(self):
        # Only apply physics after first jump
        if self.has_jumped_once:
            if not self.is_on_pipe and not self.is_on_ground:
                # Apply gravity
                self.velocity += GRAVITY
                self.y -= self.velocity
                
                # Ground check
                if self.y <= GROUND_HEIGHT:
                    self.y = GROUND_HEIGHT
                    self.velocity = 0
                    self.is_on_ground = True
        else:
            # Lock to ground until first jump
            self.y = GROUND_HEIGHT
            self.velocity = 0
            self.is_on_ground = True
    
    def land_on_pipe(self, pipe):
        self.y = pipe.y + PIPE_HEIGHT
        self.velocity = 0
        self.is_on_pipe = True
        self.is_on_ground = False
        self.current_pipe = pipe
        pipe.on_landed()
    
    def get_rect(self):
        return pygame.Rect(self.x, SCREEN_HEIGHT - self.y - self.height, 
                          self.width, self.height)
    
    def draw(self, screen, camera_y):
        color = PLAYER_ON_PIPE if self.is_on_pipe else PLAYER_COLOR
        draw_y = SCREEN_HEIGHT - (self.y - camera_y) - self.height
        pygame.draw.circle(screen, color, 
                          (self.x + self.width//2, draw_y + self.height//2), 
                          self.width//2)


class Pipe:
    def __init__(self, y_position):
        self.y = y_position
        self.gap_start = random.randint(50, SCREEN_WIDTH - GAP_SIZE - 50)
        self.gap_end = self.gap_start + GAP_SIZE
        self.speed = random.uniform(1.5, 3.0)
        self.direction = random.choice([-1, 1])
        self.is_landed = False
        self.passed = False
        
    def update(self, dt):
        if not self.is_landed:
            # Move horizontally
            movement = self.speed * self.direction * dt * 60
            self.gap_start += movement
            self.gap_end += movement
            
            # Reverse at boundaries
            if self.gap_start <= 0 or self.gap_end >= SCREEN_WIDTH:
                self.direction *= -1
                if self.gap_start <= 0:
                    self.gap_start = 0
                    self.gap_end = GAP_SIZE
                else:
                    self.gap_end = SCREEN_WIDTH
                    self.gap_start = SCREEN_WIDTH - GAP_SIZE
    
    def on_landed(self):
        self.is_landed = True
    
    def check_collision(self, player):
        player_rect = player.get_rect()
        player_bottom = player.y
        player_top = player.y + player.height
        
        # Check if player is at pipe level
        if player_bottom <= self.y + PIPE_HEIGHT and player_top >= self.y:
            # Check left pipe
            if player.x < self.gap_start:
                # Landing on top vs hitting side
                if (player_bottom <= self.y + PIPE_HEIGHT and 
                    player_bottom >= self.y + PIPE_HEIGHT - 10 and 
                    player.velocity >= 0):
                    return 'land'
                elif player_bottom < self.y + PIPE_HEIGHT - 10:
                    return 'side'
            
            # Check right pipe
            if player.x + player.width > self.gap_end:
                # Landing on top vs hitting side
                if (player_bottom <= self.y + PIPE_HEIGHT and 
                    player_bottom >= self.y + PIPE_HEIGHT - 10 and 
                    player.velocity >= 0):
                    return 'land'
                elif player_bottom < self.y + PIPE_HEIGHT - 10:
                    return 'side'
        
        return None
    
    def draw(self, screen, camera_y):
        draw_y = SCREEN_HEIGHT - (self.y - camera_y) - PIPE_HEIGHT
        color = STATIC_PIPE_COLOR if self.is_landed else PIPE_COLOR
        
        # Draw left pipe
        if self.gap_start > 0:
            pygame.draw.rect(screen, color, 
                           (0, draw_y, self.gap_start, PIPE_HEIGHT))
            pygame.draw.rect(screen, BLACK, 
                           (0, draw_y, self.gap_start, PIPE_HEIGHT), 2)
        
        # Draw right pipe
        if self.gap_end < SCREEN_WIDTH:
            pygame.draw.rect(screen, color,
                           (self.gap_end, draw_y, SCREEN_WIDTH - self.gap_end, PIPE_HEIGHT))
            pygame.draw.rect(screen, BLACK,
                           (self.gap_end, draw_y, SCREEN_WIDTH - self.gap_end, PIPE_HEIGHT), 2)


class Camera:
    def __init__(self):
        self.y = 0
        self.target_y = 0
        self.is_auto_scrolling = False
        
    def auto_reposition(self, pipe_y):
        self.target_y = pipe_y - 200
        if self.target_y > self.y:
            self.is_auto_scrolling = True
    
    def cancel_auto_scroll(self):
        self.is_auto_scrolling = False
    
    def update(self, dt):
        if self.is_auto_scrolling:
            diff = self.target_y - self.y
            if abs(diff) > 1:
                self.y += diff * 0.15
            else:
                self.y = self.target_y
                self.is_auto_scrolling = False
        
        # Don't go below ground
        self.y = max(0, self.y)


class Game:
    def __init__(self):
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("Vertical Platform Jump")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 24)
        
        self.reset_game()
        
    def reset_game(self):
        self.state = GameState.MENU
        self.player = Player()
        self.camera = Camera()
        self.pipes = []
        self.score = 0
        self.running = True
        
        # Create initial pipes
        current_height = FIRST_PIPE_HEIGHT
        for _ in range(3):
            self.pipes.append(Pipe(current_height))
            current_height += random.randint(MIN_PIPE_SPACING, MAX_PIPE_SPACING)
    
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            
            elif event.type == pygame.KEYDOWN:
                if self.state == GameState.MENU:
                    if event.key == pygame.K_SPACE:
                        self.state = GameState.PLAYING
                
                elif self.state == GameState.PLAYING:
                    if event.key == pygame.K_SPACE:
                        if self.player.jump():
                            self.camera.cancel_auto_scroll()
                
                elif self.state == GameState.GAME_OVER:
                    if event.key == pygame.K_r:
                        self.reset_game()
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if self.state == GameState.MENU:
                    self.state = GameState.PLAYING
                elif self.state == GameState.PLAYING:
                    if self.player.jump():
                        self.camera.cancel_auto_scroll()
                elif self.state == GameState.GAME_OVER:
                    self.reset_game()
    
    def update(self, dt):
        if self.state != GameState.PLAYING:
            return
        
        # Update player
        self.player.update()
        
        # Update camera
        self.camera.update(dt)
        
        # Update pipes
        for pipe in self.pipes:
            pipe.update(dt)
        
        # Check collisions (only after first jump)
        if self.player.has_jumped_once and not self.player.is_on_pipe and not self.player.is_on_ground:
            for pipe in self.pipes:
                collision = pipe.check_collision(self.player)
                if collision == 'land':
                    self.player.land_on_pipe(pipe)
                    self.camera.auto_reposition(pipe.y)
                    if not pipe.passed:
                        self.score += 1
                        pipe.passed = True
                    break
                elif collision == 'side':
                    self.state = GameState.GAME_OVER
                    break
        
        # Spawn new pipes as needed
        if self.pipes:
            highest_pipe = max(pipe.y for pipe in self.pipes)
            if self.player.y + 800 > highest_pipe:
                spacing = random.randint(MIN_PIPE_SPACING, MAX_PIPE_SPACING)
                self.pipes.append(Pipe(highest_pipe + spacing))
        
        # Remove pipes below camera
        self.pipes = [pipe for pipe in self.pipes 
                     if pipe.y > self.camera.y - 200]
    
    def draw_ground(self):
        if self.camera.y < 100:
            ground_y = SCREEN_HEIGHT - GROUND_HEIGHT + self.camera.y
            # Draw grass
            pygame.draw.rect(self.screen, GRASS_COLOR,
                           (0, ground_y, SCREEN_WIDTH, 20))
            # Draw dirt
            pygame.draw.rect(self.screen, GROUND_COLOR,
                           (0, ground_y + 20, SCREEN_WIDTH, GROUND_HEIGHT - 20))
    
    def draw_menu(self):
        # Title
        title = self.font.render("VERTICAL JUMP", True, WHITE)
        title_rect = title.get_rect(center=(SCREEN_WIDTH//2, 150))
        self.screen.blit(title, title_rect)
        
        # Instructions
        instructions = [
            "Press SPACE or CLICK to jump",
            "Land on TOP of pipes",
            "Pipes STOP when you land",
            "Avoid hitting the SIDES!",
            "",
            "Press SPACE to start"
        ]
        
        y = 250
        for line in instructions:
            text = self.small_font.render(line, True, WHITE)
            text_rect = text.get_rect(center=(SCREEN_WIDTH//2, y))
            self.screen.blit(text, text_rect)
            y += 30
    
    def draw_game_over(self):
        # Game Over text
        game_over = self.font.render("GAME OVER", True, WHITE)
        game_over_rect = game_over.get_rect(center=(SCREEN_WIDTH//2, 250))
        self.screen.blit(game_over, game_over_rect)
        
        # Score
        score_text = self.font.render(f"Score: {self.score}", True, WHITE)
        score_rect = score_text.get_rect(center=(SCREEN_WIDTH//2, 300))
        self.screen.blit(score_text, score_rect)
        
        # Restart
        restart = self.small_font.render("Press R to restart", True, WHITE)
        restart_rect = restart.get_rect(center=(SCREEN_WIDTH//2, 350))
        self.screen.blit(restart, restart_rect)
    
    def draw_ui(self):
        # Score
        score_text = self.font.render(f"Score: {self.score}", True, WHITE)
        self.screen.blit(score_text, (10, 10))
        
        # Status
        if self.player.is_on_pipe:
            status = "On Pipe (Static)" if self.player.current_pipe.is_landed else "On Pipe"
        elif self.player.is_on_ground:
            status = "On Ground"
        else:
            status = "Jumping" if self.player.velocity < 0 else "Falling"
        
        status_text = self.small_font.render(status, True, WHITE)
        status_rect = status_text.get_rect(topright=(SCREEN_WIDTH - 10, 10))
        self.screen.blit(status_text, status_rect)
    
    def draw(self):
        # Background
        self.screen.fill(BACKGROUND)
        
        if self.state == GameState.MENU:
            self.draw_menu()
        
        elif self.state == GameState.PLAYING:
            # Draw ground
            self.draw_ground()
            
            # Draw pipes
            for pipe in self.pipes:
                pipe.draw(self.screen, self.camera.y)
            
            # Draw player
            self.player.draw(self.screen, self.camera.y)
            
            # Draw UI
            self.draw_ui()
        
        elif self.state == GameState.GAME_OVER:
            self.draw_game_over()
        
        pygame.display.flip()
    
    def run(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0  # Delta time in seconds
            
            self.handle_events()
            self.update(dt)
            self.draw()
        
        pygame.quit()


if __name__ == "__main__":
    game = Game()
    game.run()