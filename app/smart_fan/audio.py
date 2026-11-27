from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


class AudioAnnouncer:
    """Asynchronous fixed-phrase announcer backed by short local WAV files."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.assets_dir = Path(str(cfg["assets_dir"]))
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=max(1, int(cfg["queue_size"])))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._last_key = ""
        self._last_error = ""
        self._last_finished_at = 0.0
        self._voice_guard_sec = max(0.0, float(cfg.get("voice_guard_sec", 0.6)))

    def start(self) -> None:
        if not bool(self.cfg.get("enabled", True)):
            return
        self._configure_mixer()
        self._thread = threading.Thread(target=self._run, name="speaker", daemon=True)
        self._thread.start()
        LOG.info("speaker ready: %s", self.cfg["audio_device"])

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=2.0)

    def announce(self, key: str, replace: bool = False) -> bool:
        if not bool(self.cfg.get("enabled", True)):
            return False
        path = self.assets_dir / f"{key}.wav"
        if not path.is_file():
            with self._lock:
                self._last_error = f"missing voice asset: {path}"
            LOG.warning("%s", self._last_error)
            return False
        if replace:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
        try:
            self._queue.put_nowait(key)
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(key)
                return True
            except (queue.Empty, queue.Full):
                return False

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": bool(self.cfg.get("enabled", True)),
                "playing": bool(self._proc and self._proc.poll() is None),
                "last_key": self._last_key,
                "last_error": self._last_error,
                "queued": self._queue.qsize(),
                "voice_blocked": self._is_listening_blocked_unlocked(),
            }

    def listening_blocked(self) -> bool:
        """Keep the recognizer from hearing queued or just-finished announcements."""
        with self._lock:
            return self._is_listening_blocked_unlocked()

    def _is_listening_blocked_unlocked(self) -> bool:
        playing = bool(self._proc and self._proc.poll() is None)
        queued = self._queue.qsize() > 0
        tail = (
            self._last_finished_at > 0.0
            and time.monotonic() - self._last_finished_at < self._voice_guard_sec
        )
        return playing or queued or tail

    def _configure_mixer(self) -> None:
        card = str(self.cfg.get("mixer_card", 0))
        commands = [
            ["amixer", "-c", card, "sset", "Speaker", "on"],
            ["amixer", "-c", card, "sset", "spk switch", "on"],
            ["amixer", "-c", card, "sset", "DACL", str(self.cfg.get("volume", "80%"))],
            ["amixer", "-c", card, "sset", "DACR", str(self.cfg.get("volume", "80%"))],
        ]
        for cmd in commands:
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                key = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if key is None:
                break
            path = self.assets_dir / f"{key}.wav"
            try:
                proc = subprocess.Popen(
                    ["aplay", "-q", "-D", str(self.cfg["audio_device"]), str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                self._proc = proc
                _, stderr = proc.communicate(timeout=15)
                if proc.returncode != 0:
                    with self._lock:
                        self._last_error = stderr.decode("utf-8", "replace").strip()
                    LOG.warning("speaker playback %s failed: %s", key, self._last_error)
                else:
                    with self._lock:
                        self._last_key = key
                        self._last_error = ""
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._last_error = f"speaker playback failed: {exc}"
                LOG.exception("speaker playback failed")
            finally:
                with self._lock:
                    self._proc = None
                    self._last_finished_at = time.monotonic()
