#!/usr/bin/env python3
"""Generate the smart-fan speaker library with the open-source MeloTTS voice.

The generated WAV files are 48 kHz, 16-bit, mono PCM so the board does not need
Python TTS packages at runtime. Run this tool on the development host whenever
assets/voice/manifest.json changes.
"""

from __future__ import annotations

import argparse
import json
import os
import wave
from fractions import Fraction
from pathlib import Path
from typing import Final

import numpy as np

ROOT: Final = Path(__file__).resolve().parents[1]
VOICE_DIR: Final = ROOT / "assets" / "voice"
MANIFEST_PATH: Final = VOICE_DIR / "manifest.json"
WAV_DIR: Final = VOICE_DIR / "wav"
MP3_DIR: Final = VOICE_DIR / "mp3"

MODEL_REPO: Final = "wolfofbackstreet/melotts_chinese_mix_english_onnx"
SOURCE_REPO: Final = "myshell-ai/MeloTTS-Chinese"
PUNCTUATION: Final = "!?…,.'-"
LEVEL_KEYS: Final = (
    "level_low",
    "level_medium",
    "level_high",
    "level_max",
    "level_low_en",
    "level_medium_en",
    "level_high_en",
    "level_max_en",
)
ZH_PUNCTUATION: Final = {"，": ",", "。": ".", "！": "!", "？": "?"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(os.environ.get("SMART_FAN_TTS_MODEL_DIR", "/tmp/smart-fan-melotts-zh")),
        help="directory containing model.onnx, lexicon.txt, and tokens.txt",
    )
    parser.add_argument("--speed-length-scale", type=float, default=1.95)
    parser.add_argument(
        "--level-speed-length-scale",
        type=float,
        default=2.20,
        help="slower length scale used for the four Chinese fan-level announcements",
    )
    parser.add_argument(
        "--english-speed-length-scale",
        type=float,
        default=3.30,
        help="English length scale; larger values speak more slowly",
    )
    parser.add_argument(
        "--english-level-speed-length-scale",
        type=float,
        default=3.45,
        help="English length scale used for the four fan-level announcements",
    )
    parser.add_argument(
        "--english-min-duration",
        type=float,
        default=3.60,
        help="minimum English announcement duration in seconds",
    )
    parser.add_argument("--peak", type=float, default=0.62, help="normalized peak level in 0..1")
    parser.add_argument(
        "--level-peak",
        type=float,
        default=0.78,
        help="higher peak level for announcements played over fan noise",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=2.20,
        help="minimum duration in seconds for every announcement",
    )
    parser.add_argument("--no-mp3", action="store_true", help="only write the board playback WAV files")
    parser.add_argument("--only", action="append", help="generate only the named manifest key(s)")
    return parser.parse_args()


def ensure_model(model_dir: Path) -> Path:
    required = [model_dir / name for name in ("model.onnx", "lexicon.txt", "tokens.txt")]
    if all(path.is_file() for path in required):
        return model_dir
    from huggingface_hub import snapshot_download

    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"downloading MeloTTS Chinese model to {model_dir}")
    snapshot_download(
        repo_id=MODEL_REPO,
        local_dir=str(model_dir),
        allow_patterns=["model.onnx", "lexicon.txt", "tokens.txt", "README.md"],
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"incomplete MeloTTS model: {', '.join(missing)}")
    return model_dir


class Lexicon:
    def __init__(self, model_dir: Path) -> None:
        self.tokens: dict[str, int] = {}
        for line in (model_dir / "tokens.txt").read_text(encoding="utf-8").splitlines():
            token, index = line.split()
            self.tokens[token] = int(index)

        self.entries: dict[str, tuple[list[int], list[int]]] = {}
        for line in (model_dir / "lexicon.txt").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            values = parts[1:]
            midpoint = len(values) // 2
            phones = [self.tokens[value] for value in values[:midpoint]]
            tones = [int(value) for value in values[midpoint:]]
            self.entries[parts[0]] = (phones, tones)

        for punctuation in PUNCTUATION:
            self.entries[punctuation] = ([self.tokens[punctuation]], [0])
        self.entries[" "] = ([self.tokens["_"]], [0])

    def convert(self, token: str) -> tuple[list[int], list[int]]:
        token = ZH_PUNCTUATION.get(token, token)
        entry = self.entries.get(token)
        if entry is not None:
            return list(entry[0]), list(entry[1])
        if len(token) > 1:
            phones: list[int] = []
            tones: list[int] = []
            for character in token:
                part_phones, part_tones = self.convert(character)
                phones.extend(part_phones)
                tones.extend(part_tones)
            return phones, tones
        raise ValueError(f"character is missing from the MeloTTS lexicon: {token!r}")


