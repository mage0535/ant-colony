"""Tier-2 bridges for apps without official APIs.

Bridge types:
  scrapling — web scraping via Scrapling
  mcp       — MCP protocol integration
  webhook   — custom webhook receiver
  email     — email-based interaction
"""

from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger("platform.bridges")


def query_via_scrapling(
    url: str,
    selector: str = "",
    query: str = "",
    timeout: int = 30,
) -> str | None:
    """Scrape a web app by URL and optional CSS selector.

    Args:
        url: Target page URL.
        selector: CSS selector to extract a specific element.
        query: Free-text to find within page content (case-insensitive).
        timeout: Request timeout in seconds.

    Returns:
        Extracted text content, or None on failure.
    """
    logger.warning("Scrapling bridge is not yet wired. Called with url=%s", url)
    return None


def start_webhook_listener(port: int = 18770) -> str:
    """Start a webhook listener on the given port for custom app callbacks.

    Args:
        port: TCP port to listen on.

    Returns:
        Listener status string (address + port), or placeholder if not active.
    """
    logger.info("Webhook listener requested on port %d (not yet wired)", port)
    return f"webhook://0.0.0.0:{port} (not active — bridge unwired)"


def query_via_mcp(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> str | None:
    """Call a tool on an MCP server via the Model Context Protocol.

    Args:
        server_name: Registered MCP server identifier.
        tool_name: Tool name to invoke on the server.
        arguments: Tool arguments dict (optional).

    Returns:
        Tool result as a string, or None on failure.
    """
    logger.debug("MCP bridge called: server=%s tool=%s", server_name, tool_name)
    return None


def query_via_email(
    smtp_host: str,
    smtp_port: int,
    sender: str,
    recipient: str,
    subject: str,
    body: str = "",
    *,
    use_tls: bool = True,
    username: str = "",
    password: str = "",
) -> str | None:
    """Send a query via email and await reply.

    Args:
        smtp_host: SMTP server hostname.
        smtp_port: SMTP server port.
        sender: From address.
        recipient: To address.
        subject: Email subject line.
        body: Email body text.
        use_tls: Whether to use STARTTLS.
        username: SMTP auth username.
        password: SMTP auth password.

    Returns:
        Placeholder for now — email bridge is not yet implemented.
    """
    logger.info("Email bridge called: %s → %s subject=%r", sender, recipient, subject)
    return None
