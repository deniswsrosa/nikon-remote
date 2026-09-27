"""Shared CameraService → Assist → AudioMonitor → FastAPI bootstrap for entrypoints."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI

from .assist import Assist
from .audio import AudioMonitor
from .camera import CameraService
from .server import create_app


@dataclass
class Runtime:
    service: CameraService
    assist: Assist
    audio: AudioMonitor
    app: FastAPI

    def stop(self) -> None:
        self.audio.stop()
        self.assist.stop()
        self.service.stop()


def build_runtime() -> Runtime:
    """Construct, start, and wire the long-lived services used by both entrypoints."""
    service = CameraService()
    service.start()
    assist = Assist(service)
    assist.start()
    # Keep CameraService._emit internal: entrypoints never assign audio._emit = service._emit.
    audio = AudioMonitor(service._emit)
    audio.start()
    return Runtime(service=service, assist=assist, audio=audio, app=create_app(service, assist, audio))
