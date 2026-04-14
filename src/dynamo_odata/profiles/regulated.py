from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..dynamo_filter import validate_filter
from ..guardrails import FilterPolicy, PartitionKeyGuard

DEFAULT_FORBIDDEN_RESPONSE_FIELDS = frozenset(
    {
        "pk",
        "sk",
        "PK",
        "SK",
        "ttl",
        "lsis1",
        "lsis2",
        "lsis3",
        "lsin4",
        "lsin5",
        "analytics_uuid",
    }
)

DEFAULT_ALLOWED_FUNCTIONS = frozenset(
    {
        "contains",
        "startswith",
        "tolower",
        "exists",
        "not_exists",
    }
)

DEFAULT_ALLOWED_COMPARATORS = frozenset(
    {
        "eq",
        "ne",
        "lt",
        "le",
        "gt",
        "ge",
        "in",
        "between",
    }
)


class AuditHook(Protocol):
    def on_query_allowed(
        self,
        *,
        partition_key: str,
        filter_text: str | None,
        normalized_limit: int,
    ) -> None: ...

    def on_query_blocked(
        self,
        *,
        reason: str,
        partition_key: str,
        filter_text: str | None,
        requested_limit: int | None,
    ) -> None: ...


class NoOpAuditHook:
    def on_query_allowed(
        self,
        *,
        partition_key: str,
        filter_text: str | None,
        normalized_limit: int,
    ) -> None:
        del partition_key, filter_text, normalized_limit

    def on_query_blocked(
        self,
        *,
        reason: str,
        partition_key: str,
        filter_text: str | None,
        requested_limit: int | None,
    ) -> None:
        del reason, partition_key, filter_text, requested_limit


@dataclass(frozen=True)
class RegulatedProfile:
    partition_guard: PartitionKeyGuard
    filter_policy: FilterPolicy
    forbidden_response_fields: frozenset[str]
    max_page_size: int
    audit_hook: AuditHook


def build_regulated_profile(
    *,
    partition_prefixes: tuple[str, ...] = ("TENANT#",),
    allowed_filter_fields: frozenset[str] | None = None,
    allowed_filter_functions: frozenset[str] = DEFAULT_ALLOWED_FUNCTIONS,
    allowed_filter_comparators: frozenset[str] = DEFAULT_ALLOWED_COMPARATORS,
    max_filter_predicates: int = 8,
    max_filter_depth: int = 8,
    forbidden_response_fields: frozenset[str] = DEFAULT_FORBIDDEN_RESPONSE_FIELDS,
    max_page_size: int = 100,
    audit_hook: AuditHook | None = None,
) -> RegulatedProfile:
    if max_page_size < 1:
        raise ValueError("max_page_size must be >= 1")

    return RegulatedProfile(
        partition_guard=PartitionKeyGuard(partition_prefixes),
        filter_policy=FilterPolicy(
            allowed_fields=allowed_filter_fields,
            allowed_functions=allowed_filter_functions,
            allowed_comparators=allowed_filter_comparators,
            max_predicates=max_filter_predicates,
            max_depth=max_filter_depth,
        ),
        forbidden_response_fields=forbidden_response_fields,
        max_page_size=max_page_size,
        audit_hook=audit_hook or NoOpAuditHook(),
    )


def apply_response_field_policy(
    items: list[dict[str, Any]],
    forbidden_fields: frozenset[str],
) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in item.items() if key not in forbidden_fields}
        for item in items
    ]


def apply_response_allowlist(
    items: list[dict[str, Any]],
    allowed_fields: frozenset[str],
) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in item.items() if key in allowed_fields}
        for item in items
    ]


def validate_page_size(
    limit: int | None,
    max_page_size: int,
    default_page_size: int | None = None,
) -> int:
    if max_page_size < 1:
        raise ValueError("max_page_size must be >= 1")

    normalized_default = (
        max_page_size if default_page_size is None else default_page_size
    )
    if normalized_default < 1:
        raise ValueError("default_page_size must be >= 1")
    if normalized_default > max_page_size:
        raise ValueError("default_page_size must be <= max_page_size")

    if limit is None:
        return normalized_default
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if limit > max_page_size:
        raise ValueError(f"limit {limit} exceeds max_page_size {max_page_size}")
    return limit


def validate_regulated_query(
    profile: RegulatedProfile,
    *,
    partition_key: str,
    filter_text: str | None,
    limit: int | None,
    default_page_size: int | None = None,
) -> int:
    try:
        profile.partition_guard.validate(partition_key)
        if filter_text:
            validate_filter(filter_text, profile.filter_policy)
        normalized_limit = validate_page_size(
            limit=limit,
            max_page_size=profile.max_page_size,
            default_page_size=default_page_size,
        )
    except Exception as exc:
        profile.audit_hook.on_query_blocked(
            reason=str(exc),
            partition_key=partition_key,
            filter_text=filter_text,
            requested_limit=limit,
        )
        raise

    profile.audit_hook.on_query_allowed(
        partition_key=partition_key,
        filter_text=filter_text,
        normalized_limit=normalized_limit,
    )
    return normalized_limit
