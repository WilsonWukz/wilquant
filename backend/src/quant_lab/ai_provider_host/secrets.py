"""AI credential boundary. Production storage never falls back to plaintext."""

import ctypes
import json
import os
import re
from ctypes import wintypes
from typing import Any, Protocol

from quant_lab.ai_provider_protocol import ProviderFailure


def validate_ref(reference: str) -> None:
    if not re.fullmatch(r"wilquant\.ai\.[A-Za-z0-9_.-]{1,240}", reference):
        raise ProviderFailure("INVALID_CREDENTIAL_REF")


class SecretStore(Protocol):
    def get(self, reference: str) -> str: ...
    def set(self, reference: str, secret: str) -> None: ...
    def delete(self, reference: str) -> None: ...
    def exists(self, reference: str) -> bool: ...


class MemorySecretStore:
    """Test-only store. No environment or filesystem persistence."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, reference: str) -> str:
        validate_ref(reference)
        if reference not in self._values:
            raise ProviderFailure("CREDENTIAL_NOT_FOUND")
        return self._values[reference]

    def set(self, reference: str, secret: str) -> None:
        validate_ref(reference)
        self._values[reference] = secret

    def delete(self, reference: str) -> None:
        validate_ref(reference)
        self._values.pop(reference, None)

    def exists(self, reference: str) -> bool:
        validate_ref(reference)
        return reference in self._values


def redact(value: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return re.sub(r'(?i)bearer\s+[^\s"\\]+', "Bearer [REDACTED]", value)


def redact_json(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (ValueError, RecursionError):
                pass
            else:
                if isinstance(parsed, (dict, list)):
                    return redact(
                        json.dumps(redact_json(parsed, secrets), ensure_ascii=False), secrets
                    )
        return redact(value, secrets)
    if isinstance(value, list):
        return [redact_json(item, secrets) for item in value]
    if isinstance(value, dict):
        sensitive = {
            "apikey",
            "accesstoken",
            "clientsecret",
            "authorization",
            "credential",
            "credentials",
            "cookie",
            "setcookie",
            "password",
            "secret",
        }
        return {
            redact(str(key), secrets): (
                "[REDACTED]"
                if re.sub(r"[^a-z]", "", str(key).lower()) in sensitive
                else redact_json(item, secrets)
            )
            for key, item in value.items()
        }
    return value


class CredentialNative(Protocol):
    def read(self, target: str) -> str | None: ...
    def write(self, target: str, value: str) -> None: ...
    def delete(self, target: str) -> None: ...


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialNative:
    def __init__(self) -> None:
        if os.name != "nt":
            raise ProviderFailure("SECRET_STORE_UNAVAILABLE")
        self.api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self.api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredDeleteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredFree.restype = None

    def read(self, target: str) -> str | None:
        pointer = ctypes.POINTER(_Credential)()
        if not self.api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise ProviderFailure("SECRET_STORE_UNAVAILABLE")
        try:
            return ctypes.string_at(
                pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize
            ).decode("utf-16-le")
        finally:
            self.api.CredFree(pointer)

    def write(self, target: str, value: str) -> None:
        blob = value.encode("utf-16-le")
        if not blob or len(blob) > 2560:
            raise ProviderFailure("INVALID_CREDENTIAL")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _Credential(
            Type=1,
            TargetName=target,
            CredentialBlobSize=len(blob),
            CredentialBlob=buffer,
            Persist=2,
            UserName="wilquant.ai",
        )
        try:
            if not self.api.CredWriteW(ctypes.byref(credential), 0):
                raise ProviderFailure("SECRET_STORE_UNAVAILABLE")
        finally:
            ctypes.memset(buffer, 0, len(blob))

    def delete(self, target: str) -> None:
        if not self.api.CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
            raise ProviderFailure("SECRET_STORE_UNAVAILABLE")


class WindowsCredentialManagerSecretStore:
    def __init__(self, native: CredentialNative | None = None) -> None:
        self.native = native or WindowsCredentialNative()

    def get(self, reference: str) -> str:
        validate_ref(reference)
        value = self.native.read(reference)
        if value is None:
            raise ProviderFailure("CREDENTIAL_NOT_FOUND")
        return value

    def set(self, reference: str, secret: str) -> None:
        validate_ref(reference)
        if not secret:
            raise ProviderFailure("INVALID_CREDENTIAL")
        self.native.write(reference, secret)

    def delete(self, reference: str) -> None:
        validate_ref(reference)
        self.native.delete(reference)

    def exists(self, reference: str) -> bool:
        validate_ref(reference)
        return self.native.read(reference) is not None
