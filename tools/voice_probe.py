#!/usr/bin/env python3
"""Live microphone probe for the smart-fan Vosk grammar.

Run on the board. It uses only the Python standard library and the Vosk C API
through ctypes, because the target image has no pip/cffi installed.

Examples:
  python3 voice_probe.py
  python3 voice_probe.py --language en
  python3 voice_probe.py --seconds 6
  python3 voice_probe.py --wav /tmp/command.wav
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from smart_fan.voice import GRAMMARS  # noqa: E402

DEFAULT_LIB = "/userdata/smart-fan/vendor/vosk/libvosk.so"
DEFAULT_MODEL = "/userdata/smart-fan/models/vosk-model-small-cn-0.22"
DEFAULT_MODEL_EN = "/userdata/smart-fan/models/vosk-model-small-en-us-0.15"
DEFAULT_DEVICE = "plughw:CARD=rockchipes8389,DEV=0"


class Vosk:
    def __init__(self, lib_path: str, grammar: list[str]) -> None:
        lib = ctypes.CDLL(lib_path)
        lib.vosk_set_log_level.argtypes = [ctypes.c_int]
        lib.vosk_set_log_level(-1)
        lib.vosk_model_new.argtypes = [ctypes.c_char_p]
        lib.vosk_model_new.restype = ctypes.c_void_p
        lib.vosk_model_free.argtypes = [ctypes.c_void_p]
        lib.vosk_recognizer_new_grm.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float,
            ctypes.c_char_p,
        ]
        lib.vosk_recognizer_new_grm.restype = ctypes.c_void_p
        lib.vosk_recognizer_free.argtypes = [ctypes.c_void_p]
        lib.vosk_recognizer_accept_waveform.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        lib.vosk_recognizer_accept_waveform.restype = ctypes.c_int
        lib.vosk_recognizer_final_result.argtypes = [ctypes.c_void_p]
        lib.vosk_recognizer_final_result.restype = ctypes.c_char_p
        self.lib = lib
        self.grammar = grammar

    def recognize(self, model_path: str, pcm: bytes, sample_rate: int) -> dict:
        model = self.lib.vosk_model_new(os.fsencode(model_path))
        if not model:
            raise RuntimeError(f"failed to load model: {model_path}")
        grammar = json.dumps(self.grammar, ensure_ascii=False)
        recognizer = self.lib.vosk_recognizer_new_grm(
            model, float(sample_rate), grammar.encode("utf-8")
        )
        if not recognizer:
            self.lib.vosk_model_free(model)
            raise RuntimeError("failed to create recognizer")
        try:
            # Vosk returns 1 when an endpoint was detected, 0 otherwise.
            # A zero return is normal for a fixed recording and is not an error.
            self.lib.vosk_recognizer_accept_waveform(recognizer, pcm, len(pcm))
            raw = self.lib.vosk_recognizer_final_result(recognizer)
            return json.loads(raw.decode("utf-8"))
        finally:
            self.lib.vosk_recognizer_free(recognizer)
            self.lib.vosk_model_free(model)


def read_wav(path: str) -> tuple[bytes, int]:
    with wave.open(path, "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise RuntimeError("WAV must be 16-bit mono")
        if wav.getframerate() != 16000:
            raise RuntimeError(f"WAV must be 16kHz, got {wav.getframerate()}")
        return wav.readframes(wav.getnframes()), wav.getframerate()


def record_pcm(device: str, seconds: float, sample_rate: int) -> bytes:
    cmd = [
        "arecord",
        "-q",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-r",
        str(sample_rate),
        "-c",
        "1",
        "-t",
        "raw",
        "-d",
        str(seconds),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lib", default=DEFAULT_LIB)
    parser.add_argument("--language", choices=sorted(GRAMMARS), default="zh")
    parser.add_argument("--model")
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--wav")
    args = parser.parse_args()

    if args.wav:
        pcm, rate = read_wav(args.wav)
    else:
        print(f"Recording {args.seconds:g}s from {args.device} ...", flush=True)
        rate = 16000
        pcm = record_pcm(args.device, args.seconds, rate)

    model = args.model or (DEFAULT_MODEL_EN if args.language == "en" else DEFAULT_MODEL)
    result = Vosk(args.lib, GRAMMARS[args.language]).recognize(model, pcm, rate)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("text") else 2


if __name__ == "__main__":
    raise SystemExit(main())
