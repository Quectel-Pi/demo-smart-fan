from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import re
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

LOG = logging.getLogger(__name__)

WAKE_ZH = "小风 小风"
WAKE_EN = "hey fan"
# Vosk's small English model often spells "Hey Fan" as "Hello Fan" or
# "Hi Fan".  Keep the complete two-word wake phrase in every accepted form;
# standalone "hey" remains invalid to avoid ambient-speech wake-ups.
WAKE_ALIASES_EN = (
    "hey fan",
    "hi fan",
    "hello fan",
    "okay fan",
    "ok fan",
    "hey fans",
    "hi fans",
    "hello fans",
    "hey smart fan",
    "hi smart fan",
    "hello smart fan",
)
GRAMMAR_ZH = [
    WAKE_ZH,
    "小风 小风 打开 风扇",
    "小风 小风 关闭 风扇",
    "小风 小风 一 档",
    "小风 小风 二 档",
    "小风 小风 三 档",
    "小风 小风 四 档",
    "小风 小风 开启 跟随",
    "小风 小风 停止 跟随",
    "小风 小风 定时 十 分钟",
    "小风 小风 定时 十 分钟 后 关闭",
    "小风 小风 定时 半 小时",
    "小风 小风 定时 半 小时 后 关闭",
    "小风 小风 定时 一 小时",
    "小风 小风 定时 一 小时 后 关闭",
    "小风 小风 取消 定时",
    "小风 小风 开启 自动 关机",
    "小风 小风 打开 自动 关机",
    "小风 小风 关闭 自动 关机",
    "小风 小风 停止 自动 关机",
    "打开 风扇",
    "关闭 风扇",
    "一 档",
    "二 档",
    "三 档",
    "四 档",
    "开启 跟随",
    "停止 跟随",
    "定时 十 分钟",
    "定时 十 分钟 后 关闭",
    "定时 半 小时",
    "定时 半 小时 后 关闭",
    "定时 一 小时",
    "定时 一 小时 后 关闭",
    "取消 定时",
    "开启 自动 关机",
    "打开 自动 关机",
    "关闭 自动 关机",
    "停止 自动 关机",
]

EN_COMMANDS = {
    'on': 'fan_on',
    'off': 'fan_off',
    'turn on': 'fan_on',
    'turn off': 'fan_off',
    'switch on': 'fan_on',
    'switch off': 'fan_off',
    'power on': 'fan_on',
    'power off': 'fan_off',
    'start the fan': 'fan_on',
    'stop the fan': 'fan_off',
    'turn on the fan': 'fan_on',
    'turn off the fan': 'fan_off',
    'turn the fan on': 'fan_on',
    'turn the fan off': 'fan_off',
    'switch the fan on': 'fan_on',
    'switch the fan off': 'fan_off',
    'switch on the fan': 'fan_on',
    'switch off the fan': 'fan_off',
    'fan on': 'fan_on',
    'fan off': 'fan_off',
    'level one': 'level_low',
    'level two': 'level_medium',
    'level three': 'level_high',
    'level four': 'level_max',
    'fan speed one': 'level_low',
    'fan speed two': 'level_medium',
    'fan speed three': 'level_high',
    'fan speed four': 'level_max',
    'set speed one': 'level_low',
    'set speed two': 'level_medium',
    'set speed three': 'level_high',
    'set speed four': 'level_max',
    'low speed': 'level_low',
    'medium speed': 'level_medium',
    'high speed': 'level_high',
    'maximum speed': 'level_max',
    'max speed': 'level_max',
    'speed one': 'level_low',
    'speed two': 'level_medium',
    'speed three': 'level_high',
    'speed four': 'level_max',
    'follow me': 'follow_on',
    'track me': 'follow_on',
    'start following me': 'follow_on',
    'start following': 'follow_on',
    'start tracking': 'follow_on',
    'stop following': 'follow_off',
    'stop tracking': 'follow_off',
    'turn following on': 'follow_on',
    'turn following off': 'follow_off',
    'turn tracking on': 'follow_on',
    'turn tracking off': 'follow_off',
    'timer ten minutes': 'timer_10m',
    'timer for ten minutes': 'timer_10m',
    'ten minutes timer': 'timer_10m',
    'timer thirty minutes': 'timer_half_hour',
    'timer for thirty minutes': 'timer_half_hour',
    'thirty minutes timer': 'timer_half_hour',
    'timer one hour': 'timer_1h',
    'timer for one hour': 'timer_1h',
    'one hour timer': 'timer_1h',
    'cancel timer': 'timer_cancel',
    'cancel the timer': 'timer_cancel',
    'stop the timer': 'timer_cancel',
    'enable auto shutdown': 'auto_off_on',
    'disable auto shutdown': 'auto_off_off',
    'turn on auto shutdown': 'auto_off_on',
    'turn off auto shutdown': 'auto_off_off',
    'auto shutdown on': 'auto_off_on',
    'auto shutdown off': 'auto_off_off',
    'enable automatic shutdown': 'auto_off_on',
    'disable automatic shutdown': 'auto_off_off',
    'turn on automatic shutdown': 'auto_off_on',
    'turn off automatic shutdown': 'auto_off_off',
    'clear the timer': 'timer_cancel',
    'automatic shutdown on': 'auto_off_on',
    'automatic shutdown off': 'auto_off_off',
}

