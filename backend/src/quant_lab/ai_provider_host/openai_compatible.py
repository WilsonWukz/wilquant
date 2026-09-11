"""OpenAI-compatible HTTP, driven solely by approved capabilities."""

import ipaddress
import json
import socket
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from quant_lab.ai_provider_protocol import (
    CallPolicy,
    EndpointProfile,
    ProviderAvailability,
    ProviderCallRequest,
    ProviderCallResult,
    ProviderCapabilities,
    ProviderFailure,
    ProviderHealth,
    ProviderUsage,
)

from .secrets import SecretStore, redact_json


def approved_address(profile: EndpointProfile) -> tuple[str, str, int]:
    try:
        parts = urlsplit(profile.base_url)
        host = parts.hostname
        if (
            not host
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.scheme not in {"http", "https"}
        ):
            raise ValueError()
        local = profile.allow_local_http and parts.scheme == "http" and host == "127.0.0.1"
        if parts.scheme != "https" and not local:
            raise ValueError()
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = {
            str(item[4][0]) for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        }
        if not addresses or (
            not local and any(not ipaddress.ip_address(ip).is_global for ip in addresses)
        ):
            raise ValueError()
        return sorted(addresses)[0], host, port
    except (ValueError, OSError):
        raise ProviderFailure("ENDPOINT_NOT_ALLOWED") from None


