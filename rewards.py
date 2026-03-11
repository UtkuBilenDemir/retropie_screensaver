"""
Reward system — confetti overlay, streak tracking, ntfy notifications.
All features are individually toggled in config.yaml under `rewards:`.
"""
import json
import random
import threading
from pathlib import Path

import pygame
import requests


# ── State persistence ─────────────────────────────────────────────────────────

_DEFAULT_STATE = {"streak": 0, "last_goal_date": None, "last_weekly_label": None}


def load_state(path: str) -> dict:
    try:
        return {**_DEFAULT_STATE, **json.loads(Path(path).read_text())}
    except Exception:
        return dict(_DEFAULT_STATE)


def save_state(path: str, state: dict) -> None:
    try:
        Path(path).write_text(json.dumps(state))
    except Exception as e:
        print(f"[rewards] save_state: {e}")


def check_goals(state: dict, path: str, today, debt: dict) -> dict:
    """
    Compare today's metrics against state. Update streak if daily goal
    was newly hit. Returns event dict:
        {"daily": bool, "weekly": bool, "streak": int}
    Saves state to disk only when something changed.
    """
    from datetime import timedelta

    today_str    = str(today)
    weekly_label = today.strftime("%G-W%V")

    daily_hit  = debt["today_debt"] <= 0 and debt["today_actual"] > 0
    weekly_hit = debt["week_debt"] <= 0

    events = {"daily": False, "weekly": False, "streak": state.get("streak", 0)}
    dirty  = False

    if daily_hit and state.get("last_goal_date") != today_str:
        yesterday = str(today - timedelta(days=1))
        if state.get("last_goal_date") == yesterday:
            state["streak"] = state.get("streak", 0) + 1
        else:
            state["streak"] = 1
        state["last_goal_date"] = today_str
        events["daily"]  = True
        events["streak"] = state["streak"]
        dirty = True

    if weekly_hit and state.get("last_weekly_label") != weekly_label:
        state["last_weekly_label"] = weekly_label
        events["weekly"] = True
        dirty = True

    if dirty:
        save_state(path, state)

    return events


# ── ntfy ──────────────────────────────────────────────────────────────────────

def notify(topic: str, title: str, body: str, tags: str = "trophy") -> None:
    """Fire-and-forget push notification via ntfy.sh. No-op if topic is empty."""
    if not topic:
        return

    def _send():
        try:
            requests.post(
                f"https://ntfy.sh/{topic}",
                data=body.encode(),
                headers={"Title": title, "Tags": tags, "Priority": "default"},
                timeout=8,
            )
        except Exception as e:
            print(f"[ntfy] {e}")

    threading.Thread(target=_send, daemon=True).start()


# ── Confetti ──────────────────────────────────────────────────────────────────

# Muted palette — matches the dashboard dark theme, not a clown show
_PALETTE = [
    (63, 185, 80),    # green
    (88, 166, 255),   # blue
    (210, 153, 34),   # gold
    (240, 136, 62),   # orange
    (230, 237, 243),  # near-white
]

CONFETTI_LIFETIME = 3.0  # seconds


class Confetti:
    def __init__(self, W: int, H: int, n: int = 100):
        self.W, self.H   = W, H
        self.elapsed     = 0.0
        self.particles   = [self._spawn(W, H) for _ in range(n)]

    @staticmethod
    def _spawn(W, H) -> dict:
        return {
            "x":     random.uniform(0, W),
            "y":     random.uniform(-H * 0.2, -10),
            "vx":    random.uniform(-1.5, 1.5),
            "vy":    random.uniform(1.5, 4.5),
            "rot":   random.uniform(0, 360),
            "rot_v": random.uniform(-5, 5),
            "w":     random.randint(6, 11),
            "h":     random.randint(3, 7),
            "color": random.choice(_PALETTE),
        }

    def update(self, dt: float) -> None:
        self.elapsed += dt
        for p in self.particles:
            p["x"]  += p["vx"]
            p["y"]  += p["vy"]
            p["vy"] += 0.09   # gravity
            p["vx"] *= 0.995  # air drag
            p["rot"] += p["rot_v"]

    def draw(self, surface: pygame.Surface) -> None:
        # Fade out over the last second
        fade_start = CONFETTI_LIFETIME - 1.0
        if self.elapsed > fade_start:
            alpha = max(0, int(255 * (CONFETTI_LIFETIME - self.elapsed)))
        else:
            alpha = 255

        for p in self.particles:
            if p["y"] > self.H + 20:
                continue
            s = pygame.Surface((p["w"], p["h"]), pygame.SRCALPHA)
            s.fill((*p["color"], alpha))
            rotated = pygame.transform.rotate(s, p["rot"])
            surface.blit(rotated, (int(p["x"]), int(p["y"])))

    @property
    def done(self) -> bool:
        return self.elapsed >= CONFETTI_LIFETIME