_EN_TIMER_DURATIONS = {
    'timer_10m': ('ten minutes',),
    'timer_half_hour': ('thirty minutes', 'half an hour'),
    'timer_1h': ('one hour', 'an hour'),
}
_EN_TIMER_TEMPLATES = (
    'timer {duration}',
    'timer for {duration}',
    'set a timer for {duration}',
    'set timer for {duration}',
    'turn off the fan in {duration}',
    'turn the fan off in {duration}',
    'turn off fan in {duration}',
    'turn fan off in {duration}',
    'shut off the fan in {duration}',
    'shut the fan off in {duration}',
    'shut off fan in {duration}',
    'switch off the fan in {duration}',
    'switch off fan in {duration}',
    'fan off in {duration}',
    'turn off the fan after {duration}',
    'turn the fan off after {duration}',
    'turn off fan after {duration}',
    'turn fan off after {duration}',
    'shut off the fan after {duration}',
    'shut the fan off after {duration}',
    'shut off fan after {duration}',
    'switch off fan after {duration}',
)
for _command, _durations in _EN_TIMER_DURATIONS.items():
    for _duration in _durations:
        for _template in _EN_TIMER_TEMPLATES:
            EN_COMMANDS[_template.format(duration=_duration)] = _command

PHRASES_EN = dict(EN_COMMANDS)

# The four most reliable spellings get full wake+command phrases.  The other
# aliases are still valid wake-only phrases; keeping every combination would
# make the grammar unnecessarily large for the board's small English model.
_GRAMMAR_WAKES_EN = WAKE_ALIASES_EN[:4]
GRAMMAR_EN = list(dict.fromkeys(
    [*WAKE_ALIASES_EN]
    + list(EN_COMMANDS)
    + [
        f"{wake} {command}"
        for wake in _GRAMMAR_WAKES_EN
        for command in EN_COMMANDS
    ]
))

GRAMMARS = {"zh": GRAMMAR_ZH, "en": GRAMMAR_EN}

