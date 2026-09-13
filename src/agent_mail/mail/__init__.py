"""Mailbox protocol clients."""

from .imap_client import FolderInfo, FetchedEmail, NeteaseImapClient
from .parser import ParsedEmail, parse_email

__all__ = [
    "FolderInfo",
    "FetchedEmail",
    "NeteaseImapClient",
    "ParsedEmail",
    "parse_email",
]
