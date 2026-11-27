#!/usr/bin/env python3
"""Interactively find safe servo endpoints and update smart-fan settings."""

from __future__ import annotations

import argparse
import json
import math
import os
import select
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path
from typing import Any

PERIOD_NS = 20_000_000
PWM_ROOT = Path("/sys/class/pwm")
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "smart_fan.json"


def pulse_us_for_angle(angle: float, range_deg: float) -> int:
    if range_deg <= 0:
        raise ValueError("servo range must be > 0")
    return int(round(500.0 + (float(angle) / float(range_deg)) * 2000.0))


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def _write(path: Path, value: str | int) -> None:
    path.write_text(f"{value}\n", encoding="ascii")


def find_pwm_chip(pwm_id: str) -> Path:
    for chip in sorted(PWM_ROOT.glob("pwmchip*")):
        try:
            target = chip.resolve(strict=True)
        except OSError:
            continue
        if f"/{pwm_id}/" in f"{target}/":
            return chip
    raise RuntimeError(f"未找到 PWM 控制器 {pwm_id!r}（GPIO2_D3 / PWM2_CH3_M2）")


def service_is_active(name: str = "smart-fan.service") -> bool:
    if shutil.which("systemctl") is None:
        return False
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


class ServoPwm:
    def __init__(
        self,
        pwm_id: str,
        range_deg: float,
        test_min: float,
        test_max: float,
        dry_run: bool,
    ) -> None:
        self.pwm_id = pwm_id
        self.range_deg = range_deg
        self.test_min = test_min
        self.test_max = test_max
        self.dry_run = dry_run
        self.chip: Path | None = None
        self.pwm: Path | None = None
        self.enabled = False
        if not dry_run:
            self.chip = find_pwm_chip(pwm_id)
            self.pwm = self.chip / "pwm0"
            if not self.pwm.exists():
                _write(self.chip / "export", 0)
                deadline = time.monotonic() + 2.0
                while not self.pwm.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                if not self.pwm.exists():
                    raise RuntimeError(f"PWM {pwm_id} channel 0 导出失败")
            _write(self.pwm / "enable", 0)
            _write(self.pwm / "duty_cycle", 0)
            _write(self.pwm / "period", PERIOD_NS)
            _write(self.pwm / "polarity", "normal")

    def write_angle(self, angle: float) -> float:
        angle = clamp(angle, self.test_min, self.test_max)
        pulse_us = pulse_us_for_angle(angle, self.range_deg)
        if self.dry_run:
            return angle
        assert self.pwm is not None
        _write(self.pwm / "duty_cycle", pulse_us * 1000)
        if not self.enabled:
            _write(self.pwm / "enable", 1)
            self.enabled = True
        return angle

    def move_to(self, target: float, speed_deg_s: float) -> float:
        target = clamp(target, self.test_min, self.test_max)
        start = self.angle
        distance = target - start
        if abs(distance) < 0.05:
            return self.write_angle(target)
        max_delta = max(0.5, speed_deg_s * 0.05)
        steps = max(1, int(math.ceil(abs(distance) / max_delta)))
        angle = start
        for index in range(1, steps + 1):
            angle = start + distance * index / steps
            self.write_angle(angle)
            if index < steps:
                time.sleep(0.05)
        return angle

    @property
    def angle(self) -> float:
        return getattr(self, "_angle", 0.0)

    @angle.setter
    def angle(self, value: float) -> None:
        self._angle = float(value)

    def disable(self) -> None:
        if self.dry_run or self.pwm is None or not self.enabled:
            return
        _write(self.pwm / "enable", 0)
        self.enabled = False


