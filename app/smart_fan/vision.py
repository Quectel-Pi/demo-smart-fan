from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .follower import TargetObservation
from .target import StableTargetSelector, parse_people

LOG = logging.getLogger(__name__)


class VisionReader:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest: TargetObservation | None = None
        self._raw: dict[str, Any] = {}
        self._last_error = ""
        self._process: subprocess.Popen[str] | None = None
        self._restarts = 0
        self._selector = StableTargetSelector(self.cfg.get("targeting", {}))

    def start(self) -> None:
        if not bool(self.cfg.get("enabled", True)):
            return
        if self._thread and self._thread.is_alive():
            return
        self._paused.clear()
        self._thread = threading.Thread(target=self._run, name="vision", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        if not bool(self.cfg.get("enabled", True)):
            return
        self._paused.set()
        proc = self._process
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
        self._mark_invalid()
        LOG.info("vision paused")

    def resume(self) -> None:
        if not bool(self.cfg.get("enabled", True)):
            return
        was_paused = self._paused.is_set()
        self._paused.clear()
        if self._thread is None or not self._thread.is_alive():
            self.start()
        if was_paused:
            LOG.info("vision resumed")

    def stop(self) -> None:
        self._stop.set()
        self._paused.clear()
        proc = self._process
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self._thread:
            self._thread.join(timeout=3.0)

    def latest(self) -> TargetObservation | None:
        with self._lock:
            return self._latest

    def raw(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._raw)

    def status(self) -> dict[str, Any]:
        with self._lock:
            obs = self._latest
            raw = dict(self._raw)
        now = time.monotonic()
        age = None if obs is None else max(0.0, now - obs.received_at)
        return {
            "connected": bool(
                not self._paused.is_set()
                and self._thread
                and self._thread.is_alive()
                and age is not None
                and age < 2.0
            ),
            "paused": self._paused.is_set(),
            "age_sec": age,
            "restarts": self._restarts,
            "last_error": self._last_error,
            "valid": bool(obs and obs.valid and age is not None and age < float(self.cfg["stale_sec"])),
            "count": int(obs.count) if obs else 0,
            "group_count": int(obs.group_count) if obs else 0,
            "direction": str(obs.selection.get("direction", "none")) if obs else "none",
            "target_x": obs.x if obs and obs.valid else None,
            "target_y": obs.y if obs and obs.valid else None,
            "score": obs.score if obs and obs.valid else None,
            "frame": obs.frame if obs else 0,
            "person": obs.person if obs and obs.valid else None,
            "people": obs.people if obs else [],
            "selection": obs.selection if obs and obs.valid else {},
            "raw": raw,
        }

    def _command(self) -> list[str]:
        c = self.cfg
        return [
            str(c["binary"]),
            "--model",
            str(c["model"]),
            "--device",
            str(c["device"]),
            "--width",
            str(c["width"]),
            "--height",
            str(c["height"]),
            "--fps",
            str(c["fps"]),
            "--infer-fps",
            str(c["infer_fps"]),
            "--conf",
            str(c["confidence"]),
            "--nms",
            str(c["nms"]),
            "--core",
            str(c["core_mask"]),
            "--snapshot",
            str(c["snapshot"]),
            "--snapshot-fps",
            str(c["snapshot_fps"]),
            "--min-height",
            str(c.get("min_height_ratio", 0.15)),
            "--min-aspect",
            str(c.get("min_aspect", 0.55)),
        ]

    def _run(self) -> None:
        binary = Path(str(self.cfg["binary"]))
        Path(str(self.cfg["snapshot"])).parent.mkdir(parents=True, exist_ok=True)
        delay = 1.0
        while not self._stop.is_set():
            if self._paused.is_set():
                self._mark_invalid()
                self._paused.wait(0.2)
                continue
            if not binary.is_file():
                with self._lock:
                    self._last_error = f"vision binary missing: {binary}"
                LOG.error("%s", self._last_error)
                self._stop.wait(5.0)
                continue
            try:
                LOG.info("starting vision: %s", " ".join(self._command()))
                proc = subprocess.Popen(
                    self._command(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                self._process = proc
                assert proc.stdout is not None
                delay = 1.0
                for line in proc.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    if line.startswith("{"):
                        self._consume(line)
                    else:
                        LOG.info("vision: %s", line)
                rc = proc.wait()
                if not self._stop.is_set():
                    with self._lock:
                        self._last_error = f"vision exited with status {rc}"
                    LOG.warning("%s", self._last_error)
            except Exception as exc:  # noqa: BLE001 - background process must recover
                with self._lock:
                    self._last_error = f"vision failed: {exc}"
                LOG.exception("vision process failed")
            finally:
                self._process = None
                self._mark_invalid()
            if self._stop.is_set():
                break
            if self._paused.is_set():
                continue
            self._restarts += 1
            self._stop.wait(delay)
            delay = min(5.0, delay * 1.5)

    def _consume(self, line: str) -> None:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            LOG.warning("invalid vision JSON: %s", exc)
            return
        raw_people = obj.get("people") if isinstance(obj.get("people"), list) else []
        image_width = int(obj.get("width", 0))
        image_height = int(obj.get("height", 0))
        people = parse_people(
            (item for item in raw_people if isinstance(item, dict)), image_width, image_height
        )
        choice = self._selector.update(people, time.monotonic())
        selected_x = choice.x if choice.valid else self._selector.last_x
        if selected_x is None:
            selected_x = 0.5
        obs = TargetObservation(
            valid=choice.valid,
            x=selected_x,
            y=choice.y,
            score=choice.score,
            count=choice.count,
            group_count=choice.group_count,
            received_at=time.monotonic(),
            image_width=int(obj.get("width", 0)),
            image_height=int(obj.get("height", 0)),
            frame=int(obj.get("frame", 0)),
            person=choice.as_dict().get("person"),
            people=raw_people,
            selection=choice.as_dict(),
            followable=choice.followable,
        )
        with self._lock:
            self._latest = obs
            self._raw = obj

    def _mark_invalid(self) -> None:
        with self._lock:
            old = self._latest
            self._latest = TargetObservation(
                valid=False,
                x=old.x if old else 0.5,
                y=old.y if old else 0.5,
                count=0,
                received_at=time.monotonic(),
                image_width=old.image_width if old else 0,
                image_height=old.image_height if old else 0,
                frame=old.frame if old else 0,
                followable=False,
            )
