from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smart_fan.audio import AudioAnnouncer
from smart_fan.config import load_config
from smart_fan.controller import COMMANDS, FAN_ONLY_COMMANDS, FanController
from smart_fan.hardware import FanOutput, ServoOutput
from smart_fan.vision import VisionReader
from smart_fan.voice import VoiceListener
from smart_fan.web import WebApi

LOG = logging.getLogger("smart_fan")

SILENT_WEB_COMMANDS = frozenset({"auto_off_on", "auto_off_off"})
FAN_REQUIRED_WEB_TEXT = {
    "zh": "风扇还没开哦，先打开风扇吧！",
    "en": "The fan is off. Please turn it on first.",
}


class MockServo:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.angle = float(cfg["initial_angle"])
        self._enabled = True

    def set_angle(self, angle: float) -> float:
        self.angle = min(float(self.cfg["max_angle"]), max(float(self.cfg["min_angle"]), float(angle)))
        return self.angle

    def suspend(self) -> None:
        self._enabled = False

    def resume(self) -> None:
        self._enabled = True

    def close(self) -> None:
        pass


class MockFan:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.enabled = False
        self.duty_ratio = 0.0

    def set_level(self, level: str) -> float:
        levels = {str(k): float(v) for k, v in self.cfg["levels"].items()}
        return self.set_ratio(levels[level])

    def set_ratio(self, ratio: float) -> float:
        self.duty_ratio = max(0.0, min(1.0, float(ratio)))
        self.enabled = self.duty_ratio > 0
        return self.duty_ratio

    def off(self) -> None:
        self.enabled = False
        self.duty_ratio = 0.0

    def close(self) -> None:
        self.off()