class Calibrator:
    def __init__(self, args: argparse.Namespace, cfg: dict[str, Any], pwm: ServoPwm) -> None:
        self.args = args
        self.config_path = args.config
        self.cfg = cfg
        self.pwm = pwm
        servo = cfg["servo"]
        self.step_deg = float(args.step)
        self.fast_step_deg = float(args.fast_step)
        self.configured_center = float(servo["center_angle"])
        self.pwm.angle = self.pwm.write_angle(self.configured_center)
        self.min_mark: float | None = None
        self.max_mark: float | None = None
        self.center_mark = self.configured_center

    def status(self) -> None:
        angle = self.pwm.angle
        pulse = pulse_us_for_angle(angle, self.pwm.range_deg)
        low = "未标记" if self.min_mark is None else f"{self.min_mark:.1f}°"
        high = "未标记" if self.max_mark is None else f"{self.max_mark:.1f}°"
        print(
            f"当前={angle:.1f}°  脉宽={pulse}µs  "
            f"中点={self.center_mark:.1f}°  左限={low}  右限={high}"
        )

    def help(self) -> None:
        print(
            "操作: a/← 左移  d/→ 右移  A/Shift+← 快速左移  D/Shift+→ 快速右移\n"
            "      c 回中点  1 标记左限  2 标记中点  3 标记右限\n"
            "      s 保存配置  i 状态  ? 帮助  q 退出并回中"
        )

    def move(self, delta: float) -> None:
        target = clamp(self.pwm.angle + delta, self.pwm.test_min, self.pwm.test_max)
        self.pwm.angle = self.pwm.write_angle(target)
        time.sleep(float(self.args.settle_ms) / 1000.0)
        self.status()
        if target in (self.pwm.test_min, self.pwm.test_max):
            print("已到本次测试的软件边界；若出现堵转声，请立即反向移动。")

    def go_center(self) -> None:
        self.pwm.angle = self.pwm.move_to(self.center_mark, float(self.args.move_speed))
        time.sleep(float(self.args.settle_ms) / 1000.0)
        self.status()

    def mark_min(self) -> None:
        self.min_mark = round(self.pwm.angle, 1)
        print(f"已标记左限 {self.min_mark:.1f}°")

    def mark_center(self) -> None:
        self.center_mark = round(self.pwm.angle, 1)
        print(f"已标记中点 {self.center_mark:.1f}°")

    def mark_max(self) -> None:
        self.max_mark = round(self.pwm.angle, 1)
        print(f"已标记右限 {self.max_mark:.1f}°")

    def save(self) -> bool:
        if self.min_mark is None or self.max_mark is None:
            print("保存失败：请先按 1 标记左限，再按 3 标记右限。")
            return False
        if not self.min_mark < self.center_mark < self.max_mark:
            print("保存失败：角度必须满足 左限 < 中点 < 右限。")
            return False

        margin = float(self.args.margin)
        saved_min = round(self.min_mark + margin, 1)
        saved_max = round(self.max_mark - margin, 1)
        if not saved_min < self.center_mark < saved_max:
            print(f"保存失败：扣除 {margin:g}° 安全余量后，中点不在新范围内。")
            return False

        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        servo = data.setdefault("servo", {})
        servo["min_angle"] = saved_min
        servo["max_angle"] = saved_max
        servo["center_angle"] = self.center_mark
        servo["initial_angle"] = self.center_mark

        behavior = data.get("behavior")
        if isinstance(behavior, dict):
            if "search_min_angle" in behavior:
                behavior["search_min_angle"] = max(float(behavior["search_min_angle"]), saved_min)
            if "search_max_angle" in behavior:
                behavior["search_max_angle"] = min(float(behavior["search_max_angle"]), saved_max)

        backup = self.config_path.with_suffix(self.config_path.suffix + ".bak")
        shutil.copy2(self.config_path, backup)
        temporary = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.config_path)
        print(
            f"已保存: min={saved_min:.1f}° center={self.center_mark:.1f}° "
            f"max={saved_max:.1f}°（安全余量 {margin:g}°）\n备份: {backup}"
        )
        return True


def _read_key(fd: int) -> str:
    data = os.read(fd, 1)
    if data != b"\x1b":
        return data.decode("utf-8", errors="ignore")
    ready, _, _ = select.select([fd], [], [], 0.02)
    if not ready:
        return "escape"
    sequence = os.read(fd, 2)
    return {
        b"[D": "left",
        b"[C": "right",
        b"[A": "fast-left",
        b"[B": "fast-right",
    }.get(sequence, "escape")


