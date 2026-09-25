"""Entry point: `uv run nikon-remote` starts the camera service and opens the UI."""

from __future__ import annotations

import argparse
import logging
import threading
import webbrowser

import uvicorn

from .assist import Assist
from .audio import AudioMonitor
from .camera import CameraService
from .server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Live view and remote control for a USB-tethered Nikon")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--lan",
        action="store_true",
        help="listen on all interfaces so a phone/tablet on the same network can control the camera",
    )
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    service = CameraService()
    service.start()
    assist = Assist(service)
    assist.start()
    audio = AudioMonitor(service._emit)
    audio.start()
    app = create_app(service, assist, audio)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Nikon Remote running at {url}" + ("  (also reachable from your LAN)" if args.lan else ""))
    try:
        uvicorn.run(app, host=host, port=args.port, log_level="warning")
    finally:
        audio.stop()
        assist.stop()
        service.stop()


if __name__ == "__main__":
    main()