class Application:
    def __init__(self, cfg: dict[str, Any], dry_run: bool = False) -> None:
        self.cfg = cfg
        self.started_at = time.monotonic()
        self.announcement_language = "zh"
        self.stop_event = threading.Event()
        self.servo = MockServo(cfg["servo"]) if dry_run else ServoOutput(cfg["servo"])
        self.fan = MockFan(cfg["fan"]) if dry_run else FanOutput(cfg["fan"])
        self.controller = FanController(cfg, self.fan, self.servo)
        if not self.controller.fan_on:
            self.servo.suspend()
        speaker_cfg = dict(cfg["speaker"])
        if dry_run:
            speaker_cfg["enabled"] = False
        self.speaker = AudioAnnouncer(speaker_cfg)
        vision_cfg = dict(cfg["vision"])
        if dry_run:
            vision_cfg["enabled"] = False
        self.vision = VisionReader(vision_cfg)
        voice_cfg = dict(cfg["voice"])
        if dry_run:
            voice_cfg["enabled"] = False
        self.voice = VoiceListener(
            voice_cfg,
            self._voice_command,
            self._voice_wake,
            playback_active=self.speaker.listening_blocked,
            on_unrecognized=self._voice_unrecognized,
        )
        self.web = WebApi(
            cfg["api"],
            self.status,
            self._web_command,
            str(cfg["vision"]["snapshot"]),
            language_fn=self._set_web_language,
        )

    @staticmethod
    def _voice_key(key: str, language: str) -> str:
        return f"{key}_en" if language == "en" else key

    def _voice_wake(self, language: str = "zh") -> None:
        self.announcement_language = language if language in ("zh", "en") else "zh"
        if language == "en" and not bool(
            self.cfg["voice"].get("announce_wake_en", False)
        ):
            return
        self.speaker.announce(self._voice_key("wake", language), replace=True)

    def _voice_unrecognized(self, language: str = "zh") -> None:
        self.announcement_language = language if language in ("zh", "en") else "zh"
        self.speaker.announce(self._voice_key("unrecognized", language))
        LOG.info("voice command was not understood (%s)", language)

    def _apply_output_state(self, command: str) -> None:
        if command == "fan_on":
            self.servo.resume()
            self.vision.resume()
        elif command == "fan_off":
            self.vision.pause()
            self.servo.suspend()

    def _sleep_outputs(self) -> None:
        self.vision.pause()
        self.servo.suspend()

    def _voice_command(self, command: str, language: str = "zh") -> None:
        self.announcement_language = language if language in ("zh", "en") else "zh"
        if not self.controller.execute(command, require_fan_on=True):
            if command in FAN_ONLY_COMMANDS:
                self.speaker.announce(self._voice_key("fan_off_required", language))
                LOG.info("voice command (%s) requires fan on: %s", language, command)
                return
            LOG.warning("ignored voice command: %s", command)
            self.speaker.announce(self._voice_key("unrecognized", language))
            return
        self._apply_output_state(command)
        self.speaker.announce(self._voice_key(command, language))
        LOG.info("executed voice command (%s): %s", language, command)

    def _web_command(
        self,
        command: str,
        language: str = "zh",
        require_fan_on: bool = False,
    ) -> tuple[bool, str, str]:
        language = language if language in ("zh", "en") else "zh"
        self.announcement_language = language
        if command not in COMMANDS:
            return False, f"unknown command: {command}", "invalid_command"
        ok = self.controller.execute(command, require_fan_on=require_fan_on)
        if not ok and require_fan_on and command in FAN_ONLY_COMMANDS:
            self.speaker.announce(self._voice_key("fan_off_required", language))
            LOG.info("web command blocked: fan is off (%s)", command)
            return False, FAN_REQUIRED_WEB_TEXT[language], "fan_required"
        action = self.controller.status().last_action if ok else "command failed"
        if ok:
            self._apply_output_state(command)
            if command not in SILENT_WEB_COMMANDS:
                self.speaker.announce(self._voice_key(command, language))
        LOG.info("web command: %s -> %s", command, action)
        return ok, action, "" if ok else "command_failed"

    def _set_web_language(self, language: str) -> None:
        self.announcement_language = language if language in ("zh", "en") else "zh"

    def status(self) -> dict[str, Any]:
        cs = self.controller.status()
        return {
            "app": {
                "name": self.cfg["device"]["name"],
                "running": not self.stop_event.is_set(),
                "uptime_sec": max(0.0, time.monotonic() - self.started_at),
                "announcement_language": self.announcement_language,
            },
            "fan": {
                "on": cs.fan_on,
                "level": cs.level,
                "duty_ratio": cs.duty_ratio,
                "follow": cs.follow,
                "servo_angle": cs.servo_angle,
                "timer_remaining_sec": cs.timer_remaining_sec,
                "last_command": cs.last_command,
                "last_action": cs.last_action,
            },
            "timer": {"remaining_sec": cs.timer_remaining_sec},
            "vision": self.vision.status(),
            "voice": self.voice.status(),
            "speaker": self.speaker.status(),
            "behavior": {
                "state": cs.behavior_state,
                "auto_off_enabled": cs.auto_off_enabled,
                "auto_off_after_sec": float(self.cfg["behavior"]["standby_after_sec"]),
            },
            "hardware": {
                "servo_pwm": self.cfg["servo"]["pwm_id"],
                "fan_pwm": self.cfg["fan"]["pwm_id"],
                "fan_pin": self.cfg["fan"].get("physical_pin", ""),
            },
        }

    def run(self) -> int:
        LOG.info("starting %s", self.cfg["device"]["name"])
        try:
            self.speaker.start()
            if self.controller.fan_on:
                self.vision.start()
            self.voice.start()
            self.web.start()
            hz = max(1.0, float(self.cfg["control"]["hz"]))
            period = 1.0 / hz
            next_tick = time.monotonic()
            last_report = 0.0
            while not self.stop_event.is_set():
                for event in self.controller.tick(self.vision.latest()):
                    if event in ("standby", "timer_expired"):
                        self._sleep_outputs()
                    language = self.announcement_language
                    self.speaker.announce(
                        self._voice_key(event, language),
                        replace=event in ("standby", "timer_expired"),
                    )
                now = time.monotonic()
                if now - last_report >= 5.0:
                    last_report = now
                    s = self.status()
                    LOG.info(
                        "fan=%s level=%s follow=%s angle=%.1f person=%s voice=%s",
                        s["fan"]["on"],
                        s["fan"]["level"],
                        s["fan"]["follow"],
                        s["fan"]["servo_angle"],
                        s["vision"]["valid"],
                        s["voice"]["listening"],
                    )
                next_tick += period
                sleep = next_tick - time.monotonic()
                if sleep > 0:
                    self.stop_event.wait(sleep)
                else:
                    next_tick = time.monotonic()
        finally:
            self.shutdown()
        return 0

    def shutdown(self) -> None:
        if self.stop_event.is_set() and getattr(self, "_shutdown_done", False):
            return
        self.stop_event.set()
        LOG.info("shutting down")
        try:
            self.web.stop()
        except Exception:  # noqa: BLE001
            LOG.exception("web shutdown failed")
        try:
            self.voice.stop()
        except Exception:  # noqa: BLE001
            LOG.exception("voice shutdown failed")
        try:
            self.speaker.stop()
        except Exception:  # noqa: BLE001
            LOG.exception("speaker shutdown failed")
        try:
            self.vision.stop()
        except Exception:  # noqa: BLE001
            LOG.exception("vision shutdown failed")
        try:
            self.fan.close()
        except Exception:  # noqa: BLE001
            LOG.exception("fan shutdown failed")
        try:
            self.servo.close()
        except Exception:  # noqa: BLE001
            LOG.exception("servo shutdown failed")
        self._shutdown_done = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smart fan controller")
    parser.add_argument("--config", default="/userdata/smart-fan/config/smart_fan.json")
    parser.add_argument("--dry-run", action="store_true", help="use mock hardware and disable vision/voice")
    parser.add_argument("--log-level", default="")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    level = (args.log_level or str(cfg["device"].get("log_level", "info"))).upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = Application(cfg, dry_run=args.dry_run)

    def stop(_signum: int, _frame: object) -> None:
        app.stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
