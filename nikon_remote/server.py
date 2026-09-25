"""FastAPI app: serves the UI and bridges browsers to the camera thread over one WebSocket.

Binary messages carry live view frames as: 4-byte big-endian JSON length,
JSON header, JPEG. Text messages carry JSON state, commands and results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import catalog
from .assist import Assist
from .audio import AudioMonitor, list_sources
from .camera import CameraService, UserError
from .ptp import PTPError
from .ptp_names import PTP_PROP_NAMES

log = logging.getLogger("nikon_remote.server")
STATIC = Path(__file__).parent / "static"

ALLOWED_COMMANDS = {
    "set",
    "pc_mode",
    "liveview",
    "focus_at",
    "autofocus",
    "manual_focus",
    "record",
    "sync_clock",
    "refresh",
    "presets",
    "save_preset",
    "delete_preset",
    "apply_preset",
    "restart_lv",
}
ASSIST_COMMANDS = {
    "face_focus": "focus_eyes",
    "face_expose": "expose_for_face",
    "face_remember": "remember_brightness",
    "assist_config": "set_config",
}


class Client:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.frame_event = asyncio.Event()
        self.ready_for_frame = True
        self.last_seq = 0


class Hub:
    def __init__(self, service: CameraService):
        self.service = service
        self.clients: set[Client] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.service.add_listener(lambda kind, payload: loop.call_soon_threadsafe(self._dispatch, kind, payload))

    def _dispatch(self, kind: str, payload) -> None:
        if kind == "frame":
            for c in self.clients:
                c.frame_event.set()
            return
        msg = json.dumps({"type": kind, "data": payload}, default=str)
        for c in self.clients:
            c.outbox.put_nowait(msg)


def create_app(service: CameraService, assist: Assist | None = None, audio: AudioMonitor | None = None) -> FastAPI:
    app = FastAPI(title="Nikon Remote")
    hub = Hub(service)
    latest = {"face": None, "audio": None, "session": None}
    if audio is not None:
        audio._emit = service._emit  # audio levels go out through the same hub

    def remember(kind, payload):
        if kind in latest:
            latest[kind] = payload

    service.add_listener(remember)

    @app.on_event("startup")
    async def _startup():
        hub.attach(asyncio.get_running_loop())

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index():
        html = (STATIC / "index.html").read_text()
        for name in ("app.js", "app.css"):
            version = int((STATIC / name).stat().st_mtime)
            html = html.replace(f"/static/{name}", f"/static/{name}?v={version}")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/api/state")
    async def state():
        """Read-only snapshot (doesn't start live view, unlike opening the UI)."""
        snap = service.snapshot()
        return {"status": snap["status"], "props": {hex(c): p for c, p in snap["props"].items()}}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        client = Client(ws)
        hub.clients.add(client)
        service.viewers += 1
        snap = service.snapshot()
        await ws.send_text(
            json.dumps(
                {
                    "type": "hello",
                    "data": {
                        "catalog": catalog.catalog_json(),
                        "names": {str(k): v for k, v in PTP_PROP_NAMES.items()},
                        "props": snap["props"],
                        "status": snap["status"],
                        "face": latest["face"],
                        "audio": latest["audio"],
                        "session": latest["session"],
                        "assist": assist.cfg if assist else None,
                    },
                },
                default=str,
            )
        )

        async def sender():
            get_msg = wait_frame = None
            try:
                while True:
                    get_msg = get_msg or asyncio.create_task(client.outbox.get())
                    wait_frame = wait_frame or asyncio.create_task(client.frame_event.wait())
                    done, _ = await asyncio.wait({get_msg, wait_frame}, return_when=asyncio.FIRST_COMPLETED)
                    if wait_frame in done:
                        wait_frame = None
                    if get_msg in done:
                        text, get_msg = get_msg.result(), None
                        await ws.send_text(text)
                        # flush anything else queued before looking at frames
                        while not client.outbox.empty():
                            await ws.send_text(client.outbox.get_nowait())
                    if client.frame_event.is_set() and client.ready_for_frame:
                        client.frame_event.clear()
                        frame = service.latest_frame()
                        if frame and frame.seq != client.last_seq:
                            client.last_seq = frame.seq
                            client.ready_for_frame = False
                            header = dict(frame.header)
                            header.pop("raw", None)
                            header.update(seq=frame.seq, af_point=service.af_point)
                            hb = json.dumps(header).encode()
                            await ws.send_bytes(struct.pack(">I", len(hb)) + hb + frame.jpeg)
                    elif client.frame_event.is_set():
                        # The browser hasn't drawn the last frame yet; the ack re-arms this.
                        client.frame_event.clear()
            finally:
                for t in (get_msg, wait_frame):
                    if t:
                        t.cancel()

        async def handle(msg: dict):
            op = msg.get("op")
            req_id = msg.get("id")
            if op == "ack":
                client.ready_for_frame = True
                if service.latest_frame() and service.latest_frame().seq != client.last_seq:
                    client.frame_event.set()
                return
            if op in ASSIST_COMMANDS or op in ("audio_sources", "audio_select", "voice_check"):
                await client.outbox.put(json.dumps(await run_extra(op, msg.get("args", []), req_id), default=str))
                return
            if op not in ALLOWED_COMMANDS:
                await client.outbox.put(json.dumps({"type": "result", "id": req_id, "ok": False, "error": "Unknown command"}))
                return
            args = msg.get("args", [])
            try:
                result = await asyncio.wait_for(asyncio.wrap_future(service.submit(op, *args)), timeout=20)
                reply = {"type": "result", "id": req_id, "ok": True, "data": result}
                if assist and op in ("focus_at", "autofocus") and isinstance(result, dict) and result.get("focused"):
                    assist.mark_focus_soon()
            except (UserError, PTPError) as e:
                reply = {"type": "result", "id": req_id, "ok": False, "error": str(e)}
            except asyncio.TimeoutError:
                reply = {"type": "result", "id": req_id, "ok": False, "error": "The camera didn't respond in time"}
            except Exception as e:
                log.exception("command %s failed", op)
                reply = {"type": "result", "id": req_id, "ok": False, "error": f"Unexpected error: {e}"}
            await client.outbox.put(json.dumps(reply, default=str))

        async def run_extra(op, args, req_id):
            try:
                if op in ASSIST_COMMANDS:
                    if assist is None:
                        raise UserError("Assistants are not running")
                    data = await asyncio.to_thread(getattr(assist, ASSIST_COMMANDS[op]), *args)
                elif audio is None:
                    raise UserError("Audio monitor is not running")
                elif op == "audio_sources":
                    data = {"sources": await asyncio.to_thread(list_sources), "current": audio.source}
                elif op == "audio_select":
                    audio.select(args[0] if args else None)
                    data = {"current": audio.source}
                else:  # voice_check
                    seconds = float(args[0]) if args else 15.0
                    data = await asyncio.wait_for(asyncio.wrap_future(audio.voice_check(seconds)), timeout=seconds + 10)
                return {"type": "result", "id": req_id, "ok": True, "data": data}
            except (UserError, PTPError, RuntimeError) as e:
                return {"type": "result", "id": req_id, "ok": False, "error": str(e)}
            except asyncio.TimeoutError:
                return {"type": "result", "id": req_id, "ok": False, "error": "Timed out — is audio still coming in?"}
            except Exception as e:
                log.exception("command %s failed", op)
                return {"type": "result", "id": req_id, "ok": False, "error": f"Unexpected error: {e}"}

        send_task = asyncio.create_task(sender())
        try:
            while True:
                text = await ws.receive_text()
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                asyncio.create_task(handle(msg))
        except WebSocketDisconnect:
            pass
        finally:
            send_task.cancel()
            hub.clients.discard(client)
            service.viewers = max(0, service.viewers - 1)

    return app