def run_interactive(cal: Calibrator) -> None:
    cal.help()
    cal.status()
    stdin_fd = sys.stdin.fileno()
    if sys.stdin.isatty():
        old_settings = termios.tcgetattr(stdin_fd)
        try:
            tty.setcbreak(stdin_fd)
            while True:
                key = _read_key(stdin_fd)
                lowered = key.lower()
                if key in ("left", "a", "-"):
                    cal.move(-cal.step_deg)
                elif key in ("right", "d", "+"):
                    cal.move(cal.step_deg)
                elif key == "fast-left" or key == "A":
                    cal.move(-cal.fast_step_deg)
                elif key == "fast-right" or key == "D":
                    cal.move(cal.fast_step_deg)
                elif lowered == "c":
                    cal.go_center()
                elif key in ("1", "["):
                    cal.mark_min()
                elif key in ("2", "m"):
                    cal.mark_center()
                elif key in ("3", "]"):
                    cal.mark_max()
                elif lowered == "s":
                    cal.save()
                elif lowered == "i":
                    cal.status()
                elif key in ("?", "h"):
                    cal.help()
                elif lowered in ("q", "\x03") or key == "escape":
                    break
        finally:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
        print()
        return

    print("stdin 不是终端，请每行输入一个命令后回车。")
    for line in sys.stdin:
        command = line.strip().lower()
        if not command:
            continue
        if command in ("a", "left", "-"):
            cal.move(-cal.step_deg)
        elif command in ("d", "right", "+"):
            cal.move(cal.step_deg)
        elif command in ("aa", "fast-left"):
            cal.move(-cal.fast_step_deg)
        elif command in ("dd", "fast-right"):
            cal.move(cal.fast_step_deg)
        elif command in ("c", "center"):
            cal.go_center()
        elif command in ("1", "min", "["):
            cal.mark_min()
        elif command in ("2", "mid", "m"):
            cal.mark_center()
        elif command in ("3", "max", "]"):
            cal.mark_max()
        elif command in ("s", "save"):
            cal.save()
        elif command in ("i", "status"):
            cal.status()
        elif command in ("?", "h", "help"):
            cal.help()
        elif command in ("q", "quit", "exit"):
            return
        else:
            print(f"未知命令: {command}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="交互式校准舵机左限、右限和中点，并可写回 smart_fan.json。"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="配置文件路径")
    parser.add_argument("--pwm-id", help="覆盖配置中的 PWM 控制器标识")
    parser.add_argument("--range-deg", type=float, help="覆盖舵机总行程，例如 270")
    parser.add_argument("--test-min", type=float, default=0.0, help="允许测试的最小软件角，默认 0")
    parser.add_argument("--test-max", type=float, default=270.0, help="允许测试的最大软件角，默认 270")
    parser.add_argument("--step", type=float, default=2.0, help="普通步进，单位度，默认 2")
    parser.add_argument("--fast-step", type=float, default=10.0, help="快速步进，单位度，默认 10")
    parser.add_argument("--settle-ms", type=float, default=180.0, help="每次移动后的稳定时间，默认 180ms")
    parser.add_argument("--move-speed", type=float, default=40.0, help="回中速度，默认 40°/s")
    parser.add_argument("--margin", type=float, default=2.0, help="保存时左右限各内缩的安全余量，默认 2°")
    parser.add_argument("--skip-service-check", action="store_true", help="不检查 smart-fan.service 是否仍在运行")
    parser.add_argument("--dry-run", action="store_true", help="不访问 PWM，仅测试交互和配置保存")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.config.exists():
        print(f"配置文件不存在: {args.config}", file=sys.stderr)
        return 2
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    servo = cfg["servo"]
    pwm_id = args.pwm_id or str(servo["pwm_id"])
    range_deg = float(args.range_deg if args.range_deg is not None else servo["range_deg"])
    if not 0.0 <= args.test_min < args.test_max <= range_deg:
        print("测试范围必须满足 0 <= test-min < test-max <= range-deg。", file=sys.stderr)
        return 2
    if args.step <= 0 or args.fast_step <= 0 or args.settle_ms < 0 or args.move_speed <= 0:
        print("步进、稳定时间和回中速度必须为有效正数。", file=sys.stderr)
        return 2
    if args.margin < 0:
        print("安全余量不能为负数。", file=sys.stderr)
        return 2
    if not args.dry_run and not args.skip_service_check and service_is_active():
        print(
            "smart-fan.service 仍在运行，其他进程会同时写同一个 PWM。\n"
            "请先执行: systemctl stop smart-fan.service\n"
            "校准完成后再执行: systemctl start smart-fan.service",
            file=sys.stderr,
        )
        return 1

    def stop(signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    old_term = signal.signal(signal.SIGTERM, stop)
    pwm: ServoPwm | None = None
    cal: Calibrator | None = None
    try:
        pwm = ServoPwm(pwm_id, range_deg, args.test_min, args.test_max, args.dry_run)
        cal = Calibrator(args, cfg, pwm)
        print(
            f"{'[DRY RUN] ' if args.dry_run else ''}PWM={pwm_id} "
            f"总行程={range_deg:g}° 测试范围={args.test_min:g}..{args.test_max:g}°"
        )
        run_interactive(cal)
        return 0
    except KeyboardInterrupt:
        print("\n收到中断，准备回中并关闭 PWM。")
        return 130
    finally:
        signal.signal(signal.SIGTERM, old_term)
        if pwm is None:
            return
        try:
            center = cal.center_mark if cal is not None else float(servo["center_angle"])
            pwm.angle = pwm.move_to(center, float(args.move_speed))
            time.sleep(float(args.settle_ms) / 1000.0)
        finally:
            pwm.disable()
        print("PWM 已关闭。" if not args.dry_run else "DRY RUN 结束。")


if __name__ == "__main__":
    raise SystemExit(main())
