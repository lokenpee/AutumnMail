"""Secure credential storage for mailbox accounts."""

from .credentials import (
    CredentialStoreError,
    credential_target,
    delete_secret,
    load_secret,
    save_secret,
)

__all__ = [
    "CredentialStoreError",
    "credential_target",
    "delete_secret",
    "load_secret",
    "save_secret",
]
