from __future__ import annotations

import array
import json
import sys
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from smart_fan.audio import AudioAnnouncer  # noqa: E402


class TestAudioAssets(unittest.TestCase):
    def test_every_manifest_phrase_has_wav(self):
        base = ROOT / "assets" / "voice"
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("wake", manifest)
        self.assertIn("standby", manifest)
        for key in manifest:
            path = base / "wav" / f"{key}.wav"
            self.assertTrue(path.is_file(), key)
            self.assertGreater(path.stat().st_size, 1000, key)

    def test_wav_files_match_speaker_format(self):
        base = ROOT / "assets" / "voice"
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        for key in manifest:
            path = base / "wav" / f"{key}.wav"
            with wave.open(str(path), "rb") as wav:
                self.assertEqual(wav.getnchannels(), 1, key)
                self.assertEqual(wav.getsampwidth(), 2, key)
                self.assertEqual(wav.getframerate(), 48000, key)
                minimum_seconds = 3.5 if key.endswith("_en") else 2.0
                self.assertGreaterEqual(
                    wav.getnframes() / wav.getframerate(), minimum_seconds, key
                )
                samples = array.array("h", wav.readframes(wav.getnframes()))
            if sys.byteorder != "little":
                samples.byteswap()
            peak = max(abs(sample) for sample in samples)
            self.assertGreater(peak, 1000, key)
            self.assertLessEqual(peak, 32767, key)

    def test_missing_asset_is_reported(self):
        ann = AudioAnnouncer(
            {
                "enabled": True,
                "audio_device": "null",
                "assets_dir": "/tmp/does-not-exist-smart-fan",
                "mixer_card": 0,
                "volume": "80%",
                "queue_size": 2,
            }
        )
        self.assertFalse(ann.announce("missing"))
        self.assertIn("missing voice asset", ann.status()["last_error"])


if __name__ == "__main__":
    unittest.main()
