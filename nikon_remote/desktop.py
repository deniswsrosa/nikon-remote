"""Desktop mode: run the app in its own window and shut everything down when it closes.

The window is a Chromium-family browser in --app mode with a private profile,
so its process lives exactly as long as the window. When it exits, the server
stops, live view ends and the camera is released.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from .camera import CameraService
from .server import create_app

PORT = 8765
BROWSERS = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"]
PROFILE = Path.home() / ".config" / "nikon-remote" / "window-profile"


def _port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _is_our_server(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def _open_window(url: str) -> subprocess.Popen | None:
    browser = next((shutil.which(b) for b in BROWSERS if shutil.which(b)), None)
    if browser is None:
        return None
    PROFILE.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [
            browser,
            f"--app={url}",
            f"--user-data-dir={PROFILE}",
            "--class=NikonRemote",
            "--window-size=1500,950",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    url = f"http://127.0.0.1:{PORT}/"

    if _port_in_use(PORT):
        if not _is_our_server(PORT):
            sys.exit(f"Port {PORT} is used by another program.")
        # Already running (e.g. started from a terminal): just open another window.
        win = _open_window(url)
        if win is None:
            webbrowser.open(url)
        return

    service = CameraService()
    service.start()
    server = uvicorn.Server(uvicorn.Config(create_app(service), host="127.0.0.1", port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    win = _open_window(url)
    try:
        if win is None:
            # No Chromium-family browser: fall back to a normal tab; Ctrl+C to quit.
            webbrowser.open(url)
            thread.join()
        else:
            win.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        service.stop()
        os._exit(0)


if __name__ == "__main__":
    main()
