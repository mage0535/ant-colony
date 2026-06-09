"""Plugin base class for third-party platform integrations.

To create a custom plugin:
1. Subclass PlatformPlugin
2. Implement required methods
3. Place the .py file in src/platform/plugins/
4. The system auto-discovers and registers it as an Agent tool

Example at src/platform/plugins/example_plugin.py
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class PlatformPlugin(ABC):
    """Base class for platform integration plugins.

    Implement any subset of methods. Unimplemented methods return None.
    Set `plugin_id` and `plugin_name` as class attributes.
    """

    plugin_id: str = ""
    plugin_name: str = ""

    def initialize(self, config: dict[str, Any]) -> bool:
        """Called once at startup. Return True on success."""
        return True

    def search_user(self, query: str) -> str | None:
        """Search for a user by name, email, or ID.

        Args:
            query: Search term (name, email, or user ID).

        Returns:
            Formatted result string, or None if not implemented.
        """
        return None

    def get_agenda(self, days: int = 7) -> str | None:
        """Fetch upcoming agenda or calendar events.

        Args:
            days: Number of days to look ahead.

        Returns:
            Formatted agenda string, or None if not implemented.
        """
        return None

    def search_docs(self, query: str) -> str | None:
        """Search documents, wiki, or knowledge base.

        Args:
            query: Search keyword or phrase.

        Returns:
            Formatted search results, or None if not implemented.
        """
        return None

    def list_approvals(self, status: str = "pending") -> str | None:
        """List approval requests (e.g. leave, reimbursement, seal).

        Args:
            status: Filter by status — 'pending', 'approved', 'rejected'.

        Returns:
            Formatted list of approvals, or None if not implemented.
        """
        return None

    def create_event(self, summary: str, start_at: str, end_at: str) -> str | None:
        """Create a calendar event.

        Args:
            summary: Event title.
            start_at: Start datetime string (ISO 8601 or 'YYYY-MM-DD HH:MM').
            end_at: End datetime string.

        Returns:
            Confirmation string with event ID/URL, or None if not implemented.
        """
        return None

    def get_admin_users(self) -> str | None:
        """Get list of platform administrators.

        Returns:
            Formatted admin list, or None if not implemented.
        """
        return None

    def query_app(self, app_id: str, action: str, params: dict[str, Any]) -> str | None:
        """Generic app query — for extending to workbench apps.

        Args:
            app_id: e.g. 'seal_approval', 'reimbursement', 'attendance'.
            action: e.g. 'list', 'get', 'submit'.
            params: Free-form dict passed to the plugin.

        Returns:
            App-specific result string, or None if not implemented.
        """
        return None
