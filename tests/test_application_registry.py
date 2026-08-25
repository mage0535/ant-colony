from __future__ import annotations


def test_registry_keeps_meeting_room_and_approval_capabilities_separate() -> None:
    from src.platform.application_registry import capabilities_for_domains

    assert capabilities_for_domains(("meeting_room",)) == ("meeting.room.query",)
    assert capabilities_for_domains(("approval",)) == ("approval.list",)


def test_registry_describes_user_filtering_and_permissions() -> None:
    from src.platform.application_registry import get_application_domain

    approval = get_application_domain("approval")

    assert approval is not None
    assert approval.supports_user_filter is True
    assert "approval.read" in approval.required_permissions


def test_registry_returns_multiple_capabilities_only_for_explicit_domains() -> None:
    from src.platform.application_registry import capabilities_for_domains

    assert capabilities_for_domains(("meeting", "approval", "calendar")) == (
        "meeting.list",
        "approval.list",
        "calendar.list",
    )


def test_third_party_domain_uses_accessible_application_catalog() -> None:
    from src.platform.application_registry import capabilities_for_domains

    assert capabilities_for_domains(("third_party",)) == ("apps.catalog",)