PHRASES_ZH = {
    "打开风扇": "fan_on",
    "关闭风扇": "fan_off",
    "一档": "level_low",
    "二档": "level_medium",
    "三档": "level_high",
    "四档": "level_max",
    "开启跟随": "follow_on",
    "停止跟随": "follow_off",
    "定时十分钟": "timer_10m",
    "定时十分钟后关闭": "timer_10m",
    "定半小时": "timer_half_hour",
    "定半小时后关闭": "timer_half_hour",
    "定时半小时": "timer_half_hour",
    "定时半小时后关闭": "timer_half_hour",
    "定时一小时": "timer_1h",
    "定时一小时后关闭": "timer_1h",
    "取消定时": "timer_cancel",
    "开启自动关机": "auto_off_on",
    "打开自动关机": "auto_off_on",
    "关闭自动关机": "auto_off_off",
    "停止自动关机": "auto_off_off",
    # Endpointing can occasionally cut the final two characters under fan
    # noise.  These prefixes still carry one unambiguous on/off meaning.
    "打开自动": "auto_off_on",
    "开启自动": "auto_off_on",
    "启动自动": "auto_off_on",
    "关闭自动": "auto_off_off",
    "停止自动": "auto_off_off",
}

PARTIAL_UNSAFE_EN_COMMANDS = frozenset({
    "on",
    "off",
    "turn on",
    "turn off",
    "switch on",
    "switch off",
    "power on",
    "power off",
}) | frozenset(
    phrase
    for phrase in PHRASES_EN
    if any(
        other != phrase and other.startswith(phrase + " ")
        for other in PHRASES_EN
    )
)


def normalize_english(text: str) -> str:
    punctuation = str.maketrans({",": " ", ".": " ", "!": " ", "?": " ", ";": " ", ":": " "})
    return " ".join(str(text).lower().translate(punctuation).split())


def strip_english_wake(text: str) -> tuple[str, str | None]:
    compact = normalize_english(text)
    for wake in sorted(WAKE_ALIASES_EN, key=len, reverse=True):
        if compact == wake:
            return "", wake
        if compact.startswith(wake + " "):
            return compact[len(wake):].strip(), wake
    return compact, None


_EN_TIMER_DURATION_COMMANDS = (
    ("ten minutes", "timer_10m"),
    ("thirty minutes", "timer_half_hour"),
    ("half an hour", "timer_half_hour"),
    ("half hour", "timer_half_hour"),
    ("one hour", "timer_1h"),
    ("an hour", "timer_1h"),
    ("sixty minutes", "timer_1h"),
)


def _english_semantic_command(compact: str) -> str | None:
    """Recognize natural speech when Vosk adds fillers or changes word order."""
    has_timer_action = bool(
        re.search(r"\b(?:timer|turn off|shut off|switch off|fan off)\b", compact)
    )
    if has_timer_action:
        for duration, command in _EN_TIMER_DURATION_COMMANDS:
            if re.search(rf"\b{re.escape(duration)}\b", compact):
                return command

    if re.search(
        r"\b(?:turn|switch)\s+(?:the\s+)?fan\s+on\b"
        r"|\b(?:turn|switch)\s+on\s+(?:the\s+)?fan\b"
        r"|\bstart\s+(?:the\s+)?fan\b"
        r"|\bfan\s+(?:is\s+)?on\b",
        compact,
    ):
        return "fan_on"
    if re.search(
        r"\b(?:turn|switch|shut)\s+(?:the\s+)?fan\s+off\b"
        r"|\b(?:turn|switch|shut)\s+off\s+(?:the\s+)?fan\b"
        r"|\bstop\s+(?:the\s+)?fan\b"
        r"|\bfan\s+(?:is\s+)?off\b",
        compact,
    ):
        return "fan_off"

    level = re.search(
        r"\b(?:level|speed)(?:\s+is|\s+to)?\s+(one|two|three|four)\b",
        compact,
    )
    if level:
        return {
            "one": "level_low",
            "two": "level_medium",
            "three": "level_high",
            "four": "level_max",
        }[level.group(1)]
    return None


def _token_edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_token in enumerate(left, 1):
        current = [left_index]
        for right_index, right_token in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_token != right_token),
            ))
        previous = current
    return previous[-1]


def _fuzzy_english_command(compact: str) -> str | None:
    tokens = compact.split()
    if len(tokens) < 2:
        return None
    distances: dict[str, int] = {}
    for phrase, command in EN_COMMANDS.items():
        distance = _token_edit_distance(tokens, phrase.split())
        distances[command] = min(distances.get(command, distance), distance)
    best = min(distances.values())
    if best > 1:
        return None
    commands = [command for command, distance in distances.items() if distance == best]
    return commands[0] if len(commands) == 1 else None


