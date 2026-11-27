from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .follower import FollowController, TargetObservation


class FanDevice(Protocol):
    enabled: bool
    duty_ratio: float

    def set_level(self, level: str) -> float: ...
    def set_ratio(self, ratio: float) -> float: ...
    def off(self) -> None: ...


COMMANDS = {
    "fan_on",
    "fan_off",
    "level_low",
    "level_medium",
    "level_high",
    "level_max",
    "follow_on",
    "follow_off",
    "timer_cancel",
    "timer_10m",
    "timer_half_hour",
    "timer_1h",
    "auto_off_on",
    "auto_off_off",
}

# These settings only make sense while the fan is running. Voice and web control
# reject them while off instead of reporting a successful change that has no
# visible effect or storing a shutdown timer for an already-off fan.
FAN_ONLY_COMMANDS = frozenset({
    "level_low",
    "level_medium",
    "level_high",
    "level_max",
    "follow_on",
    "follow_off",
    "timer_10m",
    "timer_half_hour",
    "timer_1h",
})


@dataclass
class ControllerStatus:
    fan_on: bool = False
    level: str = "medium"
    duty_ratio: float = 0.0
    follow: bool = True
    servo_angle: float = 180.0
    timer_remaining_sec: float | None = None
    target_age_sec: float | None = None
    last_person_seen_sec: float | None = None
    last_command: str = ""
    last_action: str = ""
    behavior_state: str = "off"
    target_confirmed: bool = False
    auto_off_enabled: bool = True