class OpenAICompatibleProvider:
    def __init__(
        self, profile: EndpointProfile, secret_store: SecretStore, policy: CallPolicy | None = None
    ) -> None:
        approved_address(profile)
        self.profile = profile
        self.secret_store = secret_store
        self.policy = policy or CallPolicy()

    def capabilities(self) -> ProviderCapabilities:
        return self.profile.capabilities

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            profile_id=self.profile.profile_id, endpoint_fingerprint=self.profile.fingerprint
        )

    def availability(self) -> ProviderAvailability:
        # Profile validation happens at construction. Never resolve DNS or probe upstream here.
        accessible = True
        try:
            available = self.secret_store.exists(self.profile.credential_ref)
        except Exception:
            # Native store errors can contain private details; only flags cross IPC.
            accessible = False
            available = False
        return ProviderAvailability(
            profile_id=self.profile.profile_id,
            endpoint_fingerprint=self.profile.fingerprint,
            host_ready=True,
            profile_valid=True,
            credential_store_accessible=accessible,
            credential_available=available,
        )

    def complete(self, request: ProviderCallRequest) -> ProviderCallResult:
        started = time.monotonic()
        caps = self.profile.capabilities
        if (
            request.profile_id != self.profile.profile_id
            or request.model != self.profile.model
            or request.credential_ref != self.profile.credential_ref
            or request.endpoint_fingerprint != self.profile.fingerprint
        ):
            raise ProviderFailure("PROFILE_MISMATCH")
        if request.max_output_tokens > self.policy.max_output_tokens:
            raise ProviderFailure("OUTPUT_TOKEN_LIMIT")
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [message.model_dump() for message in request.messages],
            caps.output_token_parameter: request.max_output_tokens,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.response_format != "TEXT":
            if request.response_format != "JSON_OBJECT" or not caps.supports_json_object:
                raise ProviderFailure("UNSUPPORTED_CAPABILITY")
            body["response_format"] = {"type": "json_object"}
        if request.reasoning_enabled:
            if caps.reasoning_parameter == "unsupported":
                raise ProviderFailure("UNSUPPORTED_CAPABILITY")
            body[caps.reasoning_parameter] = (
                {"type": "enabled"}
                if caps.reasoning_parameter == "thinking"
                else request.reasoning_effort or "medium"
            )
        encoded = json.dumps(body).encode()
        if len(encoded) > self.policy.max_request_bytes:
            raise ProviderFailure("REQUEST_TOO_LARGE")
        secret = self.secret_store.get(self.profile.credential_ref)
        address, host, port = approved_address(self.profile)
        # Pin the validated IP for this connection; retain original Host and TLS SNI.
        url = httpx.URL(self.profile.base_url.rstrip("/") + "/chat/completions").copy_with(
            host=address
        )
        host_header = host if port in {80, 443} else f"{host}:{port}"
        timeout = httpx.Timeout(
            connect=self.policy.connect_timeout,
            read=self.policy.read_timeout,
            write=self.policy.write_timeout,
            pool=self.policy.pool_timeout,
        )
        try:
            with (
                httpx.Client(
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                    transport=httpx.HTTPTransport(retries=0),
                ) as client,
                client.stream(
                    "POST",
                    url,
                    content=encoded,
                    headers={
                        "Authorization": "Bearer " + secret,
                        "Content-Type": "application/json",
                        "Host": host_header,
                    },
                    extensions={"sni_hostname": host},
                ) as response,
            ):
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=8192):
                    data.extend(chunk)
                    if len(data) > self.policy.max_response_bytes:
                        raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
                if response.status_code != 200:
                    code = {
                        401: "PROVIDER_AUTH_FAILED",
                        403: "PROVIDER_AUTH_FAILED",
                        429: "PROVIDER_RATE_LIMITED",
                    }.get(
                        response.status_code,
                        "PROVIDER_UNAVAILABLE"
                        if response.status_code >= 500
                        else "PROVIDER_REJECTED",
                    )
                    if response.status_code == 400 and b"context_length" in data:
                        code = "PROVIDER_CONTEXT_LENGTH"
                    if b"insufficient_quota" in data:
                        code = "PROVIDER_QUOTA_EXCEEDED"
                    raise ProviderFailure(code)
            parsed = redact_json(json.loads(data.decode("utf-8")), [secret])
            choice = parsed["choices"][0]
            message = choice["message"]
            content = message["content"]
            if (
                not isinstance(content, str)
                or message.get("tool_calls")
                or message.get("function_call")
            ):
                raise ValueError()
            reasoning = message.get(caps.reasoning_content_field)
            if reasoning is not None and not isinstance(reasoning, str):
                raise ValueError()
            usage_data = parsed.get("usage") or {}

            def usage_value(path: str) -> int | None:
                value: Any = usage_data
                for part in path.split("."):
                    value = value.get(part) if isinstance(value, dict) else None
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError()
                return value if isinstance(value, int) else None

            result = ProviderCallResult(
                request_id=request.request_id,
                endpoint_fingerprint=self.profile.fingerprint,
                model_requested=request.model,
                model_reported=parsed.get("model"),
                content=content,
                reasoning_content=reasoning,
                usage=ProviderUsage(
                    prompt_tokens=usage_value(caps.input_usage_field),
                    completion_tokens=usage_value(caps.output_usage_field),
                    total_tokens=usage_value(caps.total_usage_field),
                    reasoning_tokens=usage_value(caps.reasoning_usage_field),
                    cached_prompt_tokens=usage_value(caps.cached_usage_field),
                ),
                finish_reason=choice.get("finish_reason"),
                provider_response_id=parsed.get("id"),
                latency_ms=(time.monotonic() - started) * 1000,
            )
            # Retain only explicitly approved response fields. Unknown provider metadata,
            # echoed prompts and all reasoning text are never included in the raw artifact.
            raw = json.dumps(
                {
                    "id": result.provider_response_id,
                    "model": result.model_reported,
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": result.content},
                            "finish_reason": result.finish_reason,
                        }
                    ],
                    "usage": result.usage.model_dump(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(raw.encode()) > self.policy.max_raw_artifact_bytes:
                raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
            if (
                result.reasoning_content is not None
                and len(result.reasoning_content.encode()) > self.policy.max_reasoning_bytes
            ):
                raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
            return result.model_copy(update={"raw_response": raw})
        except httpx.TimeoutException:
            raise ProviderFailure("PROVIDER_TIMEOUT", outcome_unknown=True) from None
        except httpx.HTTPError:
            raise ProviderFailure("PROVIDER_TRANSPORT_ERROR", outcome_unknown=True) from None
        except (ValueError, KeyError, IndexError, TypeError, UnicodeError):
            raise ProviderFailure("PROVIDER_INVALID_RESPONSE") from None
