"""Core-side authenticated local IPC; never connects to a provider endpoint."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import ValidationError

from quant_lab.ai_provider_protocol import (
    CallPolicy,
    ProviderAvailability,
    ProviderCallError,
    ProviderCallRequest,
    ProviderCallResult,
    ProviderFailure,
)


class AIProviderHostClient:
    def __init__(self, base_url: str, token_path: Path, policy: CallPolicy | None = None) -> None:
        url = urlsplit(base_url)
        if (
            url.scheme != "http"
            or url.hostname != "127.0.0.1"
            or url.port is None
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("AI_PROVIDER_HOST_URL_INVALID")
        self.base_url = f"http://127.0.0.1:{url.port}"
        self.token_path = token_path
        self.policy = policy or CallPolicy()

    def _token(self) -> str:
        try:
            with self.token_path.open("rb") as stream:
                token = stream.read(129).decode("ascii").strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
                raise ValueError("invalid token")
            return token
        except (OSError, ValueError, UnicodeError):
            raise ProviderFailure("PROVIDER_HOST_UNAVAILABLE") from None

    def _exchange(
        self, method: str, path: str, request: ProviderCallRequest | None = None
    ) -> object:
        token = self._token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-AI-Protocol-Version": "1",
            "X-Request-ID": str(uuid4()),
            "X-Timestamp-UTC": datetime.now(UTC).isoformat(),
        }
        body = request.model_dump_json().encode() if request is not None else None
        if body is not None and len(body) > self.policy.max_request_bytes:
            raise ProviderFailure("PROVIDER_REQUEST_TOO_LARGE")
        if body is not None:
            headers["Content-Type"] = "application/json"
        timeout = httpx.Timeout(
            connect=self.policy.connect_timeout,
            read=self.policy.read_timeout + 5,
            write=self.policy.write_timeout,
            pool=self.policy.pool_timeout,
        )
        try:
            with (
                httpx.Client(
                    timeout=timeout,
                    trust_env=False,
                    follow_redirects=False,
                    transport=httpx.HTTPTransport(retries=0),
                ) as client,
                client.stream(
                    method, self.base_url + path, headers=headers, content=body
                ) as response,
            ):
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > self.policy.max_response_bytes:
                        raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE", outcome_unknown=True)
                payload = json.loads(data)
                if response.status_code != 200:
                    error = ProviderCallError.model_validate(payload.get("error", {}))
                    code = (
                        error.code
                        if re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", error.code)
                        else "PROVIDER_INTERNAL_ERROR"
                    )
                    # The remote message is untrusted; only a bounded stable code crosses Core.
                    raise ProviderFailure(code, outcome_unknown=error.outcome_unknown)
                return payload
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise ProviderFailure("PROVIDER_HOST_UNAVAILABLE") from None
        except httpx.TransportError:
            raise ProviderFailure(
                "PROVIDER_RESULT_UNKNOWN", outcome_unknown=request is not None
            ) from None
        except (ValueError, AttributeError):
            raise ProviderFailure(
                "PROVIDER_INVALID_RESPONSE", outcome_unknown=request is not None
            ) from None

    def complete(
        self, request: ProviderCallRequest, policy: CallPolicy | None = None
    ) -> ProviderCallResult:
        if policy is not None and policy != self.policy:
            return AIProviderHostClient(self.base_url, self.token_path, policy).complete(request)
        payload = self._exchange("POST", "/internal/v1/complete", request)
        try:
            return ProviderCallResult.model_validate(payload)
        except ValidationError:
            raise ProviderFailure("PROVIDER_INVALID_RESPONSE", outcome_unknown=True) from None

    def health(self) -> object:
        return self._exchange("GET", "/internal/v1/health")

    def availability(self) -> ProviderAvailability:
        payload = self._exchange("GET", "/internal/v1/availability")
        try:
            return ProviderAvailability.model_validate(payload)
        except ValidationError:
            raise ProviderFailure("PROVIDER_INVALID_RESPONSE") from None
