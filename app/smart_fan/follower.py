from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from .hardware import ServoOutput


@dataclass
class TargetObservation:
    valid: bool
    x: float = 0.5
    y: float = 0.5
    score: float = 0.0
    count: int = 0
    received_at: float = 0.0
    image_width: int = 0
    image_height: int = 0
    frame: int = 0
    person: dict[str, float] | None = None
    people: list[dict[str, Any]] = None  # type: ignore[assignment]
    selection: dict[str, Any] = None  # type: ignore[assignment]
    group_count: int = 0
    followable: bool = True

    def __post_init__(self) -> None:
        if self.people is None:
            self.people = []
        if self.selection is None:
            self.selection = {}


class FollowController:
    def __init__(self, cfg: dict[str, Any], servo: ServoOutput) -> None:
        self.cfg = cfg
        self.servo = servo
        self.xs: deque[float] = deque(maxlen=5)
        self.filtered_x: float | None = None
        self.last_error = 0.0
        self.last_seen_at: float | None = None
        self.last_target_at: float | None = None
        self.acquire_until = 0.0
        self.centered = False

    def _filter(self, x: float) -> float:
        self.xs.append(min(1.0, max(0.0, float(x))))
        ordered = sorted(self.xs)
        median = ordered[len(ordered) // 2]
        if self.filtered_x is None:
            self.filtered_x = median
        else:
            alpha = 0.35
            self.filtered_x = self.filtered_x + alpha * (median - self.filtered_x)
        return self.filtered_x

    def update(self, target: TargetObservation | None, now: float, dt: float) -> float | None:
        dt = max(0.001, min(0.25, float(dt)))
        if target and target.valid and now - target.received_at <= float(self.cfg["hold_sec"]):
            height_ratio = 1.0
            if target.person:
                height_ratio = max(0.0, float(target.person.get("y2", 1.0)) - float(target.person.get("y1", 0.0)))
            min_height = float(self.cfg.get("min_tracking_height", 0.18))
            if height_ratio < min_height:
                return None

            reacquired = self.last_seen_at is None or now - self.last_seen_at > float(self.cfg["hold_sec"])
            self.last_seen_at = now
            self.last_target_at = now
            self.centered = False
            if reacquired:
                self.acquire_until = now + float(self.cfg.get("soft_start_sec", 0.8))
            x = self._filter(target.x)
            error = x - 0.5
            if bool(self.cfg["invert"]):
                error = -error
            derivative = (error - self.last_error) / dt
            self.last_error = error
            if abs(error) <= float(self.cfg["deadband"]):
                return None
            rate = float(self.cfg["kp"]) * error + float(self.cfg["kd"]) * derivative
            size_factor = min(1.0, max(0.55, height_ratio / 0.35))
            rate_limit = float(self.cfg["max_rate_deg_s"]) * size_factor
            if now < self.acquire_until:
                rate_limit = min(rate_limit, float(self.cfg.get("acquire_rate_deg_s", 28.0)))
            rate = max(-rate_limit, min(rate_limit, rate))
            max_step = float(self.cfg["max_step_deg"]) * (rate_limit / max(1.0, float(self.cfg["max_rate_deg_s"])))
            max_step = max(0.35, max_step)
            step = rate * dt
            step = max(-max_step, min(max_step, step))
            if abs(step) < 0.05:
                return None
            return self.servo.set_angle(self.servo.angle + step)

        if self.last_seen_at is None:
            return None
        missing = now - self.last_seen_at
        if missing >= float(self.cfg["center_after_sec"]) and not self.centered:
            self.centered = True
            self.filtered_x = None
            self.xs.clear()
            self.last_error = 0.0
            return self.servo.set_angle(float(self.cfg["center_angle"]))
        return None

    def target_age(self, now: float) -> float | None:
        if self.last_target_at is None:
            return None
        return max(0.0, now - self.last_target_at)

    def reset(self, center: bool = False) -> None:
        self.xs.clear()
        self.filtered_x = None
        self.last_error = 0.0
        self.last_seen_at = None
        self.last_target_at = None
        self.acquire_until = 0.0
        self.centered = False
        if center:
            self.servo.set_angle(float(self.cfg["center_angle"]))
