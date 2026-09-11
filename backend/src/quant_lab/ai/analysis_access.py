"""本地研究 API 的独立授权边界。CORS 不承担鉴权。"""

from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class AnalysisAccessBoundary:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/v1/ai/analyses"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        state = scope["app"].state
        token = getattr(state, "ai_analysis_access_token", None)
        code, status = None, 403
        if not token:
            code, status = "AI_ANALYSIS_UNAVAILABLE", 503
        elif not hmac.compare_digest(
            headers.get("authorization", "").encode(), ("Bearer " + token).encode()
        ):
            code, status = "AI_ANALYSIS_UNAUTHORIZED", 401
        else:
            try:
                host = urlsplit("http://" + headers.get("host", "")).hostname
            except ValueError:
                host = None
            peer = scope.get("client")
            origin = headers.get("origin")
            if (
                host not in {"127.0.0.1", "localhost", "::1"}
                or peer is None
                or peer[0] not in {"127.0.0.1", "::1"}
                or (
                    origin is not None
                    and origin not in getattr(state, "ai_analysis_origins", set())
                )
            ):
                code = "AI_ANALYSIS_SOURCE_FORBIDDEN"
            elif (
                scope["method"] == "POST"
                and headers.get("content-type", "").split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                code, status = "AI_ANALYSIS_JSON_REQUIRED", 415
        if code:
            await JSONResponse(
                {"error_code": code, "message": "研究分析请求未获授权或不可用"}, status_code=status
            )(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 65536:
                await JSONResponse(
                    {
                        "error_code": "AI_ANALYSIS_REQUEST_TOO_LARGE",
                        "message": "研究请求超过大小限制",
                    },
                    status_code=413,
                )(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
