from unittest.mock import MagicMock, patch

import pytest

from dynamo_odata import (
    DynamoDb,
    FilterPolicy,
    FilterPolicyViolationError,
    PartitionKeyGuard,
    PartitionKeyValidationError,
    build_filter,
    validate_filter,
)


def _make_db(
    partition_key_guard: PartitionKeyGuard | None = None,
    filter_policy: FilterPolicy | None = None,
) -> DynamoDb:
    with patch("dynamo_odata.db.boto3") as mock_boto3:
        mock_resource = MagicMock()
        mock_table = MagicMock()
        mock_table.name = "table_dev"
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        db = DynamoDb(
            table_name="table_dev",
            partition_key_guard=partition_key_guard,
            filter_policy=filter_policy,
        )
        db.table = mock_table
        db.db = mock_resource
        return db


class TestFilterPolicy:
    def test_allowed_field_passes(self):
        policy = FilterPolicy(allowed_fields=frozenset({"status"}))

        condition = build_filter("status eq 'active'", policy=policy)

        assert condition is not None

    def test_disallowed_field_fails(self):
        policy = FilterPolicy(allowed_fields=frozenset({"status"}))

        with pytest.raises(
            FilterPolicyViolationError, match="Field 'age' is not allowed"
        ):
            validate_filter("age gt 18", policy)

    def test_disallowed_function_fails(self):
        policy = FilterPolicy(allowed_functions=frozenset({"contains"}))

        with pytest.raises(
            FilterPolicyViolationError,
            match="Function 'startswith' is not allowed",
        ):
            build_filter("startswith(name, 'A')", policy=policy)

    def test_max_predicates_fails(self):
        policy = FilterPolicy(max_predicates=1)

        with pytest.raises(FilterPolicyViolationError, match="max is 1"):
            build_filter("status eq 'active' and age gt 18", policy=policy)


class TestPartitionKeyGuard:
    def test_guard_rejects_non_tenant_partition(self):
        db = _make_db(partition_key_guard=PartitionKeyGuard(("TENANT#",)))

        with pytest.raises(
            PartitionKeyValidationError,
            match="must start with one of: TENANT#",
        ):
            db.get_all("DISEASE#abc", item_only=True)

    def test_guard_allows_tenant_partition(self):
        db = _make_db(partition_key_guard=PartitionKeyGuard(("TENANT#",)))
        db.table.get_item.return_value = {"Item": {"pk": "TENANT#1", "sk": "1#USER#1"}}

        result = db.get("TENANT#1", "1#USER#1", item_only=True)

        assert result == {"pk": "TENANT#1", "sk": "1#USER#1"}

    def test_db_filter_policy_is_enforced_on_get_all(self):
        db = _make_db(filter_policy=FilterPolicy(allowed_fields=frozenset({"status"})))

        with pytest.raises(
            FilterPolicyViolationError, match="Field 'age' is not allowed"
        ):
            db.get_all("tenant::1", filter="age gt 18", item_only=True)

        db.table.query.assert_not_called()
