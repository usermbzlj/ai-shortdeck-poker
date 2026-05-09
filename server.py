"""
WebSocket 广播服务器 — 将 AI 对战引擎的实时事件推送到前端牌桌。

用法：由 main.py 在后台线程启动，controller 通过 broadcast_sync() 发送事件。
"""

import asyncio
import json
import logging
import os
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

log = logging.getLogger("poker.ws")

# 前端构建产物目录（相对本文件）
_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "live-visible", "ai-shortdeck-poker", "dist")


class WebSocketManager:
    """管理 WebSocket 连接，提供线程安全的广播接口。"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8002):
        self.host = host
        self.port = port
        self.connections: List[WebSocket] = []
        self.loop: asyncio.AbstractEventLoop | None = None
        self._app = FastAPI()
        self._setup_middleware()
        self._setup_routes()

    def _setup_middleware(self) -> None:
        # 允许所有跨域请求（包括 file:// 和不同端口）
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self) -> None:
        @self._app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            # 显式接受所有 Origin（包括 null，即 file:// 协议）
            await websocket.accept()
            self.connections.append(websocket)
            log.info("WebSocket client connected | origin=%s | total=%d", websocket.headers.get("origin", "null"), len(self.connections))
            try:
                while True:
                    data = await websocket.receive_text()
                    try:
                        await websocket.send_text(json.dumps({"type": "pong", "payload": {}}))
                    except Exception:
                        break
            except WebSocketDisconnect:
                pass
            except Exception as e:
                log.debug("WebSocket client error: %s", e)
            finally:
                if websocket in self.connections:
                    self.connections.remove(websocket)
                log.info("WebSocket client disconnected | total=%d", len(self.connections))

        @self._app.get("/api/health")
        def health():
            return {"status": "ok", "connections": len(self.connections)}

        # 如果前端构建产物存在，直接托管静态文件
        if os.path.isdir(_FRONTEND_DIST):
            self._app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="static")
            log.info("静态文件托管: %s", os.path.abspath(_FRONTEND_DIST))
        else:
            @self._app.get("/")
            def root():
                return {"status": "poker live ws", "connections": len(self.connections), "note": "frontend dist not found"}

    async def broadcast(self, event_type: str, payload: dict) -> None:
        if not self.connections:
            return
        msg = json.dumps({"type": event_type, "payload": payload}, ensure_ascii=False, default=str)
        dead: List[WebSocket] = []
        for ws in self.connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.connections:
                self.connections.remove(ws)

    def broadcast_sync(self, event_type: str, payload: dict) -> None:
        """供同步代码（如 Qt 主线程）线程安全地调用。"""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(event_type, payload), self.loop)
        else:
            log.debug("WebSocket loop not running, dropping event %s", event_type)

    def run(self) -> None:
        """阻塞运行 uvicorn（应在独立线程中调用）。"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            loop="asyncio",
            log_level="warning",
        )
        server = uvicorn.Server(config)
        self.loop.run_until_complete(server.serve())
