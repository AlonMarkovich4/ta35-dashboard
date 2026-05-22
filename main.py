"""
main.py — נקודת כניסה לפרודקשן (Render).

FastAPI רץ על $PORT ומטפל ב-/webhook/telegram ישירות.
Streamlit רץ כ-subprocess פנימי על 8501.
כל בקשה שאינה /webhook/* מועברת ל-Streamlit דרך reverse-proxy (HTTP + WebSocket).
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.websockets import WebSocket, WebSocketDisconnect

_ROOT = Path(__file__).parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from webhook_server import TelegramPayload, receive_telegram  # noqa: E402

_STREAMLIT_HOST = "127.0.0.1"
_STREAMLIT_PORT = 8501
_PORT = int(os.getenv("PORT", "8080"))

app = FastAPI(title="TA-35 Expiry Intelligence", docs_url=None, redoc_url=None)

# ── Webhook (handled directly — לא דרך proxy) ─────────────────────────
app.post("/webhook/telegram")(receive_telegram)

# ── State ─────────────────────────────────────────────────────────────
_sl_proc: subprocess.Popen | None = None
_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def _startup() -> None:
    """מפעיל Streamlit כ-subprocess ויוצר http client ל-proxy."""
    global _sl_proc, _client

    env = os.environ.copy()
    env["DISABLE_WEBHOOK_RUNNER"] = "1"  # מונע מ-app.py להפעיל webhook_runner מחדש

    _sl_proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run",
            str(_ROOT / "app.py"),
            f"--server.port={_STREAMLIT_PORT}",
            "--server.headless=true",
            f"--server.address={_STREAMLIT_HOST}",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # המתן שStreamlit יאתחל לפני שמתחילים לקבל בקשות
    for _ in range(20):
        await asyncio.sleep(1)
        try:
            async with httpx.AsyncClient() as probe:
                r = await probe.get(
                    f"http://{_STREAMLIT_HOST}:{_STREAMLIT_PORT}/healthz",
                    timeout=2,
                )
                if r.status_code < 500:
                    break
        except Exception:
            pass

    _client = httpx.AsyncClient(
        base_url=f"http://{_STREAMLIT_HOST}:{_STREAMLIT_PORT}",
        timeout=60.0,
        follow_redirects=True,
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    """מסיים את תהליך Streamlit וסוגר http client."""
    if _sl_proc and _sl_proc.poll() is None:
        _sl_proc.terminate()
    if _client:
        await _client.aclose()


# ── HTTP reverse-proxy ────────────────────────────────────────────────
@app.api_route(
    "/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
)
async def _http_proxy(request: Request, path: str) -> StreamingResponse:
    """מעביר בקשות HTTP ל-Streamlit על הפורט הפנימי."""
    assert _client is not None, "client not initialised"
    url = httpx.URL(
        path=f"/{path}",
        query=request.url.query.encode("utf-8"),
    )
    rp_req = _client.build_request(
        request.method,
        url,
        headers=[(k, v) for k, v in request.headers.items() if k.lower() != "host"],
        content=await request.body(),
    )
    rp_resp = await _client.send(rp_req, stream=True)
    return StreamingResponse(
        rp_resp.aiter_raw(),
        status_code=rp_resp.status_code,
        headers=dict(rp_resp.headers),
        background=BackgroundTask(rp_resp.aclose),
    )


# ── WebSocket reverse-proxy ───────────────────────────────────────────
@app.websocket("/{path:path}")
async def _ws_proxy(ws_client: WebSocket, path: str) -> None:
    """מעביר חיבורי WebSocket ל-Streamlit (נדרש לממשק האינטראקטיבי)."""
    import websockets  # noqa: PLC0415

    await ws_client.accept()

    qs = f"?{ws_client.url.query}" if ws_client.url.query else ""
    ws_url = f"ws://{_STREAMLIT_HOST}:{_STREAMLIT_PORT}/{path}{qs}"

    try:
        async with websockets.connect(ws_url) as ws_server:

            async def _to_server() -> None:
                try:
                    while True:
                        msg = await ws_client.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if "bytes" in msg and msg["bytes"] is not None:
                            await ws_server.send(msg["bytes"])
                        elif "text" in msg and msg["text"] is not None:
                            await ws_server.send(msg["text"])
                except (WebSocketDisconnect, Exception):
                    pass

            async def _to_client() -> None:
                try:
                    async for data in ws_server:
                        if isinstance(data, bytes):
                            await ws_client.send_bytes(data)
                        else:
                            await ws_client.send_text(data)
                except Exception:
                    pass

            tasks = [
                asyncio.create_task(_to_server()),
                asyncio.create_task(_to_client()),
            ]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    except Exception:
        pass
    finally:
        try:
            await ws_client.close()
        except Exception:
            pass


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_PORT, log_level="info")
