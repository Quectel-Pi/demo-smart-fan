from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "device": {"name": "smart-fan-demo", "log_level": "info"},
    "vision": {
        "enabled": True,
        "binary": "/userdata/smart-fan/bin/fan_vision",
        "model": "/userdata/smart-fan/models/yolov8s-640-640.rknn",
        "device": "/dev/video73",
        "width": 640,
        "height": 480,
        "fps": 30,
        "infer_fps": 10,
        "confidence": 0.30,
        "nms": 0.45,
        "core_mask": 0,
        "snapshot": "/userdata/smart-fan/state/current.jpg",
        "snapshot_fps": 15.0,
        "stale_sec": 1.0,
        "min_height_ratio": 0.12,
        "min_aspect": 0.55,
        "targeting": {
            "prefer_group_count": True,
            "group_distance": 0.12,
            "min_height": 0.12,
            "max_height": 0.98,
            "min_area": 0.008,
            "max_center_jump": 0.22,
            "switch_confirm_sec": 0.8,
            "detection_hold_sec": 1.0,
        },
    },
    "servo": {
        "pwm_id": "2ade3000.pwm",
        "range_deg": 270.0,
        "initial_angle": 180.0,
        "center_angle": 180.0,
        "min_angle": 20.0,
        "max_angle": 250.0,
        "invert": True,
        "deadband": 0.03,
        "kp": 120.0,
        "kd": 6.0,
        "max_rate_deg_s": 55.0,
        "max_step_deg": 2.75,
        "min_tracking_height": 0.12,
        "soft_start_sec": 0.8,
        "acquire_rate_deg_s": 28.0,
        "hold_sec": 3.0,
        "center_after_sec": 10.0,
        "keep_enabled_on_exit": False,
    },
    "fan": {
        "pwm_id": "2add5000.pwm",
        "physical_pin": "40Pin-35 / GPIO2_C6 / PWM1_CH5_M2",
        "frequency_hz": 25000,
        "polarity": "inversed",
        "levels": {"off": 0.0, "low": 0.70, "medium": 0.80, "high": 0.90, "max": 1.0},
        "default_level": "medium",
    },
    "voice": {
        "enabled": True,
        "audio_device": "plughw:CARD=rockchipes8389,DEV=0",
        "sample_rate": 16000,
        "channels": 1,
        "sample_format": "S16_LE",
        "mixer_card": 0,
        "capture_volume": 225,
        "capture_pga": 6,
        "capture_warmup_sec": 1.0,
        "min_input_peak": 1000,
        "min_input_peak_en": 550,
        "min_input_peak_wake_en": 500,
        "min_input_rms": 90.0,
        "min_speech_sec": 0.3,
        "min_speech_sec_en": 0.22,
        "min_speech_sec_wake_en": 0.18,
        "endpoint_silence_sec": 0.7,
        "max_utterance_sec": 7.0,
        "partial_confirm_chunks": 2,
        "unrecognized_cooldown_sec": 2.0,
        "wake_retry_sec": 4.0,
        "vosk_lib": "/userdata/smart-fan/vendor/vosk/libvosk.so",
        "model": "/userdata/smart-fan/models/vosk-model-small-cn-0.22",
        "model_en": "/userdata/smart-fan/models/vosk-model-small-en-us-0.15",
        "enabled_languages": ["zh", "en"],
        "wake_word_en": "hey fan",
        "announce_wake_en": True,
        "wake_timeout_sec": 5.0,
        "wake_timeout_sec_en": 10.0,
        "wake_retry_sec_en": 6.0,
        "command_cooldown_sec": 1.5,
    },
    "timer": {
        "default_minutes": 10,
        "persist_path": "/userdata/smart-fan/state/timer.json",
    },
    "speaker": {
        "enabled": True,
        "audio_device": "plughw:CARD=rockchipes8389,DEV=0",
        "assets_dir": "/userdata/smart-fan/voice",
        "mixer_card": 0,
        "volume": "80%",
        "queue_size": 4,
        "voice_guard_sec": 0.6,
    },
    "behavior": {
        "search_after_sec": 5.0,
        "search_speed_deg_s": 12.0,
        "search_min_angle": 60.0,
        "search_max_angle": 220.0,
        "standby_after_sec": 60.0,
        "auto_off_enabled": True,
        "found_announce_cooldown_sec": 20.0,
        "target_confirm_sec": 0.3,
    },
    "control": {"hz": 20.0},
    "api": {"listen": "0.0.0.0", "port": 8090},
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("configuration root must be an object")
    cfg = _merge(DEFAULTS, data)
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    servo = cfg["servo"]
    if float(servo["range_deg"]) <= 0:
        raise ValueError("servo.range_deg must be > 0")
    if not float(servo["min_angle"]) <= float(servo["center_angle"]) <= float(servo["max_angle"]):
        raise ValueError("servo center_angle must be within min_angle..max_angle")
    if not 0 <= float(servo["deadband"]) < 0.5:
        raise ValueError("servo.deadband must be in [0, 0.5)")
    if int(cfg["api"]["port"]) <= 0 or int(cfg["api"]["port"]) > 65535:
        raise ValueError("api.port is invalid")
    if cfg["fan"].get("polarity", "normal") not in ("normal", "inversed"):
        raise ValueError("fan.polarity must be normal or inversed")
    if not isinstance(cfg["behavior"].get("auto_off_enabled"), bool):
        raise ValueError("behavior.auto_off_enabled must be a boolean")
    languages = cfg["voice"].get("enabled_languages", [])
    if not isinstance(languages, list) or not languages:
        raise ValueError("voice.enabled_languages must be a non-empty list")
    if not set(languages).issubset({"zh", "en"}):
        raise ValueError("voice.enabled_languages supports only zh and en")
    levels = cfg["fan"]["levels"]
    if cfg["fan"]["default_level"] not in levels:
        raise ValueError("fan.default_level must exist in fan.levels")
    for name, ratio in levels.items():
        if not 0.0 <= float(ratio) <= 1.0:
            raise ValueError(f"fan level {name} must be in [0, 1]")
