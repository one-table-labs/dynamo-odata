import pytest

from dynamo_odata import (
    DEFAULT_FORBIDDEN_RESPONSE_FIELDS,
    NoOpAuditHook,
    apply_response_allowlist,
    apply_response_field_policy,
    build_regulated_profile,
    validate_page_size,
    validate_regulated_query,
)
from dynamo_odata.guardrails import FilterPolicyViolationError, PartitionKeyValidationError


class _CaptureAuditHook:
    def __init__(self) -> None:
        self.allowed_calls: list[dict] = []
        self.blocked_calls: list[dict] = []

    def on_query_allowed(
        self,
        *,
        partition_key: str,
        filter_text: str | None,
        normalized_limit: int,
    ) -> None:
        self.allowed_calls.append(
            {
                "partition_key": partition_key,
                "filter_text": filter_text,
                "normalized_limit": normalized_limit,
            }
        )

    def on_query_blocked(
        self,
        *,
        reason: str,
        partition_key: str,
        filter_text: str | None,
        requested_limit: int | None,
    ) -> None:
        self.blocked_calls.append(
            {
                "reason": reason,
                "partition_key": partition_key,
                "filter_text": filter_text,
                "requested_limit": requested_limit,
            }
        )


def test_build_regulated_profile_defaults():
    profile = build_regulated_profile()

    assert profile.max_page_size == 100
    assert profile.partition_guard.allowed_prefixes == ("TENANT#",)
    assert profile.forbidden_response_fields == DEFAULT_FORBIDDEN_RESPONSE_FIELDS
    assert isinstance(profile.audit_hook, NoOpAuditHook)


def test_build_regulated_profile_with_overrides():
    profile = build_regulated_profile(
        partition_prefixes=("ORG#",),
        max_page_size=25,
        forbidden_response_fields=frozenset({"PK", "SK"}),
        allowed_filter_fields=frozenset({"status"}),
    )

    assert profile.partition_guard.allowed_prefixes == ("ORG#",)
    assert profile.max_page_size == 25
    assert profile.forbidden_response_fields == frozenset({"PK", "SK"})
    assert profile.filter_policy.allowed_fields == frozenset({"status"})


def test_build_regulated_profile_rejects_invalid_max_page_size():
    with pytest.raises(ValueError, match="max_page_size"):
        build_regulated_profile(max_page_size=0)


def test_apply_response_field_policy_strips_internal_fields():
    items = [
        {"PK": "TENANT#1", "SK": "1#USER#1", "name": "Ada", "ttl": 123},
        {"PK": "TENANT#1", "SK": "1#USER#2", "name": "Grace", "active": True},
    ]

    result = apply_response_field_policy(items, frozenset({"PK", "SK", "ttl"}))

    assert result == [{"name": "Ada"}, {"name": "Grace", "active": True}]


def test_apply_response_allowlist_keeps_only_allowed_fields():
    items = [
        {"PK": "TENANT#1", "SK": "1#USER#1", "name": "Ada", "status": "active"},
        {"PK": "TENANT#1", "SK": "1#USER#2", "name": "Grace", "status": "inactive"},
    ]

    result = apply_response_allowlist(items, frozenset({"name", "status"}))

    assert result == [
        {"name": "Ada", "status": "active"},
        {"name": "Grace", "status": "inactive"},
    ]


def test_validate_page_size_defaults_and_bounds():
    assert validate_page_size(limit=None, max_page_size=50, default_page_size=20) == 20
    assert validate_page_size(limit=None, max_page_size=50) == 50
    assert validate_page_size(limit=10, max_page_size=50) == 10

    with pytest.raises(ValueError, match="limit must be >= 1"):
        validate_page_size(limit=0, max_page_size=50)

    with pytest.raises(ValueError, match="exceeds max_page_size"):
        validate_page_size(limit=51, max_page_size=50)


def test_validate_regulated_query_allowed_calls_audit_hook():
    hook = _CaptureAuditHook()
    profile = build_regulated_profile(
        allowed_filter_fields=frozenset({"status"}),
        max_page_size=25,
        audit_hook=hook,
    )

    normalized_limit = validate_regulated_query(
        profile,
        partition_key="TENANT#a",
        filter_text="status eq 'active'",
        limit=10,
    )

    assert normalized_limit == 10
    assert len(hook.allowed_calls) == 1
    assert hook.allowed_calls[0]["partition_key"] == "TENANT#a"
    assert hook.allowed_calls[0]["normalized_limit"] == 10
    assert hook.blocked_calls == []


def test_validate_regulated_query_partition_blocked_calls_audit_hook():
    hook = _CaptureAuditHook()
    profile = build_regulated_profile(audit_hook=hook)

    with pytest.raises(PartitionKeyValidationError):
        validate_regulated_query(
            profile,
            partition_key="DISEASE#x",
            filter_text=None,
            limit=10,
        )

    assert len(hook.blocked_calls) == 1
    assert "must start with one of" in hook.blocked_calls[0]["reason"]
    assert hook.allowed_calls == []


def test_validate_regulated_query_filter_blocked_calls_audit_hook():
    hook = _CaptureAuditHook()
    profile = build_regulated_profile(
        allowed_filter_fields=frozenset({"status"}),
        audit_hook=hook,
    )

    with pytest.raises(FilterPolicyViolationError):
        validate_regulated_query(
            profile,
            partition_key="TENANT#a",
            filter_text="age gt 18",
            limit=10,
        )

    assert len(hook.blocked_calls) == 1
    assert "Field 'age' is not allowed" in hook.blocked_calls[0]["reason"]
