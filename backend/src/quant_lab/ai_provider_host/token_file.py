"""Exclusive token creation with a protected current-user DACL from first write."""

import hmac
import os
import secrets
import subprocess
from pathlib import Path

from quant_lab.ai_provider_protocol import ProviderFailure

_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$path = $env:WILQUANT_AI_TOKEN_PATH
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$parent = [System.IO.Path]::GetDirectoryName($path)
if ($env:WILQUANT_AI_TOKEN_CREATE -eq '1') {
    if (![System.IO.Directory]::Exists($parent)) {
        $directorySecurity = New-Object System.Security.AccessControl.DirectorySecurity
        $directorySecurity.SetOwner($sid)
        $directorySecurity.SetAccessRuleProtection($true, $false)
        $directoryRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $directorySecurity.AddAccessRule($directoryRule)
        [void][System.IO.Directory]::CreateDirectory($parent, $directorySecurity)
    }
    $parentAcl = [System.IO.Directory]::GetAccessControl($parent)
    $parentRules = $parentAcl.GetAccessRules(
        $true, $true, [System.Security.Principal.SecurityIdentifier])
    if (!$parentAcl.AreAccessRulesProtected -or $parentRules.Count -ne 1 -or
        $parentRules[0].IdentityReference.Value -ne $sid.Value -or
        $parentRules[0].AccessControlType -ne 'Allow' -or $parentRules[0].IsInherited -or
        $parentRules[0].FileSystemRights -ne 'FullControl') { throw 'Unsafe parent ACL' }
    $security = New-Object System.Security.AccessControl.FileSecurity
    $security.SetOwner($sid)
    $security.SetAccessRuleProtection($true, $false)
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $sid, 'FullControl', 'Allow')
    $security.AddAccessRule($rule)
    $stream = New-Object System.IO.FileStream($path, [System.IO.FileMode]::CreateNew,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.IO.FileShare]::None, 4096, [System.IO.FileOptions]::None, $security)
    [Console]::Out.WriteLine('WILQUANT_TOKEN_CREATED')
    try {
        $bytes = [System.Text.Encoding]::ASCII.GetBytes([Console]::In.ReadToEnd())
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally { $stream.Dispose() }
}
$acl = [System.IO.File]::GetAccessControl($path)
if (!$acl.AreAccessRulesProtected) { throw 'Unsafe ACL' }
if ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) {
    throw 'Unsafe owner'
}
$rules = $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])
if ($rules.Count -ne 1 -or $rules[0].IdentityReference.Value -ne $sid.Value -or
    $rules[0].AccessControlType -ne 'Allow' -or $rules[0].IsInherited -or
    $rules[0].FileSystemRights -ne 'FullControl') { throw 'Unsafe ACL' }
"""


class HostTokenFile:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).absolute()
        self._owned_token: str | None = None
        self._created_in_call = False

    def _secure(self, create: bool, token: str = "") -> None:
        if os.name != "nt":
            raise ProviderFailure("TOKEN_ACL_UNAVAILABLE")
        environment = dict(
            os.environ,
            WILQUANT_AI_TOKEN_PATH=str(self.path),
            WILQUANT_AI_TOKEN_CREATE="1" if create else "0",
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _ACL_SCRIPT],
                input=token,
                text=True,
                capture_output=True,
                env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=20,
            )
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or b"").decode("ascii", errors="ignore")
            if create and "WILQUANT_TOKEN_CREATED" in output.splitlines():
                self._created_in_call = True
            raise ProviderFailure("TOKEN_ACL_INVALID") from None
        if create and "WILQUANT_TOKEN_CREATED" in result.stdout.splitlines():
            self._created_in_call = True
        if result.returncode:
            raise ProviderFailure("TOKEN_ACL_INVALID")

    def create(self) -> str:
        token = secrets.token_hex(32)
        self._created_in_call = False
        try:
            self._secure(True, token)
            self._owned_token = token
            if not hmac.compare_digest(self.read(), token):
                raise ProviderFailure("TOKEN_ACL_INVALID")
        except Exception:
            # Both an exclusive-create acknowledgement and the unpredictable token
            # identity are required; a pre-existing file can never enter this path.
            if self._created_in_call and not self.path.is_symlink():
                try:
                    if hmac.compare_digest(self.path.read_bytes(), token.encode("ascii")):
                        self.path.unlink()
                except OSError:
                    pass
            self._owned_token = None
            raise
        return token

    def read(self) -> str:
        self._secure(False)
        value = self.path.read_text(encoding="ascii")
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ProviderFailure("TOKEN_INVALID")
        return value

    def close(self) -> None:
        if (
            self._owned_token is not None
            and self.path.exists()
            and hmac.compare_digest(self.read(), self._owned_token)
        ):
            self.path.unlink()
        self._owned_token = None