class MeloVoice:
    def __init__(self, model_dir: Path) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = min(4, os.cpu_count() or 1)
        self.session = ort.InferenceSession(
            str(model_dir / "model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        metadata = self.session.get_modelmeta().custom_metadata_map
        self.sample_rate = int(metadata["sample_rate"])
        self.speaker_id = int(metadata["speaker_id"])
        self.add_blank = int(metadata["add_blank"])
        self.lexicon = Lexicon(model_dir)

    def render(
        self,
        text: str,
        *,
        length_scale: float,
        noise_scale: float = 0.62,
        noise_scale_w: float = 0.8,
    ) -> tuple[np.ndarray, int]:
        import jieba

        phones: list[int] = []
        tones: list[int] = []
        for word in jieba.cut(text.lower(), HMM=True):
            word_phones, word_tones = self.lexicon.convert(word)
            phones.extend(word_phones)
            tones.extend(word_tones)
        if not phones:
            raise ValueError(f"no pronounceable tokens in text: {text!r}")

        if self.add_blank:
            punctuated = [0] * (2 * len(phones) + 1)
            toned = [0] * (2 * len(tones) + 1)
            punctuated[1::2] = phones
            toned[1::2] = tones
            phones = punctuated
            tones = toned

        x = np.asarray([phones], dtype=np.int64)
        tone_array = np.asarray([tones], dtype=np.int64)
        audio = self.session.run(
            ["y"],
            {
                "x": x,
                "x_lengths": np.asarray([x.shape[-1]], dtype=np.int64),
                "tones": tone_array,
                "sid": np.asarray([self.speaker_id], dtype=np.int64),
                "noise_scale": np.asarray([noise_scale], dtype=np.float32),
                "noise_scale_w": np.asarray([noise_scale_w], dtype=np.float32),
                "length_scale": np.asarray([length_scale], dtype=np.float32),
            },
        )[0][0][0]
        return np.asarray(audio, dtype=np.float32), self.sample_rate


def resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    from scipy.signal import resample_poly

    if source_rate == target_rate:
        return audio
    ratio = Fraction(target_rate, source_rate)
    return resample_poly(audio, ratio.numerator, ratio.denominator).astype(np.float32)


def prepare_wav(audio: np.ndarray, source_rate: int, target_rate: int, peak: float) -> np.ndarray:
    if not 0.0 < peak <= 1.0:
        raise ValueError("--peak must be in (0, 1]")
    audio = resample(audio, source_rate, target_rate)
    audio = audio - float(np.mean(audio))

    fade_samples = min(int(round(target_rate * 0.008)), audio.size // 2)
    if fade_samples:
        fade = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32) ** 2
        audio[:fade_samples] *= fade
        audio[-fade_samples:] *= fade[::-1]

    leading = np.zeros(int(round(target_rate * 0.06)), dtype=np.float32)
    trailing = np.zeros(int(round(target_rate * 0.08)), dtype=np.float32)
    audio = np.concatenate((leading, audio, trailing))

    maximum = float(np.max(np.abs(audio)))
    if maximum <= 1e-7:
        raise ValueError("TTS produced silence")
    return np.asarray(audio * (peak / maximum), dtype=np.float32)


def render_announcement(
    voice: MeloVoice,
    text: str,
    *,
    length_scale: float,
    peak: float,
    min_duration: float,
    sample_rate: int = 48000,
) -> tuple[np.ndarray, float, float]:
    if min_duration <= 0:
        raise ValueError("--min-duration must be positive")

    current_scale = length_scale
    prepared = np.empty(0, dtype=np.float32)
    for _ in range(4):
        audio, source_rate = voice.render(text, length_scale=current_scale)
        prepared = prepare_wav(audio, source_rate, sample_rate, peak)
        duration = len(prepared) / sample_rate
        if duration >= min_duration:
            return prepared, duration, current_scale
        current_scale *= max(1.01, min_duration / duration * 1.02)

    # The voice has already been slowed deliberately; this tiny guard only
    # covers rounding or TTS timing jitter when the final pass lands just short.
    missing_samples = max(0, int(round((min_duration - duration) * sample_rate)))
    prepared = np.concatenate((prepared, np.zeros(missing_samples, dtype=np.float32)))
    return prepared, len(prepared) / sample_rate, current_scale


def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    pcm = np.clip(np.rint(audio * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


def write_mp3(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    import lameenc

    mp3_rate = 24000
    mp3_audio = resample(audio, sample_rate, mp3_rate)
    pcm = np.clip(np.rint(mp3_audio * 32767.0), -32768, 32767).astype("<i2")
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(48)
    encoder.set_in_sample_rate(mp3_rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    path.write_bytes(encoder.encode(pcm.tobytes()) + encoder.flush())


def main() -> int:
    args = parse_args()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    selected = set(args.only or manifest)
    unknown = selected.difference(manifest)
    if unknown:
        raise SystemExit(f"unknown manifest key(s): {', '.join(sorted(unknown))}")

    model_dir = ensure_model(args.model_dir)
    voice = MeloVoice(model_dir)
    WAV_DIR.mkdir(parents=True, exist_ok=True)
    if not args.no_mp3:
        MP3_DIR.mkdir(parents=True, exist_ok=True)

    print(f"voice: {SOURCE_REPO} via {MODEL_REPO} (MIT)")
    for key in manifest:
        if key not in selected:
            continue
        text = str(manifest[key])
        is_english = key.endswith("_en")
        is_level = key in LEVEL_KEYS
        if is_english:
            requested_scale = (
                args.english_level_speed_length_scale
                if is_level
                else args.english_speed_length_scale
            )
            min_duration = args.english_min_duration
        else:
            requested_scale = (
                args.level_speed_length_scale
                if is_level
                else args.speed_length_scale
            )
            min_duration = args.min_duration
        peak = args.level_peak if is_level else args.peak
        prepared, duration, actual_scale = render_announcement(
            voice,
            text,
            length_scale=requested_scale,
            peak=peak,
            min_duration=min_duration,
        )
        wav_path = WAV_DIR / f"{key}.wav"
        write_wav(wav_path, prepared, 48000)
        detail = f"{duration:.2f}s, scale={actual_scale:.2f}"
        if not args.no_mp3:
            write_mp3(MP3_DIR / f"{key}.mp3", prepared, 48000)
            detail += ", WAV + MP3"
        else:
            detail += ", WAV"
        print(f"  {key:16} {text}  ({detail})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