@dataclass
class FanController:
    cfg: dict[str, Any]
    fan: FanDevice
    servo: Any
    now_fn: Callable[[], float] = time.monotonic
    lock: threading.RLock = field(default_factory=threading.RLock)
    fan_on: bool = False
    level: str = ""
    follow: bool = True
    timer_deadline: float | None = None
    last_command: str = ""
    last_action: str = "startup"
    last_person_at: float | None = None
    behavior_state: str = "off"
    search_started_at: float | None = None
    last_found_announce_at: float = -1e9
    target_seen_since: float | None = None
    last_target_frame: int = -1
    target_confirmed: bool = False
    auto_off_enabled: bool = True
    _last_tick: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.level = str(self.cfg["fan"]["default_level"])
        self.follow = True
        self.auto_off_enabled = bool(self.cfg["behavior"].get("auto_off_enabled", True))
        self.follower = FollowController(self.cfg["servo"], self.servo)
        self.servo.set_angle(float(self.cfg["servo"]["initial_angle"]))
        self.fan.off()

    @property
    def timer_seconds(self) -> dict[str, float]:
        return {"timer_10m": 600.0, "timer_half_hour": 1800.0, "timer_1h": 3600.0}

    def execute(self, command: str, *, require_fan_on: bool = False) -> bool:
        command = str(command).strip()
        if command not in COMMANDS:
            return False
        with self.lock:
            if require_fan_on and command in FAN_ONLY_COMMANDS and not self.fan_on:
                self.last_command = command
                self.last_action = "风扇未开启，命令未执行"
                return False
            self.last_command = command
            if command == "fan_on":
                self.fan_on = True
                self.last_person_at = self.now_fn()
                self.search_started_at = None
                self.target_seen_since = None
                self.target_confirmed = False
                self.behavior_state = "follow" if self.follow else "manual"
                self.fan.set_level(self.level)
                self.last_action = "风扇已打开"
            elif command == "fan_off":
                self.fan_on = False
                self.fan.off()
                self.timer_deadline = None
                self.search_started_at = None
                self.behavior_state = "off"
                self.follower.reset(center=False)
                self.target_seen_since = None
                self.target_confirmed = False
                self.last_action = "风扇已关闭，摄像头和舵机进入待机"
            elif command.startswith("level_"):
                self.level = command.removeprefix("level_")
                if self.fan_on:
                    self.fan.set_level(self.level)
                self.last_action = f"档位切换为 {self.level}"
            elif command == "follow_on":
                self.follow = True
                self.follower.reset(center=False)
                if self.fan_on:
                    self.last_person_at = self.now_fn()
                    self.search_started_at = None
                    self.behavior_state = "follow"
                else:
                    self.behavior_state = "off"
                self.last_action = "人体跟随已开启"
            elif command == "follow_off":
                self.follow = False
                self.follower.reset(center=False)
                self.search_started_at = None
                self.behavior_state = "manual" if self.fan_on else "off"
                self.last_action = "人体跟随已停止"
            elif command == "auto_off_on":
                self.auto_off_enabled = True
                self.last_action = "无人自动关机已开启"
            elif command == "auto_off_off":
                self.auto_off_enabled = False
                self.last_action = "无人自动关机已关闭"
            elif command == "timer_cancel":
                self.timer_deadline = None
                self.last_action = "定时已取消"
            elif command in self.timer_seconds:
                self.timer_deadline = self.now_fn() + self.timer_seconds[command]
                self.last_action = f"定时已设置 {int(self.timer_seconds[command])} 秒"
            return True

    def tick(self, target: TargetObservation | None) -> list[str]:
        now = self.now_fn()
        dt = now - self._last_tick
        self._last_tick = now
        events: list[str] = []
        with self.lock:
            if self.timer_deadline is not None and now >= self.timer_deadline:
                self.timer_deadline = None
                self.fan_on = False
                self.fan.off()
                self.follower.reset(center=False)
                self.behavior_state = "standby"
                self.search_started_at = None
                self.last_action = "定时到期，风扇已关闭"
                events.append("timer_expired")

            raw_target = bool(
                target
                and target.valid
                and now - target.received_at <= float(self.cfg["vision"]["stale_sec"])
            )
            if raw_target and target is not None:
                if target.frame != self.last_target_frame:
                    self.last_target_frame = target.frame
                if self.target_seen_since is None:
                    self.target_seen_since = now
                self.target_confirmed = (
                    now - self.target_seen_since
                    >= float(self.cfg["behavior"]["target_confirm_sec"])
                )
            else:
                self.target_seen_since = None
                self.target_confirmed = False
            valid_target = raw_target and self.target_confirmed

            if not self.fan_on:
                self.behavior_state = "off"
                return events

            if not self.follow:
                self.behavior_state = "manual"
                return events

            if self.behavior_state == "standby":
                return events

            if valid_target:
                self.last_person_at = now
                if self.behavior_state == "search":
                    self.behavior_state = "follow"
                    self.search_started_at = None
                    self.follower.reset(center=False)
                    cooldown = float(self.cfg["behavior"]["found_announce_cooldown_sec"])
                    if now - self.last_found_announce_at >= cooldown:
                        events.append("target_found")
                        self.last_found_announce_at = now
                    self.last_action = "巡视已找到人员"
                elif self.behavior_state != "standby":
                    self.behavior_state = "follow"

            if self.behavior_state == "standby":
                return events

            if self.behavior_state in ("follow", "search"):
                if self.last_person_at is None:
                    self.last_person_at = now
                missing = now - self.last_person_at

                if (
                    self.auto_off_enabled
                    and missing >= float(self.cfg["behavior"]["standby_after_sec"])
                ):
                    self.behavior_state = "standby"
                    self.timer_deadline = None
                    self.search_started_at = None
                    self.fan_on = False
                    self.fan.off()
                    self.follower.reset(center=False)
                    self.last_action = "长时间无人，已进入待机"
                    events.append("standby")
                    return events

                if missing >= float(self.cfg["behavior"]["search_after_sec"]):
                    if self.behavior_state != "search":
                        self.behavior_state = "search"
                        self.search_started_at = now
                        self.follower.reset(center=False)
                        self.last_action = "无人，开始缓慢巡视"
                        events.append("search_start")

            if self.behavior_state == "search" and self.search_started_at is not None:
                behavior = self.cfg["behavior"]
                lo = float(behavior["search_min_angle"])
                hi = float(behavior["search_max_angle"])
                speed = max(1.0, float(behavior["search_speed_deg_s"]))
                span = max(1.0, hi - lo)
                leg = span / speed
                phase = (now - self.search_started_at) % (leg * 2.0)
                desired = lo + speed * phase if phase <= leg else hi - speed * (phase - leg)
                max_step = max(0.2, speed * dt)
                delta = max(-max_step, min(max_step, desired - self.servo.angle))
                if abs(delta) >= 0.05:
                    self.servo.set_angle(self.servo.angle + delta)
            elif valid_target and target is not None and target.followable:
                self.follower.update(target, now, dt)
        return events

    def status(self) -> ControllerStatus:
        now = self.now_fn()
        with self.lock:
            remaining = None if self.timer_deadline is None else max(0.0, self.timer_deadline - now)
            last_person = None if self.last_person_at is None else max(0.0, now - self.last_person_at)
            return ControllerStatus(
                fan_on=self.fan_on,
                level=self.level,
                duty_ratio=float(self.fan.duty_ratio),
                follow=self.follow,
                servo_angle=float(self.servo.angle),
                timer_remaining_sec=remaining,
                target_age_sec=self.follower.target_age(now),
                last_person_seen_sec=last_person,
                last_command=self.last_command,
                last_action=self.last_action,
                behavior_state=self.behavior_state,
                target_confirmed=self.target_confirmed,
                auto_off_enabled=self.auto_off_enabled,
            )
