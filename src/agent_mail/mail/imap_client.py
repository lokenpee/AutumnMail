"""Minimal 163-compatible IMAP client."""

from __future__ import annotations

import imaplib
import re
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

if "ID" not in imaplib.Commands:
    imaplib.Commands["ID"] = ("AUTH",)


_NETEASE_IMAP_FALLBACK_IPS = (
    "117.135.214.13",
    "117.135.214.18",
    "220.197.33.205",
    "220.197.33.210",
)


def _resolve_host_addresses(host: str, port: int) -> list[str]:
    last_error: OSError | None = None
    for attempt in range(3):
        try:
            addresses = sorted({
                item[4][0]
                for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                if item[4] and item[4][0]
            })
            if addresses:
                return addresses
        except socket.gaierror as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(0.25 * (attempt + 1))
    if host.strip().lower() == "imap.163.com":
        return list(_NETEASE_IMAP_FALLBACK_IPS)
    if last_error is not None:
        raise last_error
    raise socket.gaierror(f"无法解析 {host}")


class _ResolvedAddressIMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(self, *args, resolved_addresses: list[str] | None = None, **kwargs) -> None:
        self._resolved_addresses = list(resolved_addresses or [])
        super().__init__(*args, **kwargs)

    def _create_socket(self, timeout):
        if not self._resolved_addresses:
            return super()._create_socket(timeout)
        last_error: OSError | None = None
        for address in self._resolved_addresses:
            try:
                sock = socket.create_connection((address, self.port), timeout)
                return self.ssl_context.wrap_socket(sock, server_hostname=self.host)
            except OSError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return super()._create_socket(timeout)


def _imap_date(value: date) -> str:
    month_names = (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    )
    return f"{value.day:02d}-{month_names[value.month - 1]}-{value.year}"


@dataclass(slots=True)
class FolderInfo:
    name: str
    delimiter: str | None
    flags: tuple[str, ...] = ()


@dataclass(slots=True)
class FetchedEmail:
    uid: str
    flags: tuple[str, ...]
    internal_date: str | None
    raw_bytes: bytes


class NeteaseImapClient:
    """Small IMAP wrapper that handles the 163 client ID requirement."""

    def __init__(
        self,
        email: str,
        auth_code: str,
        host: str = "imap.163.com",
        port: int = 993,
        timeout: int = 30,
    ) -> None:
        self.email = email
        self.auth_code = auth_code
        self.host = host
        self.port = port
        self.timeout = timeout
        self._connection: imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        context = ssl.create_default_context()
        resolved_addresses = _resolve_host_addresses(self.host, self.port)
        connection = _ResolvedAddressIMAP4SSL(
            self.host,
            self.port,
            ssl_context=context,
            timeout=self.timeout,
            resolved_addresses=resolved_addresses,
        )
        try:
            connection.login(self.email, self.auth_code)
            self._send_client_id(connection)
        except Exception:
            try:
                connection.logout()
            except Exception:
                pass
            raise
        self._connection = connection

    def disconnect(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.logout()
        finally:
            self._connection = None

    @property
    def connection(self) -> imaplib.IMAP4_SSL:
        if self._connection is None:
            raise RuntimeError("IMAP connection is not open.")
        return self._connection

    @staticmethod
    def _send_client_id(connection: imaplib.IMAP4_SSL) -> None:
        """Send the mandatory 163 IMAP ID command before SELECT/EXAMINE."""

        client_id = (
            "name",
            "AgentMail",
            "version",
            "0.1.0",
            "vendor",
            "local-agent-mail",
            "support-email",
            "local@localhost",
        )
        status, _ = connection._simple_command(
            "ID",
            '("' + '" "'.join(client_id) + '")',
        )
        if status != "OK":
            raise RuntimeError("163 IMAP ID command failed")

    def list_folders(self) -> list[FolderInfo]:
        status, data = self.connection.list()
        if status != "OK":
            return []

        folders: list[FolderInfo] = []
        for item in data or []:
            if not item:
                continue
            line = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
            match = re.match(r'\((?P<flags>[^)]*)\)\s+"(?P<delimiter>[^"]*)"\s+(?P<name>.+)', line)
            if not match:
                continue
            name = match.group("name").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
            flags = tuple(match.group("flags").split())
            folders.append(
                FolderInfo(
                    name=name,
                    delimiter=match.group("delimiter") or None,
                    flags=flags,
                )
            )
        return folders

    def select_folder(self, folder: str, readonly: bool = True) -> int:
        status, data = self.connection.select(self._quote(folder), readonly=readonly)
        if status != "OK":
            raise RuntimeError(f"Unable to select folder: {folder}")
        if data and data[0]:
            try:
                return int(data[0])
            except (TypeError, ValueError):
                return 0
        return 0

    def get_uidvalidity(self, folder: str = "INBOX") -> str | None:
        status, data = self.connection.status(self._quote(folder), "(UIDVALIDITY UIDNEXT)")
        if status != "OK" or not data or not data[0]:
            return None
        match = re.search(r"UIDVALIDITY\s+(\d+)", data[0].decode("utf-8", errors="replace"))
        return match.group(1) if match else None

    def search_uids(self, criteria: str = "ALL") -> list[str]:
        status, data = self.connection.uid("SEARCH", None, criteria)
        if status != "OK" or not data or not data[0]:
            return []
        return [item.decode("ascii") if isinstance(item, bytes) else str(item) for item in data[0].split()]

    def search_range(self, start_date: date | None = None, end_date: date | None = None) -> list[str]:
        criteria: list[str] = []
        if start_date:
            criteria.extend(("SINCE", _imap_date(start_date)))
        if end_date:
            criteria.extend(("BEFORE", _imap_date(end_date + timedelta(days=1))))
        if not criteria:
            criteria.append("ALL")
        status, data = self.connection.uid("SEARCH", None, *criteria)
        if status != "OK" or not data or not data[0]:
            return []
        return [item.decode("ascii") if isinstance(item, bytes) else str(item) for item in data[0].split()]

    def search_since(self, days: int = 30) -> list[str]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        return self.search_range(start_date=since.date())

    def fetch_emails(self, uids: list[str], batch_size: int = 30) -> list[FetchedEmail]:
        messages: list[FetchedEmail] = []
        for start in range(0, len(uids), batch_size):
            batch = uids[start : start + batch_size]
            status, data = self.connection.uid(
                "FETCH",
                ",".join(batch),
                "(UID FLAGS INTERNALDATE BODY.PEEK[])",
            )
            if status != "OK":
                continue
            for item in data or []:
                if not isinstance(item, tuple) or len(item) < 2:
                    continue
                header = item[0].decode("utf-8", errors="replace") if isinstance(item[0], bytes) else str(item[0])
                raw_bytes = item[1]
                if not isinstance(raw_bytes, bytes):
                    continue
                uid_match = re.search(r"UID\s+(\d+)", header)
                if not uid_match:
                    continue
                flags_match = re.search(r"FLAGS\s+\(([^)]*)\)", header)
                internal_match = re.search(r'INTERNALDATE\s+"([^"]+)"', header)
                messages.append(
                    FetchedEmail(
                        uid=uid_match.group(1),
                        flags=tuple(flags_match.group(1).split()) if flags_match else (),
                        internal_date=internal_match.group(1) if internal_match else None,
                        raw_bytes=raw_bytes,
                    )
                )
        return messages

    @staticmethod
    def _quote(value: str) -> str:
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
