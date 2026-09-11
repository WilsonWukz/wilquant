"""Authenticated local-only IPC service."""

import hmac
import json
import os
import threading
import time
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from quant_lab.ai_provider_protocol import (
    CallPolicy,
    EndpointProfile,
    ProviderCallRequest,
    ProviderFailure,
)

from .providers import Provider


class ReplayCache:
    def __init__(self, capacity: int, skew: int) -> None:
        self.capacity = capacity
        self.skew = skew
        self.entries: dict[str, float] = {}
        self.lock = threading.Lock()

    def claim(self, identity: str, timestamp: datetime) -> None:
        now = time.time()
        offset = timestamp.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ProviderFailure("REQUEST_TIMESTAMP_INVALID")
        stamp = timestamp.timestamp()
        if abs(now - stamp) > self.skew:
            raise ProviderFailure("REQUEST_TIMESTAMP_INVALID")
        with self.lock:
            self.entries = {key: expiry for key, expiry in self.entries.items() if expiry >= now}
            if identity in self.entries:
                raise ProviderFailure("DUPLICATE_PROVIDER_REQUEST")
            if len(self.entries) >= self.capacity:
                raise ProviderFailure("REPLAY_CACHE_FULL")
            self.entries[identity] = now + 2 * self.skew


def create_app(
    profile: EndpointProfile, provider: Provider, token: str, policy: CallPolicy | None = None
) -> FastAPI:
    policy = policy or CallPolicy()
    if len(token) < 32:
        raise ValueError("Host token must contain at least 256 bits")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    cache = ReplayCache(policy.replay_cache_size, policy.timestamp_skew_seconds)
    started_at = datetime.now(UTC).isoformat()

    @app.middleware("http")
    async def secure_boundary(request: Request, call_next: object) -> JSONResponse:
        try:
            authorization = request.headers.get("authorization", "")
            if not hmac.compare_digest(authorization, "Bearer " + token):
                return JSONResponse(
                    {"error": ProviderFailure("UNAUTHORIZED").as_error().model_dump()},
                    status_code=401,
                )
            if request.headers.get("x-ai-protocol-version") != "1":
                raise ProviderFailure("PROTOCOL_VERSION_MISMATCH")
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > policy.max_request_bytes:
                    raise ProviderFailure("REQUEST_TOO_LARGE")
            if request.url.path == "/internal/v1/complete" and request.method == "POST":
                raw = json.loads(body)
                if isinstance(raw, dict) and any(
                    key in raw
                    for key in (
                        "tools",
                        "functions",
                        "tool_choice",
                        "function_call",
                    )
                ):
                    raise ProviderFailure("PROVIDER_TOOLS_NOT_ALLOWED")
                dto = ProviderCallRequest.model_validate_json(bytes(body))
                cache.claim(dto.request_id, dto.timestamp_utc)
                if (
                    dto.profile_id != profile.profile_id
                    or dto.model != profile.model
                    or dto.credential_ref != profile.credential_ref
                    or dto.endpoint_fingerprint != profile.fingerprint
                ):
                    raise ProviderFailure("PROFILE_MISMATCH")
                if dto.max_output_tokens > policy.max_output_tokens:
                    raise ProviderFailure("OUTPUT_TOKEN_LIMIT")
                if len(dto.messages) > policy.max_messages or any(
                    len(message.content) > policy.max_chars_per_message for message in dto.messages
                ):
                    raise ProviderFailure("REQUEST_TOO_LARGE")
                if dto.response_format == "JSON_SCHEMA":
                    raise ProviderFailure("UNSUPPORTED_CAPABILITY")
                if (
                    dto.response_format == "JSON_OBJECT"
                    and not profile.capabilities.supports_json_object
                ):
                    raise ProviderFailure("UNSUPPORTED_CAPABILITY")
                if (
                    dto.reasoning_enabled
                    and profile.capabilities.reasoning_parameter == "unsupported"
                ):
                    raise ProviderFailure("UNSUPPORTED_CAPABILITY")
                result = await run_in_threadpool(provider.complete, dto)
                if (
                    result.reasoning_content is not None
                    and len(result.reasoning_content.encode()) > policy.max_reasoning_bytes
                ):
                    raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
                payload = result.model_dump(mode="json")
            elif request.method == "GET" and request.url.path in {
                "/internal/v1/health",
                "/internal/v1/capabilities",
                "/internal/v1/availability",
            }:
                identity = request.headers.get("x-request-id", "")
                if not identity or len(identity) > 128:
                    raise ProviderFailure("INVALID_REQUEST")
                timestamp = datetime.fromisoformat(request.headers.get("x-timestamp-utc", ""))
                cache.claim(identity, timestamp)
                if request.url.path.endswith("health"):
                    payload = {
                        "protocol_version": "1",
                        "status": "ready",
                        "process_id": os.getpid(),
                        "started_at": started_at,
                        "profile_id": profile.profile_id,
                        "endpoint_fingerprint": profile.fingerprint,
                        "provider_health": provider.health().model_dump(mode="json"),
                    }
                elif request.url.path.endswith("availability"):
                    availability = await run_in_threadpool(provider.availability)
                    payload = availability.model_dump(mode="json")
                else:
                    payload = provider.capabilities().model_dump(mode="json")
            else:
                return JSONResponse({"error": {"code": "NOT_FOUND"}}, status_code=404)
            encoded = json.dumps(payload).replace(token, "[REDACTED]")
            if len(encoded.encode()) > policy.max_response_bytes:
                raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
            return JSONResponse(json.loads(encoded))
        except ProviderFailure as exc:
            status = (
                409
                if exc.code in {"DUPLICATE_PROVIDER_REQUEST", "PROTOCOL_VERSION_MISMATCH"}
                else 400
            )
            return JSONResponse({"error": exc.as_error().model_dump()}, status_code=status)
        except (ValidationError, ValueError, TypeError):
            return JSONResponse(
                {"error": ProviderFailure("INVALID_REQUEST").as_error().model_dump()},
                status_code=400,
            )
        except Exception:
            return JSONResponse(
                {
                    "error": ProviderFailure("HOST_INTERNAL_ERROR", outcome_unknown=True)
                    .as_error()
                    .model_dump()
                },
                status_code=500,
            )

    return app
