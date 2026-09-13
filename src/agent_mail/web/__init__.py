"""Local web server for the Agent Mail UI and JSON API."""

from .server import AgentMailServer, create_server

__all__ = ["AgentMailServer", "create_server"]
