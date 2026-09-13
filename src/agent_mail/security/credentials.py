"""Windows Credential Manager backed by the Win32 Credential API."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

SERVICE_PREFIX = "AgentMail"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class CredentialStoreError(RuntimeError):
    """Raised when a credential cannot be read or written."""


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def credential_target(account_key: str) -> str:
    """Return a stable Credential Manager target for an account key."""

    normalized = account_key.strip().lower()
    if not normalized:
        raise ValueError("account_key must not be empty")
    return f"{SERVICE_PREFIX}/{normalized}"


def _advapi32() -> ctypes.WinDLL:
    if os.name != "nt":
        raise CredentialStoreError("Windows Credential Manager is only available on Windows.")
    return ctypes.WinDLL("Advapi32.dll", use_last_error=True)


def save_secret(account_key: str, username: str, secret: str) -> str:
    """Store a secret in Windows Credential Manager and return its target."""

    if not secret:
        raise ValueError("secret must not be empty")

    target = credential_target(account_key)
    api = _advapi32()
    api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL

    secret_bytes = secret.encode("utf-8")
    blob = ctypes.create_string_buffer(secret_bytes)
    credential = _CREDENTIALW()
    credential.Flags = 0
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.Comment = "Agent Mail 163 authorization code"
    credential.CredentialBlobSize = len(secret_bytes)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_byte))
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.AttributeCount = 0
    credential.Attributes = None
    credential.TargetAlias = None
    credential.UserName = username

    if not api.CredWriteW(ctypes.byref(credential), 0):
        error = ctypes.get_last_error()
        raise CredentialStoreError(f"CredWriteW failed with Windows error {error}.")
    return target


def load_secret(account_key: str) -> str | None:
    """Read a secret from Windows Credential Manager."""

    target = credential_target(account_key)
    api = _advapi32()
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None

    credential_ptr = ctypes.POINTER(_CREDENTIALW)()
    if not api.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(credential_ptr)):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return None
        raise CredentialStoreError(f"CredReadW failed with Windows error {error}.")

    try:
        credential = credential_ptr.contents
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return blob.decode("utf-8")
    finally:
        api.CredFree(credential_ptr)


def delete_secret(account_key: str) -> bool:
    """Delete a secret. Returns False when it did not exist."""

    target = credential_target(account_key)
    api = _advapi32()
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL

    if not api.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return False
        raise CredentialStoreError(f"CredDeleteW failed with Windows error {error}.")
    return True