def phrase_to_command(text: str, language: str = "zh") -> str | None:
    raw = str(text).strip()
    if language == "en":
        compact, _wake = strip_english_wake(raw)
        while compact.startswith("please "):
            compact = compact[7:].strip()
        # Common Vosk substitutions for this small English model.  Exact
        # matches and the constrained wake/awake gate still take precedence.
        compact = compact.replace("turn on an the fan", "turn on the fan")
        compact = compact.replace("fan half", "fan off")
        compact = compact.replace("turn half the fan", "turn off the fan")
        compact = compact.replace("switch half the fan", "switch off the fan")
        compact = compact.replace("power half", "power off")
        exact = PHRASES_EN.get(compact)
        return (
            exact
            if exact is not None
            else _english_semantic_command(compact)
            or _fuzzy_english_command(compact)
        )
    compact = "".join(raw.split())
    if not compact:
        return None
    if compact.startswith("小风小风"):
        compact = compact[4:]
    return PHRASES_ZH.get(compact)


class VoiceListener:
    def __init__(
        self,
        cfg: dict[str, Any],
        on_command: Callable[[str, str], None],
        on_wake: Callable[[str], None] | None = None,
        playback_active: Callable[[], bool] | None = None,
        on_unrecognized: Callable[[str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_command = on_command
        self.on_wake = on_wake
        self.on_unrecognized = on_unrecognized
        self.playback_active = playback_active
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._audio: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._last_text = ""
        self._last_partial = ""
        self._input_rms = 0.0
        self._input_peak = 0
        self._last_command = ""
        self._last_command_at = 0.0
        self._last_unrecognized_at = 0.0
        self._last_error = ""
        enabled_languages = self.cfg.get("enabled_languages", ["zh"])
        self._wake_until: dict[str, float] = {
            str(language): 0.0 for language in enabled_languages
        }
        self._last_trigger: dict[str, float] = {
            str(language): 0.0 for language in enabled_languages
        }
        self._last_language = "zh"
        self._utterance_peak = 0
        self._utterance_rms = 0.0
        self._utterance_active_sec = 0.0
        self._utterance_started_at = 0.0
        self._utterance_has_text = False
        self._speech_seen = False
        self._silence_sec = 0.0
        self._partial_candidate: tuple[str, str] | None = None
        self._partial_candidate_count = 0
        self._endpoint_reason = ""
        self._models: dict[str, int] = {}
        self._recognizers: dict[str, int] = {}
        self._lib: ctypes.CDLL | None = None

    def start(self) -> None:
        if not bool(self.cfg.get("enabled", True)):
            return
        self._thread = threading.Thread(target=self._run, name="voice", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        proc = self._audio
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._release_vosk()

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            awake_until = {
                language: until
                for language, until in self._wake_until.items()
                if until > now
            }
            awake_language = (
                max(awake_until, key=awake_until.get) if awake_until else ""
            )
            command_age = (
                max(0.0, now - self._last_command_at)
                if self._last_command_at > 0.0
                else None
            )
            return {
                "enabled": bool(self.cfg.get("enabled", True)),
                "listening": bool(self._thread and self._thread.is_alive() and self._recognizers),
                "languages": sorted(self._recognizers),
                "last_language": self._last_language,
                "last_text": self._last_text,
                "last_partial": self._last_partial,
                "input_rms": round(self._input_rms, 1),
                "input_peak": self._input_peak,
                "last_command": self._last_command,
                "last_command_age_sec": round(command_age, 1) if command_age is not None else None,
                "awake": bool(awake_language),
                "awake_language": awake_language,
                "wake_remaining_sec": round(max(0.0, awake_until.get(awake_language, 0.0) - now), 1),
                "endpoint_reason": self._endpoint_reason,
                "last_error": self._last_error,
            }

    def _load_vosk(self) -> None:
        lib_path = str(self.cfg["vosk_lib"])
        if not Path(lib_path).is_file():
            raise FileNotFoundError(f"Vosk library missing: {lib_path}")
        lib = ctypes.CDLL(lib_path)
        lib.vosk_set_log_level.argtypes = [ctypes.c_int]
        lib.vosk_set_log_level(-1)
        lib.vosk_model_new.argtypes = [ctypes.c_char_p]
        lib.vosk_model_new.restype = ctypes.c_void_p
        lib.vosk_model_free.argtypes = [ctypes.c_void_p]
        lib.vosk_recognizer_new_grm.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.c_char_p]
        lib.vosk_recognizer_new_grm.restype = ctypes.c_void_p
        lib.vosk_recognizer_free.argtypes = [ctypes.c_void_p]
        lib.vosk_recognizer_accept_waveform.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        lib.vosk_recognizer_accept_waveform.restype = ctypes.c_int
        lib.vosk_recognizer_result.argtypes = [ctypes.c_void_p]
        lib.vosk_recognizer_result.restype = ctypes.c_char_p
        lib.vosk_recognizer_partial_result.argtypes = [ctypes.c_void_p]
        lib.vosk_recognizer_partial_result.restype = ctypes.c_char_p
        lib.vosk_recognizer_final_result.argtypes = [ctypes.c_void_p]
        lib.vosk_recognizer_final_result.restype = ctypes.c_char_p
        lib.vosk_recognizer_reset.argtypes = [ctypes.c_void_p]
        lib.vosk_recognizer_reset.restype = None

        configured = [("zh", str(self.cfg["model"]))]
        requested = {str(v) for v in self.cfg.get("enabled_languages", ["zh", "en"])}
        if "en" in requested:
            configured.append(("en", str(self.cfg.get("model_en", ""))))

        models: dict[str, int] = {}
        recognizers: dict[str, int] = {}
        try:
            for language, model_path in configured:
                if not model_path or not Path(model_path).is_dir():
                    if language == "zh":
                        raise FileNotFoundError(f"Vosk model missing: {model_path}")
                    LOG.warning("English voice model missing: %s", model_path)
                    continue
                model = lib.vosk_model_new(os.fsencode(model_path))
                if not model:
                    raise RuntimeError(f"vosk_model_new failed: {language}")
                models[language] = model
                grammar = json.dumps(GRAMMARS[language], ensure_ascii=False).encode("utf-8")
                rec = lib.vosk_recognizer_new_grm(
                    model, float(self.cfg["sample_rate"]), grammar
                )
                if not rec:
                    raise RuntimeError(f"vosk_recognizer_new_grm failed: {language}")
                recognizers[language] = rec
        except Exception:
            for rec in recognizers.values():
                lib.vosk_recognizer_free(rec)
            for model in models.values():
                lib.vosk_model_free(model)
            raise

        self._lib = lib
        self._models = models
        self._recognizers = recognizers
        self._wake_until = {language: 0.0 for language in recognizers}
        self._last_trigger = {language: 0.0 for language in recognizers}
        LOG.info("voice recognizers ready: %s", ", ".join(sorted(recognizers)))

    def _release_vosk(self) -> None:
        if self._lib:
            for recognizer in self._recognizers.values():
                self._lib.vosk_recognizer_free(recognizer)
            for model in self._models.values():
                self._lib.vosk_model_free(model)
        self._recognizers = {}
        self._models = {}
        self._lib = None

    def _run(self) -> None:
        try:
            self._load_vosk()
        except Exception as exc:  # noqa: BLE001 - app must run without voice
            with self._lock:
                self._last_error = str(exc)
            LOG.error("voice unavailable: %s", exc)
            return

        self._configure_capture()
        c = self.cfg
        cmd = [
            "arecord",
            "-q",
            "-D",
            str(c["audio_device"]),
            "-f",
            str(c["sample_format"]),
            "-r",
            str(c["sample_rate"]),
            "-c",
            str(c["channels"]),
            "-t",
            "raw",
        ]
        backoff = 1.0
        while not self._stop.is_set():
            try:
                LOG.info("starting microphone: %s", " ".join(cmd))
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self._audio = proc
                assert proc.stdout is not None
                backoff = 1.0
                clunk = max(2, int(c["sample_rate"]) // 5) * 2
                self._reset_utterance()
                for recognizer in self._recognizers.values():
                    self._lib.vosk_recognizer_reset(recognizer)
                warmup_bytes = int(
                    float(c["sample_rate"])
                    * int(c["channels"])
                    * 2
                    * max(0.0, float(c.get("capture_warmup_sec", 1.0)))
                )
                while warmup_bytes > 0 and not self._stop.is_set():
                    pcm = proc.stdout.read(min(clunk, warmup_bytes))
                    if not pcm:
                        break
                    warmup_bytes -= len(pcm)
                if warmup_bytes > 0:
                    break
                while not self._stop.is_set():
                    pcm = proc.stdout.read(clunk)
                    if not pcm:
                        break
                    self._accept(pcm)
                code = proc.wait()
                if not self._stop.is_set():
                    self._set_error(f"arecord exited with status {code}")
            except Exception as exc:  # noqa: BLE001
                self._set_error(f"voice loop failed: {exc}")
                LOG.exception("voice loop failed")
            finally:
                self._audio = None
            if self._stop.is_set():
                break
            self._stop.wait(backoff)
            backoff = min(5.0, backoff * 1.5)
        self._release_vosk()

    def _configure_capture(self) -> None:
        card = str(self.cfg.get("mixer_card", 0))
        commands = [
            ["amixer", "-c", card, "sset", "ADC MUX", "AMIC"],
            ["amixer", "-c", card, "sset", "Main Mic", "on"],
            ["amixer", "-c", card, "sset", "Headset Mic", "off"],
            ["amixer", "-c", card, "sset", "ADCL PGA", str(self.cfg.get("capture_pga", 6))],
            ["amixer", "-c", card, "sset", "ADCR PGA", str(self.cfg.get("capture_pga", 6))],
            ["amixer", "-c", card, "sset", "ADCL", str(self.cfg.get("capture_volume", 210))],
            ["amixer", "-c", card, "sset", "ADCR", str(self.cfg.get("capture_volume", 210))],
        ]
        for cmd in commands:
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _set_error(self, text: str) -> None:
        with self._lock:
            self._last_error = text
        LOG.warning("%s", text)

    def _accept(self, pcm: bytes) -> None:
        if not self._lib or not self._recognizers:
            return
        count = len(pcm) // 2
        if count <= 0:
            return
        samples = struct.unpack(f"<{count}h", pcm[: count * 2])
        rms = math.sqrt(sum(x * x for x in samples) / count)
        peak = max(abs(x) for x in samples)
        chunk_sec = count / float(self.cfg["sample_rate"])
        now = time.monotonic()
        with self._lock:
            self._input_rms = rms
            self._input_peak = peak
            self._utterance_peak = max(self._utterance_peak, peak)
            self._utterance_rms = max(self._utterance_rms, rms)
            if rms >= float(self.cfg.get("min_input_rms", 90.0)):
                if not self._speech_seen:
                    self._utterance_started_at = now
                self._speech_seen = True
                self._silence_sec = 0.0
                self._utterance_active_sec += chunk_sec
            elif self._speech_seen:
                self._silence_sec += chunk_sec

        endpoint = False
        partials: list[tuple[str, str]] = []
        for language, recognizer in self._recognizers.items():
            endpoint = bool(
                self._lib.vosk_recognizer_accept_waveform(recognizer, pcm, len(pcm))
            ) or endpoint
            partial_raw = self._lib.vosk_recognizer_partial_result(recognizer)
            if not partial_raw:
                continue
            try:
                partial = str(
                    json.loads(partial_raw.decode("utf-8")).get("text", "")
                ).strip()
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if partial:
                partials.append((language, partial))

        if partials:
            with self._lock:
                self._last_partial = max((text for _lang, text in partials), key=len)
                self._utterance_has_text = True

        # Vosk can wait a long time for an endpoint in fan noise.  Once a
        # complete, unambiguous command has appeared in two consecutive
        # partials, dispatch it immediately instead of waiting for silence.
        candidate = next(
            (
                (language, text)
                for language, text in partials
                if self._partial_is_safe(text, language)
            ),
            None,
        )
        with self._lock:
            if candidate is None:
                self._partial_candidate = None
                self._partial_candidate_count = 0
            elif candidate == self._partial_candidate:
                self._partial_candidate_count += 1
            else:
                self._partial_candidate = candidate
                self._partial_candidate_count = 1
            confirm_chunks = max(1, int(self.cfg.get("partial_confirm_chunks", 2)))
            dispatch_partial = self._partial_candidate_count >= confirm_chunks

        if dispatch_partial and candidate is not None:
            language, text = candidate
            metrics = self._peek_utterance()
            with self._lock:
                self._last_text = text
            if self._handle_text(text, language=language, **metrics):
                self._take_utterance()
                self._endpoint_reason = "partial"
                LOG.info("voice endpoint (%s): %s", language, text)
                self._reset_recognition()
                return

        force_reason = ""
        with self._lock:
            if endpoint:
                force_reason = "vosk"
            elif self._speech_seen and self._utterance_has_text:
                silence_limit = float(
                    self.cfg.get("endpoint_silence_sec", 0.7)
                )
                max_utterance = float(self.cfg.get("max_utterance_sec", 4.0))
                if self._silence_sec >= silence_limit:
                    force_reason = "silence"
                elif self._utterance_active_sec >= max_utterance:
                    force_reason = "max_duration"
        if not force_reason:
            return

        self._endpoint_reason = force_reason
        metrics = self._take_utterance()
        self._dispatch_results(metrics)
        self._reset_recognition()

    def _dispatch_results(self, metrics: dict[str, float | int]) -> None:
        if not self._lib:
            return
        for language, recognizer in self._recognizers.items():
            raw = self._lib.vosk_recognizer_result(recognizer)
            if not raw:
                continue
            try:
                text = str(json.loads(raw.decode("utf-8")).get("text", "")).strip()
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._set_error(f"invalid voice result: {exc}")
                continue
            if not text:
                continue
            with self._lock:
                self._last_text = text
            self._handle_text(text, language=language, **metrics)

    def _partial_is_safe(self, text: str, language: str) -> bool:
        if language != "en":
            return False
        compact, wake = strip_english_wake(text)
        if wake is not None and not compact:
            # Let a standalone wake word finish naturally.  Dispatching it from
            # a partial can play the acknowledgement and cut off a command that
            # is still being spoken in the same sentence.
            return False
        command = phrase_to_command(text, "en")
        return bool(
            compact
            and compact not in PARTIAL_UNSAFE_EN_COMMANDS
            and command
            and command != "fan_off"
        )

    def _reset_recognition(self) -> None:
        if self._lib:
            for recognizer in self._recognizers.values():
                self._lib.vosk_recognizer_reset(recognizer)
        self._reset_utterance()

    def _reset_utterance(self) -> None:
        with self._lock:
            self._utterance_peak = 0
            self._utterance_rms = 0.0
            self._utterance_active_sec = 0.0
            self._utterance_started_at = 0.0
            self._utterance_has_text = False
            self._speech_seen = False
            self._silence_sec = 0.0
            self._partial_candidate = None
            self._partial_candidate_count = 0

    def _peek_utterance(self) -> dict[str, float | int]:
        with self._lock:
            return {
                "peak": self._utterance_peak,
                "rms": self._utterance_rms,
                "active_sec": self._utterance_active_sec,
            }

    def _take_utterance(self) -> dict[str, float | int]:
        with self._lock:
            metrics: dict[str, float | int] = {
                "peak": self._utterance_peak,
                "rms": self._utterance_rms,
                "active_sec": self._utterance_active_sec,
            }
            self._utterance_peak = 0
            self._utterance_rms = 0.0
            self._utterance_active_sec = 0.0
            return metrics

    def _handle_text(
        self,
        text: str,
        *,
        language: str = "zh",
        peak: int | None = None,
        rms: float | None = None,
        active_sec: float | None = None,
    ) -> bool:
        compact = normalize_english(text) if language == "en" else "".join(text.split())
        now = time.monotonic()
        if self.playback_active and self.playback_active():
            LOG.info("ignored voice result during speaker playback: %s", text)
            return False
        is_wake = compact in WAKE_ALIASES_EN if language == "en" else compact == "小风小风"
        if language == "en" and is_wake:
            peak_key = "min_input_peak_wake_en"
            speech_key = "min_speech_sec_wake_en"
        else:
            peak_key = "min_input_peak_en" if language == "en" else "min_input_peak"
            speech_key = "min_speech_sec_en" if language == "en" else "min_speech_sec"
        peak_threshold = int(self.cfg.get(peak_key, self.cfg.get("min_input_peak", 600)))
        if peak is not None and peak < peak_threshold:
            LOG.info(
                "ignored low-level %s voice result: %s peak=%s rms=%.1f active=%.1fs",
                language,
                text,
                peak,
                rms or 0.0,
                active_sec or 0.0,
            )
            return False
        min_speech = float(
            self.cfg.get(speech_key, self.cfg.get("min_speech_sec", 0.3))
        )
        if active_sec is not None and active_sec < min_speech:
            LOG.info(
                "ignored short voice result: %s peak=%s rms=%.1f active=%.1fs",
                text,
                peak or 0,
                rms or 0.0,
                active_sec,
            )
            return False
        if is_wake:
            with self._lock:
                timeout = float(
                    self.cfg.get(
                        f"wake_timeout_sec_{language}", self.cfg["wake_timeout_sec"]
                    )
                )
                self._wake_until[language] = now + timeout
                self._last_command = ""
                self._last_language = language
            LOG.info("voice wake word (%s): %s", language, text)
            if self.on_wake:
                self.on_wake(language)
            return True

        notify_unrecognized = False
        with self._lock:
            has_wake = (
                any(compact.startswith(wake + " ") for wake in WAKE_ALIASES_EN)
                if language == "en"
                else compact.startswith("小风小风")
            )
            awake = has_wake or now <= self._wake_until.get(language, 0.0)
            if not awake:
                return False
            if now - self._last_trigger.get(language, 0.0) < float(
                self.cfg["command_cooldown_sec"]
            ):
                return False
            command = phrase_to_command(text, language)
            if not command:
                retry_timeout = float(
                    self.cfg.get(
                        f"wake_retry_sec_{language}",
                        self.cfg.get("wake_retry_sec", 4.0),
                    )
                )
                self._wake_until[language] = max(
                    self._wake_until.get(language, 0.0), now + retry_timeout
                )
                cooldown = float(self.cfg.get("unrecognized_cooldown_sec", 2.0))
                if (
                    self.on_unrecognized
                    and now - self._last_unrecognized_at >= cooldown
                ):
                    self._last_unrecognized_at = now
                    notify_unrecognized = True
                LOG.info(
                    "ignored unmatched %s voice result: %s peak=%s rms=%.1f active=%.1fs",
                    language,
                    text,
                    peak or 0,
                    rms or 0.0,
                    active_sec or 0.0,
                )
            else:
                self._last_trigger[language] = now
                self._last_command = command
                self._last_command_at = now
                self._wake_until[language] = 0.0
                self._last_language = language

        if notify_unrecognized:
            if self.on_unrecognized:
                self.on_unrecognized(language)
            return False
        if not command:
            return False
        LOG.info("voice command (%s): %s -> %s", language, text, command)
        self.on_command(command, language)
        return True
