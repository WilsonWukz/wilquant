"""Persistent Core credential and crash-released local process ownership.

This is independent of the Provider Host's ephemeral token lifecycle. It trusts
the current Windows user, not arbitrary remote clients or other local accounts;
it does not defend against malware already running as that user.
"""

import os
import stat
import subprocess
from pathlib import Path

from quant_lab.ai_provider_host.token_file import HostTokenFile
from quant_lab.ai_provider_protocol import ProviderFailure

_PARENT_ACL = r"""
$ErrorActionPreference = 'Stop'
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = [System.IO.Directory]::GetAccessControl($env:WILQUANT_CORE_ACCESS_DIRECTORY)
$rules = $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])
if (!$acl.AreAccessRulesProtected -or
    $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $sid.Value -or
    $rules.Count -ne 1 -or $rules[0].IdentityReference.Value -ne $sid.Value -or
    $rules[0].AccessControlType -ne 'Allow' -or $rules[0].IsInherited -or
    $rules[0].FileSystemRights -ne 'FullControl') { throw 'Unsafe Core directory' }
"""


class CoreLocalAccess:
    def __init__(self, path: Path, *, lock_path: Path | None = None) -> None:
        self.path = path.absolute()
        self.lock_path = (lock_path or self.path.with_name("core.lock")).absolute()
        self._lock_fd: int | None = None

    def acquire(self) -> str:
        if os.name != "nt":
            raise ProviderFailure("TOKEN_ACL_UNAVAILABLE")
        import msvcrt

        # Reject junctions/symlinks before even validating or creating a token.
        for path in (self.path, self.lock_path):
            for candidate in (path, *path.parents):
                try:
                    info = candidate.lstat()
                except FileNotFoundError:
                    continue
                if (
                    stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)
                ):
                    raise ProviderFailure("TOKEN_ACL_INVALID")
        token_file = HostTokenFile(self.path)
        token = token_file.read() if self.path.exists() else token_file.create()
        if self.path.stat().st_nlink != 1:
            raise ProviderFailure("TOKEN_ACL_INVALID")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PARENT_ACL],
                env=dict(os.environ, WILQUANT_CORE_ACCESS_DIRECTORY=str(self.path.parent)),
                capture_output=True,
                timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            raise ProviderFailure("TOKEN_ACL_INVALID") from None
        if result.returncode:
            raise ProviderFailure("TOKEN_ACL_INVALID")
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.fstat(fd).st_nlink != 1:
                raise ProviderFailure("TOKEN_ACL_INVALID")
            # Windows allows locking beyond EOF. Never write secrets or truncate
            # this inode: all Core instances must contend on the same lock byte.
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except BaseException:
            os.close(fd)
            raise
        self._lock_fd = fd
        return token

    def close(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)  # OS also releases this lock on process death.
            self._lock_fd = None
        # The verified Core credential deliberately persists across restarts.
