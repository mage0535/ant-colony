from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApplicationDomain:
    domain: str
    capability_id: str
    required_permissions: tuple[str, ...]
    supports_user_filter: bool = False


_DOMAINS = {
    "meeting_room": ApplicationDomain("meeting_room", "meeting.room.query", ("meeting_room.read",), True),
    "meeting": ApplicationDomain("meeting", "meeting.list", ("meeting.read",), True),
    "approval": ApplicationDomain("approval", "approval.list", ("approval.read",), True),
    "calendar": ApplicationDomain("calendar", "calendar.list", ("calendar.read",), True),
    "docs": ApplicationDomain("docs", "docs.search", ("docs.read",), True),
    "drive": ApplicationDomain("drive", "drive.search", ("drive.read",), True),
    "mail": ApplicationDomain("mail", "mail.search", ("mail.read",), True),
    "contacts": ApplicationDomain("contacts", "contacts.search", ("contacts.read",), True),
    "third_party": ApplicationDomain("third_party", "apps.catalog", ("third_party.read",), True),
}


def get_application_domain(domain: str) -> ApplicationDomain | None:
    return _DOMAINS.get(str(domain or "").strip())


def capabilities_for_domains(domains: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_DOMAINS[domain].capability_id for domain in domains if domain in _DOMAINS)


def list_application_domains() -> tuple[ApplicationDomain, ...]:
    return tuple(_DOMAINS.values())
