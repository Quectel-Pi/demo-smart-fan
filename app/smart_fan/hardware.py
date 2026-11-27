from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

PWM_ROOT = Path("/sys/class/pwm")


class HardwareError(RuntimeError):
    pass


def _write(path: Path, value: object) -> None:
    try:
        path.write_text(str(value), encoding="ascii")
    except OSError as exc:
        raise HardwareError(f"write {path} = {value!r}: {exc}") from exc


def find_pwm_chip(pwm_id: str) -> Path:
    for chip in sorted(PWM_ROOT.glob("pwmchip*")):
        try:
            target = chip.resolve()
        except OSError:
            continue
        if f"/{pwm_id}/" in f"{target}/":
            return chip
    raise HardwareError(f"PWM controller {pwm_id!r} not found under {PWM_ROOT}")


class PwmChannel:
    def __init__(self, pwm_id: str, channel: int = 0) -> None:
        self.pwm_id = pwm_id
        self.channel = channel
        self.lock = threading.RLock()
        self.chip = find_pwm_chip(pwm_id)
        self.path = self.chip / f"pwm{channel}"
        self.created = False
        self._ensure_exported()
        # Rockchip PWM rejects polarity changes while the channel is enabled.
        # A service restart often inherits an enabled channel from the previous run.
        enable = self.path / "enable"
        if enable.exists() and enable.read_text(encoding="ascii").strip() != "0":
            _write(enable, 0)

    def _ensure_exported(self) -> None:
        if self.path.is_dir():
            return
        _write(self.chip / "export", self.channel)
        self.created = True
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if self.path.is_dir():
                return
            time.sleep(0.02)
        raise HardwareError(f"PWM {self.pwm_id} channel {self.channel} did not export")

    def _write_if_supported(self, name: str, value: object) -> None:
        p = self.path / name
        if p.exists() and not (p.read_text(encoding="ascii").strip() == str(value)):
            _write(p, value)

    def configure_period(self, period_ns: int, polarity: str = "normal") -> None:
        with self.lock:
            enable = self.path / "enable"
            if enable.exists() and enable.read_text(encoding="ascii").strip() != "0":
                _write(enable, 0)
            duty_path = self.path / "duty_cycle"
            current_period = int((self.path / "period").read_text(encoding="ascii").strip() or 0)
            current_duty = int(duty_path.read_text(encoding="ascii").strip() or 0)
            # On RK3576, duty_cycle cannot be written while period is zero.
            if current_period > 0 and current_duty != 0:
                _write(duty_path, 0)
            _write(self.path / "period", int(period_ns))
            # Polarity is accepted only after period is non-zero and while off.
            self._write_if_supported("polarity", polarity)
            _write(duty_path, 0)

    def set_duty_ns(self, duty_ns: int) -> None:
        with self.lock:
            current = int((self.path / "duty_cycle").read_text(encoding="ascii").strip() or 0)
            if current != int(duty_ns):
                _write(self.path / "duty_cycle", int(duty_ns))

    def enable(self, on: bool) -> None:
        with self.lock:
            current = (self.path / "enable").read_text(encoding="ascii").strip()
            value = "1" if on else "0"
            if current != value:
                _write(self.path / "enable", value)

    def close(self, unexport: bool = False) -> None:
        with self.lock:
            try:
                self.enable(False)
            except HardwareError:
                pass
            if unexport and self.created:
                try:
                    _write(self.chip / "unexport", self.channel)
                except HardwareError:
                    pass


class ServoOutput:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.pwm = PwmChannel(str(cfg["pwm_id"]))
        self.period_ns = 20_000_000
        self.angle = float(cfg["initial_angle"])
        self._enabled = True
        self.pwm.configure_period(self.period_ns)
        self.set_angle(self.angle)
        self.pwm.enable(True)

    def pulse_us_for_angle(self, angle: float) -> int:
        range_deg = float(self.cfg["range_deg"])
        return int(round(500.0 + (float(angle) / range_deg) * 2000.0))

    def clamp_angle(self, angle: float) -> float:
        return min(float(self.cfg["max_angle"]), max(float(self.cfg["min_angle"]), float(angle)))

    def set_angle(self, angle: float) -> float:
        angle = self.clamp_angle(angle)
        pulse_us = self.pulse_us_for_angle(angle)
        self.pwm.set_duty_ns(pulse_us * 1000)
        self.angle = angle
        return angle

    def suspend(self) -> None:
        """Stop holding torque while keeping the current servo angle."""
        self.pwm.enable(False)
        self._enabled = False

    def resume(self) -> None:
        if not self._enabled:
            self.set_angle(self.angle)
            self.pwm.enable(True)
            self._enabled = True

    def close(self) -> None:
        if not bool(self.cfg.get("keep_enabled_on_exit", False)):
            try:
                self.suspend()
            finally:
                self.pwm.close(unexport=False)


class FanOutput:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.pwm = PwmChannel(str(cfg["pwm_id"]))
        self.frequency_hz = int(cfg["frequency_hz"])
        self.period_ns = int(round(1_000_000_000 / self.frequency_hz))
        self.polarity = str(cfg.get("polarity", "normal"))
        self.pwm.configure_period(self.period_ns, self.polarity)
        self.duty_ratio = 0.0
        self.enabled = False
        self.off()

    @property
    def levels(self) -> dict[str, float]:
        return {str(k): float(v) for k, v in self.cfg["levels"].items()}

    def set_level(self, level: str) -> float:
        if level == "off":
            self.off()
            return 0.0
        if level not in self.levels:
            raise ValueError(f"unknown fan level: {level}")
        ratio = self.levels[level]
        return self.set_ratio(ratio)

    def set_ratio(self, ratio: float) -> float:
        ratio = min(1.0, max(0.0, float(ratio)))
        self.duty_ratio = ratio
        if ratio <= 0:
            self.off()
            return 0.0
        duty_ns = int(round(self.period_ns * ratio))
        self.pwm.set_duty_ns(duty_ns)
        self.pwm.enable(True)
        self.enabled = True
        return ratio

    def off(self) -> None:
        self.pwm.set_duty_ns(0)
        if self.polarity == "inversed":
            # An active-low control input is off while the signal stays high.
            self.pwm.enable(True)
        else:
            self.pwm.enable(False)
        self.enabled = False
        self.duty_ratio = 0.0

    def close(self) -> None:
        self.off()
        if self.polarity != "inversed":
            self.pwm.close(unexport=self.pwm.created)
